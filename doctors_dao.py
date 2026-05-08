"""
وظيفة الملف: كائن الوصول لبيانات الأطباء (Doctors DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية وأمنية:
- [Deep RBAC]: الإدارة (إضافة، تعديل، تعطيل) محصورة بمدير النظام (admin).
- [Operational Access]: القراءة والبحث متاحة للموظفين (للاستخدام في الوصفات ونقاط البيع).
- [Soft Delete]: يُمنع الحذف الجذري لحماية النزاهة المرجعية للوصفات الطبية التاريخية، ويُستبدل بتعطيل الحساب.
- [Data Integrity]: منع تكرار رقم الرخصة الطبية.
"""

from database.db_manager import DatabaseManager
import json


class DoctorsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _log_breach(self, cursor, user_id, action_desc):
        """توثيق محاولة التجاوز الأمني"""
        breach_payload = json.dumps({"SECURITY_BREACH": action_desc})
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, old_values)
            VALUES (?, 'UPDATE', 'doctors', ?)
        """, (user_id, breach_payload))

    def get_all_doctors(self, active_only=True):
        """جلب الأطباء (متاح للجميع للعمليات التشغيلية)"""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            if active_only:
                cursor.execute(
                    "SELECT id, name, specialty, phone, license_number, notes, is_active FROM doctors WHERE is_active = 1 ORDER BY name ASC")
            else:
                cursor.execute(
                    "SELECT id, name, specialty, phone, license_number, notes, is_active FROM doctors ORDER BY name ASC")
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching doctors: {e}")
            return []
        finally:
            conn.close()

    def search_doctor(self, text, active_only=True):
        """البحث عن طبيب بالاسم أو رقم الرخصة أو الهاتف"""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            search_term = f"%{text}%"
            query = """
                SELECT id, name, specialty, phone, license_number, notes, is_active 
                FROM doctors 
                WHERE (name LIKE ? OR phone LIKE ? OR license_number LIKE ?)
            """
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY name ASC"

            cursor.execute(query, (search_term, search_term, search_term))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error searching doctors: {e}")
            return []
        finally:
            conn.close()

    def add_doctor(self, requester_id, name, specialty, phone, license_number, notes):
        """
        إضافة طبيب جديد.
        [Deep RBAC]: Admin only.
        """
        if not requester_id: return False, "المستخدم غير محدد."

        clean_name = name.strip()
        if not clean_name:
            return False, "اسم الطبيب حقل إلزامي."

        # تنظيف رقم الرخصة ليكون None إذا كان فارغاً (لتجنب تعارض قيد UNIQUE مع القيم الفارغة)
        clean_license = license_number.strip() if license_number and license_number.strip() else None

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # 1. التحقق العميق من الصلاحية
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized attempt to add doctor: {clean_name}")
                conn.commit()
                raise Exception("صلاحيات غير كافية. إضافة الأطباء تتطلب صلاحية 'مدير النظام'.")

            # 2. التحقق من عدم تكرار رقم الرخصة
            if clean_license:
                cursor.execute("SELECT id FROM doctors WHERE license_number = ?", (clean_license,))
                if cursor.fetchone():
                    raise Exception(f"رقم الرخصة الطبية ({clean_license}) مسجل مسبقاً لطبيب آخر.")

            # 3. الإدراج
            cursor.execute("""
                INSERT INTO doctors (name, specialty, phone, license_number, notes, is_active) 
                VALUES (?, ?, ?, ?, ?, 1)
            """, (clean_name, specialty, phone, clean_license, notes))

            doctor_id = cursor.lastrowid

            # 4. التوثيق الأمني
            audit_payload = json.dumps({"name": clean_name, "specialty": specialty, "license": clean_license})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'doctors', ?, ?)
            """, (requester_id, doctor_id, audit_payload))

            conn.commit()
            return True, "تمت إضافة بيانات الطبيب بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_doctor(self, requester_id, doctor_id, name, specialty, phone, license_number, notes):
        """
        تعديل بيانات الطبيب.
        [Deep RBAC]: Admin only.
        """
        if not requester_id or not doctor_id: return False, "بيانات غير مكتملة."

        clean_name = name.strip()
        if not clean_name: return False, "اسم الطبيب حقل إلزامي."
        clean_license = license_number.strip() if license_number and license_number.strip() else None

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            # 1. التحقق من الصلاحية
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized attempt to update doctor ID: {doctor_id}")
                conn.commit()
                raise Exception("صلاحيات غير كافية.")

            # 2. التحقق من عدم تكرار رقم الرخصة (مع استثناء الطبيب الحالي)
            if clean_license:
                cursor.execute("SELECT id FROM doctors WHERE license_number = ? AND id != ?",
                               (clean_license, doctor_id))
                if cursor.fetchone():
                    raise Exception(f"رقم الرخصة الطبية ({clean_license}) مسجل مسبقاً لطبيب آخر.")

            # 3. جلب القيم القديمة للتوثيق
            cursor.execute("SELECT name, specialty, license_number FROM doctors WHERE id = ?", (doctor_id,))
            old_data = cursor.fetchone()
            if not old_data:
                raise Exception("بيانات الطبيب غير موجودة.")

            old_payload = json.dumps({"name": old_data[0], "specialty": old_data[1], "license": old_data[2]})

            # 4. التحديث
            cursor.execute("""
                UPDATE doctors SET name = ?, specialty = ?, phone = ?, license_number = ?, notes = ? WHERE id = ?
            """, (clean_name, specialty, phone, clean_license, notes, doctor_id))

            # 5. التوثيق الأمني
            new_payload = json.dumps({"name": clean_name, "specialty": specialty, "license": clean_license})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'doctors', ?, ?, ?)
            """, (requester_id, doctor_id, old_payload, new_payload))

            conn.commit()
            return True, "تم تحديث بيانات الطبيب بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def toggle_doctor_status(self, requester_id, doctor_id, make_active: bool):
        """
        تفعيل أو تعطيل حساب الطبيب (Soft Delete).
        [Deep RBAC]: Admin only.
        """
        if not requester_id or not doctor_id: return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            # 1. التحقق من الصلاحية
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized attempt to toggle doctor ID: {doctor_id}")
                conn.commit()
                raise Exception("صلاحيات غير كافية.")

            # 2. التحقق من وجود الطبيب
            cursor.execute("SELECT name, is_active FROM doctors WHERE id = ?", (doctor_id,))
            target = cursor.fetchone()
            if not target:
                raise Exception("الطبيب المحدد غير موجود.")

            doctor_name, current_status = target
            new_status_int = 1 if make_active else 0

            if current_status == new_status_int:
                return True, "الحالة مطابقة بالفعل ولا تحتاج لتعديل."

            # 3. تنفيذ التعديل (Soft Delete / Reactivate)
            cursor.execute("UPDATE doctors SET is_active = ? WHERE id = ?", (new_status_int, doctor_id))

            # 4. التوثيق الأمني
            status_text = "Activated" if make_active else "Deactivated (Soft Delete)"
            audit_payload = json.dumps({"action": status_text, "doctor_name": doctor_name})

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'doctors', ?, ?)
            """, (requester_id, doctor_id, audit_payload))

            conn.commit()
            action_ar = "تفعيل" if make_active else "تعطيل"
            return True, f"تم {action_ar} سجل الطبيب ({doctor_name}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()