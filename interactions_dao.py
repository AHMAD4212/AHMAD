"""
وظيفة الملف: كائن الوصول لبيانات التداخلات الدوائية (Drug Interactions DAO).
الطبقة: Data Access Layer / Business Logic

ملاحظات معمارية وأمنية:
- [Canonical Form]&#58; يتم تنظيف المكونات الفعالة وترتيبها canonical ordering
  قبل الحفظ والفحص لمنع التكرار العكسي (A+B == B+A).
- [Deep RBAC]&#58; إدارة التداخلات (إضافة/تعديل/تعطيل/حذف) محصورة بـ (admin, pharmacist).
- [Soft Governance]&#58; التفعيل/التعطيل يتم عبر is_active دون الحاجة لحذف السجل دائماً.
- [Hard Delete Allowed]&#58; الحذف الجذري مسموح لأن التداخلات لا ترتبط بقيود مالية تشغيلية.
- [Clinical Contract]&#58; الوصف السريري الحقيقي محفوظ في clinical_effect،
  مع حقول إضافية للإجراء المقترح والمصدر المرجعي وخطة الإدارة.
- [Cart Safety Engine]&#58; فحص السلة يعتمد حالياً على active_ingredient النصي في جدول medicines.
"""

from database.db_manager import DatabaseManager
import json


class InteractionsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # أدوات داخلية مساعدة
    # ==========================================
    def _normalize_text(self, value):
        """تنظيف نصي آمن: trim + lower + دمج الفراغات."""
        if value is None:
            return ""
        return " ".join(str(value).strip().lower().split())

    def _normalize_optional_text(self, value):
        """تنظيف للنصوص الاختيارية دون lower-case إجباري."""
        if value is None:
            return ""
        return str(value).strip()

    def _canonicalize_ingredients(self, ing1, ing2):
        """
        تنظيف وترتيب المكونات الفعالة لضمان:
        aspirin + ibuprofen == ibuprofen + aspirin
        """
        c_ing1 = self._normalize_text(ing1)
        c_ing2 = self._normalize_text(ing2)

        if not c_ing1 or not c_ing2:
            raise ValueError("يجب تحديد المادتين الفعالتين.")
        if c_ing1 == c_ing2:
            raise ValueError("لا يمكن إضافة تداخل للمادة مع نفسها.")

        return (c_ing1, c_ing2) if c_ing1 < c_ing2 else (c_ing2, c_ing1)

    def _validate_severity(self, severity):
        allowed = {"minor", "moderate", "major", "contraindicated"}
        clean = self._normalize_text(severity)
        if clean not in allowed:
            raise ValueError("درجة الخطورة غير صالحة. القيم المسموحة: minor, moderate, major, contraindicated.")
        return clean

    def _validate_required_text(self, value, field_name):
        clean = self._normalize_optional_text(value)
        if not clean:
            raise ValueError(f"{field_name} حقل إلزامي.")
        return clean

    def _check_rbac(self, cursor, user_id, allowed_roles=None):
        if allowed_roles is None:
            allowed_roles = ['admin', 'pharmacist']

        cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user or int(user[1]) == 0:
            raise ValueError("المستخدم غير موجود أو حسابه معطل.")
        if user[0] not in allowed_roles:
            raise ValueError("صلاحيات غير كافية. إدارة التداخلات تتطلب صلاحية صيدلي أو مدير.")

        return True

    def _log_audit(self, cursor, user_id, action, record_id, old_values=None, new_values=None):
        old_payload = old_values if old_values is not None else {}
        new_payload = new_values if new_values is not None else {}

        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
            VALUES (?, ?, 'drug_interactions', ?, ?, ?)
        """, (
            user_id,
            action,
            record_id,
            json.dumps(old_payload, ensure_ascii=False),
            json.dumps(new_payload, ensure_ascii=False)
        ))

    def _fetch_interaction_row(self, cursor, interaction_id):
        cursor.execute("""
            SELECT
                id,
                ingredient_1,
                ingredient_2,
                severity,
                clinical_effect,
                recommendation,
                management_plan,
                source_reference,
                is_active,
                created_by_user_id,
                updated_by_user_id,
                created_at,
                updated_at
            FROM drug_interactions
            WHERE id = ?
        """, (interaction_id,))
        return cursor.fetchone()

    def _row_to_dict(self, row):
        if not row:
            return None

        return {
            "id": row[0],
            "ingredient_1": row[1],
            "ingredient_2": row[2],
            "severity": row[3],
            "clinical_effect": row[4],
            "recommendation": row[5],
            "management_plan": row[6],
            "source_reference": row[7],
            "is_active": row[8],
            "created_by_user_id": row[9],
            "updated_by_user_id": row[10],
            "created_at": row[11],
            "updated_at": row[12],
        }

    # ==========================================
    # CRUD + إدارة الحالة
    # ==========================================
    def add_interaction(
        self,
        requester_id,
        ingredient_1,
        ingredient_2,
        severity,
        clinical_effect,
        recommendation="",
        management_plan="",
        source_reference=""
    ):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            ing1, ing2 = self._canonicalize_ingredients(ingredient_1, ingredient_2)
            sev = self._validate_severity(severity)
            effect = self._validate_required_text(clinical_effect, "الأثر السريري")
            recommendation = self._normalize_optional_text(recommendation)
            management_plan = self._normalize_optional_text(management_plan)
            source_reference = self._normalize_optional_text(source_reference)

            cursor.execute("""
                INSERT INTO drug_interactions (
                    ingredient_1,
                    ingredient_2,
                    severity,
                    clinical_effect,
                    recommendation,
                    management_plan,
                    source_reference,
                    is_active,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                ing1,
                ing2,
                sev,
                effect,
                recommendation,
                management_plan,
                source_reference,
                requester_id
            ))

            interaction_id = cursor.lastrowid

            self._log_audit(
                cursor,
                requester_id,
                "INSERT",
                interaction_id,
                old_values={},
                new_values={
                    "ingredient_1": ing1,
                    "ingredient_2": ing2,
                    "severity": sev,
                    "clinical_effect": effect,
                    "recommendation": recommendation,
                    "management_plan": management_plan,
                    "source_reference": source_reference,
                    "is_active": 1
                }
            )

            conn.commit()
            return True, "تمت إضافة التداخل الدوائي بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, "هذا التداخل مسجل مسبقاً كزوج فعّال في النظام."
            return False, "فشل داخلي أثناء إضافة التداخل الدوائي."
        finally:
            conn.close()

    def update_interaction(
        self,
        requester_id,
        interaction_id,
        ingredient_1,
        ingredient_2,
        severity,
        clinical_effect,
        recommendation="",
        management_plan="",
        source_reference=""
    ):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            old_row = self._fetch_interaction_row(cursor, interaction_id)
            if not old_row:
                raise ValueError("التداخل الدوائي غير موجود.")

            old_payload = self._row_to_dict(old_row)

            ing1, ing2 = self._canonicalize_ingredients(ingredient_1, ingredient_2)
            sev = self._validate_severity(severity)
            effect = self._validate_required_text(clinical_effect, "الأثر السريري")
            recommendation = self._normalize_optional_text(recommendation)
            management_plan = self._normalize_optional_text(management_plan)
            source_reference = self._normalize_optional_text(source_reference)

            cursor.execute("""
                UPDATE drug_interactions
                SET
                    ingredient_1 = ?,
                    ingredient_2 = ?,
                    severity = ?,
                    clinical_effect = ?,
                    recommendation = ?,
                    management_plan = ?,
                    source_reference = ?,
                    updated_by_user_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                ing1,
                ing2,
                sev,
                effect,
                recommendation,
                management_plan,
                source_reference,
                requester_id,
                interaction_id
            ))

            self._log_audit(
                cursor,
                requester_id,
                "UPDATE",
                interaction_id,
                old_values=old_payload,
                new_values={
                    "ingredient_1": ing1,
                    "ingredient_2": ing2,
                    "severity": sev,
                    "clinical_effect": effect,
                    "recommendation": recommendation,
                    "management_plan": management_plan,
                    "source_reference": source_reference
                }
            )

            conn.commit()
            return True, "تم تحديث التداخل الدوائي بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e).upper():
                return False, "يوجد تداخل آخر فعّال بنفس زوج المادتين."
            return False, "فشل داخلي أثناء تحديث التداخل الدوائي."
        finally:
            conn.close()

    def toggle_interaction_status(self, requester_id, interaction_id, new_status=None):
        """
        إذا كانت new_status = None يتم قلب الحالة الحالية.
        وإذا أُرسلت True/False يتم ضبطها صراحة.
        """
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            old_row = self._fetch_interaction_row(cursor, interaction_id)
            if not old_row:
                raise ValueError("التداخل الدوائي غير موجود.")

            old_payload = self._row_to_dict(old_row)
            current_status = int(old_row[8])

            if new_status is None:
                target_status = 0 if current_status == 1 else 1
            else:
                target_status = 1 if bool(new_status) else 0

            cursor.execute("""
                UPDATE drug_interactions
                SET
                    is_active = ?,
                    updated_by_user_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                target_status,
                requester_id,
                interaction_id
            ))

            self._log_audit(
                cursor,
                requester_id,
                "UPDATE",
                interaction_id,
                old_values=old_payload,
                new_values={
                    "is_active": target_status
                }
            )

            conn.commit()
            action_text = "تفعيل" if target_status == 1 else "تعطيل"
            return True, f"تم {action_text} التداخل الدوائي بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            return False, "فشل داخلي أثناء تغيير حالة التداخل."
        finally:
            conn.close()

    def delete_interaction(self, requester_id, interaction_id):
        """
        حذف جذري للتداخل:
        مسموح لأن السجل لا يحمل ارتباطات محاسبية تشغيلية.
        """
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id)

            old_row = self._fetch_interaction_row(cursor, interaction_id)
            if not old_row:
                raise ValueError("التداخل الدوائي غير موجود.")

            old_payload = self._row_to_dict(old_row)

            cursor.execute("DELETE FROM drug_interactions WHERE id = ?", (interaction_id,))

            self._log_audit(
                cursor,
                requester_id,
                "DELETE",
                interaction_id,
                old_values=old_payload,
                new_values={}
            )

            conn.commit()
            return True, "تم حذف التداخل الدوائي نهائياً بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            return False, "فشل داخلي أثناء حذف التداخل الدوائي."
        finally:
            conn.close()

    # ==========================================
    # واجهات القراءة للواجهة الرسومية
    # ==========================================
    def get_interaction_by_id(self, interaction_id):
        conn = self.db.connect()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            row = self._fetch_interaction_row(cursor, interaction_id)
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_all_interactions(self, active_only=False):
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()

            query = """
                SELECT
                    i.id,
                    i.ingredient_1,
                    i.ingredient_2,
                    i.severity,
                    i.clinical_effect,
                    i.recommendation,
                    i.management_plan,
                    i.source_reference,
                    i.is_active,
                    u.username,
                    i.created_at,
                    i.updated_at
                FROM drug_interactions i
                LEFT JOIN users u ON i.created_by_user_id = u.id
            """
            params = []

            if active_only:
                query += " WHERE i.is_active = 1"

            query += """
                ORDER BY
                    CASE i.severity
                        WHEN 'contraindicated' THEN 1
                        WHEN 'major' THEN 2
                        WHEN 'moderate' THEN 3
                        WHEN 'minor' THEN 4
                        ELSE 5
                    END,
                    i.ingredient_1 ASC,
                    i.ingredient_2 ASC
            """

            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        finally:
            conn.close()

    def search_interactions(self, text, active_only=False):
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()

            clean = self._normalize_text(text)
            raw = self._normalize_optional_text(text)

            if not clean and not raw:
                return self.get_all_interactions(active_only=active_only)

            like_norm = f"%{clean}%"
            like_raw = f"%{raw.strip()}%"

            query = """
                SELECT
                    i.id,
                    i.ingredient_1,
                    i.ingredient_2,
                    i.severity,
                    i.clinical_effect,
                    i.recommendation,
                    i.management_plan,
                    i.source_reference,
                    i.is_active,
                    u.username,
                    i.created_at,
                    i.updated_at
                FROM drug_interactions i
                LEFT JOIN users u ON i.created_by_user_id = u.id
                WHERE (
                    LOWER(TRIM(i.ingredient_1)) LIKE ?
                    OR LOWER(TRIM(i.ingredient_2)) LIKE ?
                    OR LOWER(TRIM(i.clinical_effect)) LIKE ?
                    OR LOWER(TRIM(COALESCE(i.recommendation, ''))) LIKE ?
                    OR LOWER(TRIM(COALESCE(i.management_plan, ''))) LIKE ?
                    OR LOWER(TRIM(COALESCE(i.source_reference, ''))) LIKE ?
                    OR LOWER(TRIM(i.severity)) LIKE ?
                )
            """
            params = [
                like_norm,
                like_norm,
                like_norm,
                like_norm,
                like_norm,
                like_norm,
                like_norm
            ]

            if active_only:
                query += " AND i.is_active = 1"

            query += """
                ORDER BY
                    CASE i.severity
                        WHEN 'contraindicated' THEN 1
                        WHEN 'major' THEN 2
                        WHEN 'moderate' THEN 3
                        WHEN 'minor' THEN 4
                        ELSE 5
                    END,
                    i.ingredient_1 ASC,
                    i.ingredient_2 ASC
            """

            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        finally:
            conn.close()

    # ==========================================
    # محرك فحص السلة / الوصفة
    # ==========================================
    def check_cart_interactions(self, medicine_ids_list):
        """
        فحص سلة البيع أو عناصر الوصفة لاكتشاف التداخلات الفعّالة فقط.

        المخرج:
        {
            "minor": [...],
            "moderate": [...],
            "major": [...],
            "contraindicated": [...]
        }
        """
        results = {
            "minor": [],
            "moderate": [],
            "major": [],
            "contraindicated": []
        }

        if not medicine_ids_list or len(medicine_ids_list) < 2:
            return results

        conn = self.db.connect()
        if not conn:
            return results

        try:
            cursor = conn.cursor()

            clean_ids = []
            seen_ids = set()
            for med_id in medicine_ids_list:
                try:
                    med_id_int = int(med_id)
                except Exception:
                    continue

                if med_id_int not in seen_ids:
                    seen_ids.add(med_id_int)
                    clean_ids.append(med_id_int)

            if len(clean_ids) < 2:
                return results

            placeholders = ",".join("?" * len(clean_ids))
            cursor.execute(f"""
                SELECT id, name, active_ingredient
                FROM medicines
                WHERE id IN ({placeholders})
            """, tuple(clean_ids))
            medicines = cursor.fetchall()

            valid_meds = []
            for med in medicines:
                med_id, med_name, active_ing = med
                clean_ing = self._normalize_text(active_ing)
                if clean_ing:
                    valid_meds.append({
                        "id": med_id,
                        "name": med_name,
                        "ingredient": clean_ing
                    })

            if len(valid_meds) < 2:
                return results

            checked_pairs = set()

            for i in range(len(valid_meds)):
                for j in range(i + 1, len(valid_meds)):
                    med_a = valid_meds[i]
                    med_b = valid_meds[j]

                    try:
                        ing1, ing2 = self._canonicalize_ingredients(
                            med_a["ingredient"],
                            med_b["ingredient"]
                        )
                    except Exception:
                        continue

                    if (ing1, ing2) in checked_pairs:
                        continue
                    checked_pairs.add((ing1, ing2))

                    cursor.execute("""
                        SELECT
                            id,
                            severity,
                            clinical_effect,
                            recommendation,
                            management_plan,
                            source_reference
                        FROM drug_interactions
                        WHERE ingredient_1 = ?
                          AND ingredient_2 = ?
                          AND is_active = 1
                        LIMIT 1
                    """, (ing1, ing2))

                    interaction = cursor.fetchone()
                    if not interaction:
                        continue

                    interaction_id, severity, clinical_effect, recommendation, management_plan, source_reference = interaction

                    warning_item = {
                        "interaction_id": interaction_id,
                        "medicine_1": med_a["name"],
                        "medicine_2": med_b["name"],
                        "ingredient_1": ing1,
                        "ingredient_2": ing2,
                        "clinical_effect": clinical_effect,
                        "recommendation": recommendation or "",
                        "management_plan": management_plan or "",
                        "source_reference": source_reference or ""
                    }

                    if severity in results:
                        results[severity].append(warning_item)

            return results

        except Exception:
            return results
        finally:
            conn.close()