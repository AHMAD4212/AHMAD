"""
وظيفة الملف: كائن الوصول لبيانات السلامة الدوائية (Drug Safety Profiles DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية وأمنية:
- [Canonicalization]: يتم توحيد (ingredient_key) و (effect_name) برمجياً (تحويل لأحرف صغيرة، إزالة الفراغات الزائدة) لضمان دقة مفاتيح الربط والقيود (UNIQUE).
- [Deep RBAC]: الإضافة، التعديل، والحذف محصورة بـ (admin, pharmacist).
- [V1 Tech Debt]: حقل (max_daily_dose) يُعامل كنص مرجعي (Informational) وليس كحقل حسابي للجرعات.
"""

from database.db_manager import DatabaseManager
import json


class DrugSafetyDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _canonicalize_text(self, text):
        """تنظيف وتوحيد النصوص (للمادة الفعالة والآثار الجانبية)"""
        if not text:
            return ""
        # تحويل لأحرف صغيرة، إزالة الفراغات من الأطراف، ودمج الفراغات المتعددة في فراغ واحد
        return " ".join(str(text).strip().lower().split())

    def _check_rbac(self, cursor, user_id, allowed_roles=['admin', 'pharmacist']):
        cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user or user[1] == 0:
            raise Exception("المستخدم غير موجود أو حسابه معطل.")
        if user[0] not in allowed_roles:
            raise Exception("صلاحيات غير كافية. هذه العملية تتطلب صلاحية 'صيدلي' أو 'مدير'.")
        return True

    def _log_audit(self, cursor, user_id, action, table, record_id, old_val, new_val):
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, action, table, record_id, json.dumps(old_val), json.dumps(new_val)))

    # ==========================================
    # 1. إدارة الملف الرئيسي (Drug Safety Profiles)
    # ==========================================

    def add_safety_profile(self, requester_id, ingredient_text, display_name, contraindications,
                           max_daily_dose, pregnancy_warning, lactation_warning, renal_warning,
                           hepatic_warning, pediatric_warning, geriatric_warning, counseling_notes,
                           overdose_notes, source_reference):

        ingredient_key = self._canonicalize_text(ingredient_text)
        if not ingredient_key or not display_name:
            return False, "المادة الفعالة والاسم المعروض حقول إلزامية."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            cursor.execute("""
                INSERT INTO drug_safety_profiles (
                    ingredient_key, display_name, contraindications, max_daily_dose,
                    pregnancy_warning, lactation_warning, renal_warning, hepatic_warning,
                    pediatric_warning, geriatric_warning, counseling_notes, overdose_notes,
                    source_reference, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ingredient_key, display_name, contraindications, max_daily_dose,
                  pregnancy_warning, lactation_warning, renal_warning, hepatic_warning,
                  pediatric_warning, geriatric_warning, counseling_notes, overdose_notes,
                  source_reference, requester_id))

            profile_id = cursor.lastrowid

            self._log_audit(cursor, requester_id, 'INSERT', 'drug_safety_profiles', profile_id, {},
                            {"ingredient_key": ingredient_key})
            conn.commit()
            return True, "تم إنشاء الملف الطبي للمادة الفعالة بنجاح."

        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, f"الملف الطبي للمادة ({ingredient_key}) موجود مسبقاً."
            return False, str(e)
        finally:
            conn.close()

    def update_safety_profile(self, requester_id, profile_id, ingredient_text, display_name, contraindications,
                              max_daily_dose, pregnancy_warning, lactation_warning, renal_warning,
                              hepatic_warning, pediatric_warning, geriatric_warning, counseling_notes,
                              overdose_notes, source_reference):

        ingredient_key = self._canonicalize_text(ingredient_text)
        if not ingredient_key or not display_name:
            return False, "المادة الفعالة والاسم المعروض حقول إلزامية."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            cursor.execute("SELECT ingredient_key FROM drug_safety_profiles WHERE id = ?", (profile_id,))
            old_data = cursor.fetchone()
            if not old_data:
                raise Exception("الملف الطبي غير موجود.")

            cursor.execute("""
                UPDATE drug_safety_profiles SET
                    ingredient_key = ?, display_name = ?, contraindications = ?, max_daily_dose = ?,
                    pregnancy_warning = ?, lactation_warning = ?, renal_warning = ?, hepatic_warning = ?,
                    pediatric_warning = ?, geriatric_warning = ?, counseling_notes = ?, overdose_notes = ?,
                    source_reference = ?, updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (ingredient_key, display_name, contraindications, max_daily_dose,
                  pregnancy_warning, lactation_warning, renal_warning, hepatic_warning,
                  pediatric_warning, geriatric_warning, counseling_notes, overdose_notes,
                  source_reference, requester_id, profile_id))

            self._log_audit(cursor, requester_id, 'UPDATE', 'drug_safety_profiles', profile_id,
                            {"ingredient_key": old_data[0]}, {"ingredient_key": ingredient_key})
            conn.commit()
            return True, "تم تحديث الملف الطبي بنجاح."

        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, f"يوجد ملف آخر يحمل نفس المادة الفعالة ({ingredient_key})."
            return False, str(e)
        finally:
            conn.close()

    def toggle_profile_status(self, requester_id, profile_id, is_active):
        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."
        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            status_val = 1 if is_active else 0
            cursor.execute(
                "UPDATE drug_safety_profiles SET is_active = ?, updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status_val, requester_id, profile_id))

            self._log_audit(cursor, requester_id, 'UPDATE', 'drug_safety_profiles', profile_id, {},
                            {"is_active": status_val})
            conn.commit()
            action = "تفعيل" if is_active else "تعطيل"
            return True, f"تم {action} الملف الطبي بنجاح."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def get_all_profiles(self, active_only=False):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = "SELECT id, ingredient_key, display_name, is_active, updated_at FROM drug_safety_profiles"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY display_name ASC"
            cursor.execute(query)
            return cursor.fetchall()
        finally:
            conn.close()

    def search_profiles(self, text, active_only=False):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            search_term = f"%{self._canonicalize_text(text)}%"
            display_term = f"%{text}%"

            query = "SELECT id, ingredient_key, display_name, is_active, updated_at FROM drug_safety_profiles WHERE (ingredient_key LIKE ? OR display_name LIKE ?)"
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY display_name ASC"

            cursor.execute(query, (search_term, display_term))
            return cursor.fetchall()
        finally:
            conn.close()

    def get_profile_by_id(self, profile_id):
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM drug_safety_profiles WHERE id = ?", (profile_id,))
            columns = [column[0] for column in cursor.description]
            row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
            return None
        finally:
            conn.close()

    def get_profile_by_ingredient(self, ingredient_text):
        """البحث عن الملف الطبي عبر المادة الفعالة مع التنظيف المسبق"""
        ingredient_key = self._canonicalize_text(ingredient_text)
        if not ingredient_key: return None

        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM drug_safety_profiles WHERE ingredient_key = ? AND is_active = 1",
                           (ingredient_key,))
            columns = [column[0] for column in cursor.description]
            row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
            return None
        finally:
            conn.close()

    def get_profile_by_medicine_id(self, medicine_id):
        """جلب الملف الطبي انطلاقاً من رقم الدواء في المخزون"""
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT active_ingredient FROM medicines WHERE id = ?", (medicine_id,))
            med_row = cursor.fetchone()
            if not med_row or not med_row[0]:
                return None

            ingredient_key = self._canonicalize_text(med_row[0])
            cursor.execute("SELECT * FROM drug_safety_profiles WHERE ingredient_key = ? AND is_active = 1",
                           (ingredient_key,))

            columns = [column[0] for column in cursor.description]
            profile_row = cursor.fetchone()
            if profile_row:
                return dict(zip(columns, profile_row))
            return None
        finally:
            conn.close()

    # ==========================================
    # 2. إدارة الآثار الجانبية (Drug Side Effects)
    # ==========================================

    def add_side_effect(self, requester_id, profile_id, effect_name, frequency, severity, notes):
        clean_effect = self._canonicalize_text(effect_name)
        if not clean_effect or not profile_id: return False, "اسم الأثر الجانبي والملف الطبي حقول إلزامية."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            cursor.execute("""
                INSERT INTO drug_side_effects (profile_id, effect_name, frequency, severity, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (profile_id, clean_effect, frequency, severity, notes))

            se_id = cursor.lastrowid
            self._log_audit(cursor, requester_id, 'INSERT', 'drug_side_effects', se_id, {},
                            {"effect_name": clean_effect})
            conn.commit()
            return True, "تمت إضافة الأثر الجانبي بنجاح."
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, "هذا الأثر الجانبي مسجل مسبقاً لهذا الملف الطبي."
            return False, str(e)
        finally:
            conn.close()

    def update_side_effect(self, requester_id, side_effect_id, effect_name, frequency, severity, notes):
        clean_effect = self._canonicalize_text(effect_name)
        if not clean_effect: return False, "اسم الأثر الجانبي حقل إلزامي."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            cursor.execute(
                "UPDATE drug_side_effects SET effect_name = ?, frequency = ?, severity = ?, notes = ? WHERE id = ?",
                (clean_effect, frequency, severity, notes, side_effect_id))

            self._log_audit(cursor, requester_id, 'UPDATE', 'drug_side_effects', side_effect_id, {},
                            {"effect_name": clean_effect})
            conn.commit()
            return True, "تم تحديث الأثر الجانبي بنجاح."
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, "هذا الأثر الجانبي مسجل مسبقاً لهذا الملف الطبي."
            return False, str(e)
        finally:
            conn.close()

    def delete_side_effect(self, requester_id, side_effect_id):
        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."
        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            cursor.execute("DELETE FROM drug_side_effects WHERE id = ?", (side_effect_id,))
            self._log_audit(cursor, requester_id, 'DELETE', 'drug_side_effects', side_effect_id, {}, {})
            conn.commit()
            return True, "تم حذف الأثر الجانبي بنجاح."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def get_side_effects_for_profile(self, profile_id):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, effect_name, frequency, severity, notes 
                FROM drug_side_effects 
                WHERE profile_id = ?
                ORDER BY 
                    CASE severity WHEN 'severe' THEN 1 WHEN 'moderate' THEN 2 WHEN 'mild' THEN 3 ELSE 4 END,
                    CASE frequency WHEN 'very_rare' THEN 4 WHEN 'rare' THEN 3 WHEN 'uncommon' THEN 2 WHEN 'common' THEN 1 ELSE 5 END
            """, (profile_id,))
            return cursor.fetchall()
        finally:
            conn.close()

    # ==========================================
    # 3. قراءة الملف الكامل (Full Profile)
    # ==========================================

    def get_full_profile(self, profile_id):
        """إرجاع بيانات الملف الرئيسي مع قائمة الآثار الجانبية في كائن واحد"""
        profile = self.get_profile_by_id(profile_id)
        if not profile:
            return None

        side_effects = self.get_side_effects_for_profile(profile_id)

        # تحويل السجلات إلى قواميس لسهولة الاستخدام في الواجهة
        profile['side_effects'] = [
            {
                "id": row[0],
                "effect_name": row[1],
                "frequency": row[2],
                "severity": row[3],
                "notes": row[4]
            } for row in side_effects
        ]

        return profile