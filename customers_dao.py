"""
وظيفة الملف: كائن الوصول لبيانات العملاء والمرضى (Customers DAO).
الطبقة: Data Access Layer / Business Logic

ملاحظة معمارية وأمنية:
- [Extended Patient Profile]&#58; يدعم الحقول الجديدة في V24 مثل:
  national_id, date_of_birth, gender, address, medical_notes, is_active, updated_at
- [Operational Flexibility]&#58; الإضافة والتعديل متاحتان للمستخدم النشط لتسهيل العمل التشغيلي،
  بينما الحذف الجذري يبقى محصوراً بالمدير فقط.
- [Uniqueness Guard]&#58; يمنع تكرار phone / email / national_id عند وجودها فعلاً.
- [Clinical/Financial Integrity]&#58; يمنع حذف العميل إذا كان مرتبطاً بمبيعات أو وصفات أو سجلات رقابية/سريرية.
- [Audit Trails]&#58; توثيق شامل لكافة العمليات ومحاولات التجاوز في audit_logs.
- [Backward Compatibility]&#58; يحافظ على التواقيع القديمة للدوال بحيث لا ينكسر استدعاء الواجهات الحالية.
"""

from database.db_manager import DatabaseManager
import json
import sqlite3
from datetime import datetime


class CustomersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # Helpers
    # ==========================================
    def _sanitize_text(self, value, allow_null=True):
        if value is None:
            return None if allow_null else ""
        clean = " ".join(str(value).strip().split())
        if clean == "":
            return None if allow_null else ""
        return clean

    def _normalize_email(self, email):
        clean = self._sanitize_text(email, allow_null=True)
        return clean.lower() if clean else None

    def _normalize_phone(self, phone):
        clean = self._sanitize_text(phone, allow_null=True)
        if not clean:
            return None

        # تطبيع بسيط وعملي للهاتف لتقليل التكرارات الشكلية
        allowed = []
        for i, ch in enumerate(clean):
            if ch.isdigit():
                allowed.append(ch)
            elif ch == "+" and i == 0:
                allowed.append(ch)

        normalized = "".join(allowed).strip()
        return normalized if normalized else None

    def _normalize_national_id(self, national_id):
        clean = self._sanitize_text(national_id, allow_null=True)
        return clean if clean else None

    def _normalize_gender(self, gender):
        clean = self._sanitize_text(gender, allow_null=True)
        if not clean:
            return None

        low = clean.lower()
        mapping = {
            "male": "male",
            "m": "male",
            "ذكر": "male",
            "رجل": "male",

            "female": "female",
            "f": "female",
            "أنثى": "female",
            "انثى": "female",
            "امرأة": "female",

            "other": "other",
            "o": "other",
            "أخرى": "other",
            "اخرى": "other"
        }
        return mapping.get(low, None)

    def _normalize_date(self, date_value):
        clean = self._sanitize_text(date_value, allow_null=True)
        if not clean:
            return None

        try:
            datetime.strptime(clean, "%Y-%m-%d")
            return clean
        except ValueError:
            raise ValueError("صيغة تاريخ الميلاد يجب أن تكون YYYY-MM-DD.")

    def _ensure_requester_active(self, cursor, requester_id):
        cursor.execute(
            "SELECT id, role, is_active FROM users WHERE id = ?",
            (requester_id,)
        )
        row = cursor.fetchone()
        if not row or int(row[2]) != 1:
            raise ValueError("المستخدم غير موجود أو الحساب غير نشط.")
        return row

    def _log_breach(self, cursor, user_id, action_desc):
        breach_payload = json.dumps({"SECURITY_BREACH": action_desc}, ensure_ascii=False)
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, old_values)
            VALUES (?, 'UPDATE', 'customers', ?)
        """, (user_id, breach_payload))

    def _find_existing_by_field(self, cursor, field_name, field_value, exclude_customer_id=None):
        if not field_value:
            return None

        if field_name == "email":
            query = """
                SELECT id, name
                FROM customers
                WHERE email IS NOT NULL
                  AND LOWER(TRIM(email)) = LOWER(TRIM(?))
            """
        elif field_name == "phone":
            query = """
                SELECT id, name
                FROM customers
                WHERE phone IS NOT NULL
                  AND TRIM(phone) = TRIM(?)
            """
        elif field_name == "national_id":
            query = """
                SELECT id, name
                FROM customers
                WHERE national_id IS NOT NULL
                  AND TRIM(national_id) = TRIM(?)
            """
        else:
            return None

        params = [field_value]

        if exclude_customer_id is not None:
            query += " AND id <> ?"
            params.append(exclude_customer_id)

        query += " LIMIT 1"
        cursor.execute(query, tuple(params))
        return cursor.fetchone()

    def _count_same_name(self, cursor, name, exclude_customer_id=None):
        if not name:
            return 0

        query = "SELECT COUNT(id) FROM customers WHERE TRIM(name) = TRIM(?)"
        params = [name]

        if exclude_customer_id is not None:
            query += " AND id <> ?"
            params.append(exclude_customer_id)

        cursor.execute(query, tuple(params))
        row = cursor.fetchone()
        return row[0] if row else 0

    def _validate_core_fields(
        self,
        name,
        phone=None,
        email=None,
        national_id=None,
        date_of_birth=None,
        gender=None
    ):
        clean_name = self._sanitize_text(name, allow_null=False)
        if not clean_name:
            raise ValueError("اسم العميل/المريض حقل إلزامي.")

        clean_phone = self._normalize_phone(phone)
        clean_email = self._normalize_email(email)
        clean_national_id = self._normalize_national_id(national_id)
        clean_dob = self._normalize_date(date_of_birth)
        clean_gender = self._normalize_gender(gender)

        if email and clean_email is None:
            raise ValueError("البريد الإلكتروني غير صالح.")

        if gender and clean_gender is None:
            raise ValueError("قيمة الجنس غير صالحة. القيم المعتمدة: male / female / other.")

        return {
            "name": clean_name,
            "phone": clean_phone,
            "email": clean_email,
            "national_id": clean_national_id,
            "date_of_birth": clean_dob,
            "gender": clean_gender
        }

    def _build_duplicate_error(self, field_label, existing_row):
        existing_id, existing_name = existing_row
        return f"{field_label} مستخدم مسبقاً من قبل سجل آخر (ID: {existing_id} - {existing_name})."

    # ==========================================
    # Read APIs
    # ==========================================
    def get_all_customers(self, active_only=True):
        """
        جلب جميع العملاء/المرضى.
        يحافظ على id و name في أول عمودين لعدم كسر الواجهات الحالية.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT
                    id,
                    name,
                    phone,
                    email,
                    national_id,
                    date_of_birth,
                    gender,
                    address,
                    medical_notes,
                    is_active,
                    notes
                FROM customers
            """
            params = []

            if active_only and self._column_exists_safe(cursor, "customers", "is_active"):
                query += " WHERE is_active = 1"

            query += " ORDER BY name ASC, id ASC"
            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching customers: {e}")
            return []
        finally:
            conn.close()

    def search_customer(self, text, active_only=True):
        """
        البحث في العملاء/المرضى بالاسم أو الهاتف أو البريد أو الهوية.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            search_term = f"%{text.strip()}%"

            query = """
                SELECT
                    id,
                    name,
                    phone,
                    email,
                    national_id,
                    date_of_birth,
                    gender,
                    address,
                    medical_notes,
                    is_active,
                    notes
                FROM customers
                WHERE (
                    name LIKE ?
                    OR phone LIKE ?
                    OR email LIKE ?
                    OR national_id LIKE ?
                )
            """
            params = [search_term, search_term, search_term, search_term]

            if active_only and self._column_exists_safe(cursor, "customers", "is_active"):
                query += " AND is_active = 1"

            query += " ORDER BY name ASC, id ASC"
            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error searching customers: {e}")
            return []
        finally:
            conn.close()

    def get_customer_by_id(self, customer_id):
        conn = self.db.connect()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    id,
                    name,
                    phone,
                    email,
                    national_id,
                    date_of_birth,
                    gender,
                    address,
                    medical_notes,
                    is_active,
                    notes,
                    created_at,
                    updated_at
                FROM customers
                WHERE id = ?
            """, (customer_id,))
            return cursor.fetchone()
        except Exception as e:
            print(f"Error fetching customer by id: {e}")
            return None
        finally:
            conn.close()

    def find_exact_name_matches(self, name, exclude_customer_id=None):
        clean_name = self._sanitize_text(name, allow_null=False)
        if not clean_name:
            return []

        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT id, name, phone, email, national_id
                FROM customers
                WHERE TRIM(name) = TRIM(?)
            """
            params = [clean_name]

            if exclude_customer_id is not None:
                query += " AND id <> ?"
                params.append(exclude_customer_id)

            query += " ORDER BY id ASC"
            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error finding name duplicates: {e}")
            return []
        finally:
            conn.close()

    def _column_exists_safe(self, cursor, table_name, column_name):
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            return column_name in columns
        except Exception:
            return False

    # ==========================================
    # Write APIs
    # ==========================================
    def add_customer(
        self,
        requester_id,
        name,
        phone="",
        email="",
        notes="",
        national_id="",
        date_of_birth=None,
        gender=None,
        address="",
        medical_notes="",
        is_active=1
    ):
        """
        إضافة عميل/مريض جديد.
        متاحة للمستخدم النشط لتسهيل العمل التشغيلي.
        """
        if not requester_id:
            return False, "المستخدم غير محدد."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._ensure_requester_active(cursor, requester_id)

            normalized = self._validate_core_fields(
                name=name,
                phone=phone,
                email=email,
                national_id=national_id,
                date_of_birth=date_of_birth,
                gender=gender
            )

            clean_notes = self._sanitize_text(notes, allow_null=True)
            clean_address = self._sanitize_text(address, allow_null=True)
            clean_medical_notes = self._sanitize_text(medical_notes, allow_null=True)
            safe_is_active = 1 if int(is_active) == 1 else 0

            if normalized["phone"]:
                existing = self._find_existing_by_field(cursor, "phone", normalized["phone"])
                if existing:
                    raise ValueError(self._build_duplicate_error("رقم الهاتف", existing))

            if normalized["email"]:
                existing = self._find_existing_by_field(cursor, "email", normalized["email"])
                if existing:
                    raise ValueError(self._build_duplicate_error("البريد الإلكتروني", existing))

            if normalized["national_id"]:
                existing = self._find_existing_by_field(cursor, "national_id", normalized["national_id"])
                if existing:
                    raise ValueError(self._build_duplicate_error("رقم الهوية", existing))

            same_name_count = self._count_same_name(cursor, normalized["name"])

            cursor.execute("""
                INSERT INTO customers (
                    name, phone, email, national_id, date_of_birth, gender,
                    address, notes, medical_notes, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                normalized["name"],
                normalized["phone"],
                normalized["email"],
                normalized["national_id"],
                normalized["date_of_birth"],
                normalized["gender"],
                clean_address,
                clean_notes,
                clean_medical_notes,
                safe_is_active
            ))
            customer_id = cursor.lastrowid

            audit_payload = json.dumps({
                "name": normalized["name"],
                "phone": normalized["phone"],
                "email": normalized["email"],
                "national_id": normalized["national_id"],
                "date_of_birth": normalized["date_of_birth"],
                "gender": normalized["gender"],
                "address": clean_address,
                "notes": clean_notes,
                "medical_notes": clean_medical_notes,
                "is_active": safe_is_active
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'customers', ?, ?)
            """, (requester_id, customer_id, audit_payload))

            conn.commit()

            if same_name_count > 0:
                return True, "تمت إضافة العميل/المريض بنجاح. تنبيه: يوجد سجل آخر بنفس الاسم، يرجى التحقق من الهوية أو الهاتف لتفادي الالتباس."
            return True, "تمت إضافة العميل/المريض بنجاح."

        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()

            if "phone" in error_msg:
                return False, "رقم الهاتف مستخدم مسبقاً."
            if "email" in error_msg:
                return False, "البريد الإلكتروني مستخدم مسبقاً."
            if "national_id" in error_msg:
                return False, "رقم الهوية مستخدم مسبقاً."

            return False, "حدث تعارض تكاملي في بيانات العميل/المريض."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_customer(
        self,
        requester_id,
        customer_id,
        name,
        phone="",
        email="",
        notes="",
        national_id="",
        date_of_birth=None,
        gender=None,
        address="",
        medical_notes="",
        is_active=1
    ):
        """
        تعديل بيانات العميل/المريض.
        متاحة للمستخدم النشط.
        """
        if not requester_id or not customer_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            self._ensure_requester_active(cursor, requester_id)

            normalized = self._validate_core_fields(
                name=name,
                phone=phone,
                email=email,
                national_id=national_id,
                date_of_birth=date_of_birth,
                gender=gender
            )

            clean_notes = self._sanitize_text(notes, allow_null=True)
            clean_address = self._sanitize_text(address, allow_null=True)
            clean_medical_notes = self._sanitize_text(medical_notes, allow_null=True)
            safe_is_active = 1 if int(is_active) == 1 else 0

            cursor.execute("""
                SELECT
                    name, phone, email, national_id, date_of_birth, gender,
                    address, notes, medical_notes, is_active
                FROM customers
                WHERE id = ?
            """, (customer_id,))
            old_data = cursor.fetchone()

            if not old_data:
                raise ValueError("العميل/المريض غير موجود.")

            if normalized["phone"]:
                existing = self._find_existing_by_field(cursor, "phone", normalized["phone"], exclude_customer_id=customer_id)
                if existing:
                    raise ValueError(self._build_duplicate_error("رقم الهاتف", existing))

            if normalized["email"]:
                existing = self._find_existing_by_field(cursor, "email", normalized["email"], exclude_customer_id=customer_id)
                if existing:
                    raise ValueError(self._build_duplicate_error("البريد الإلكتروني", existing))

            if normalized["national_id"]:
                existing = self._find_existing_by_field(cursor, "national_id", normalized["national_id"], exclude_customer_id=customer_id)
                if existing:
                    raise ValueError(self._build_duplicate_error("رقم الهوية", existing))

            same_name_count = self._count_same_name(cursor, normalized["name"], exclude_customer_id=customer_id)

            old_payload = json.dumps({
                "name": old_data[0],
                "phone": old_data[1],
                "email": old_data[2],
                "national_id": old_data[3],
                "date_of_birth": old_data[4],
                "gender": old_data[5],
                "address": old_data[6],
                "notes": old_data[7],
                "medical_notes": old_data[8],
                "is_active": old_data[9]
            }, ensure_ascii=False)

            cursor.execute("""
                UPDATE customers
                SET
                    name = ?,
                    phone = ?,
                    email = ?,
                    national_id = ?,
                    date_of_birth = ?,
                    gender = ?,
                    address = ?,
                    notes = ?,
                    medical_notes = ?,
                    is_active = ?
                WHERE id = ?
            """, (
                normalized["name"],
                normalized["phone"],
                normalized["email"],
                normalized["national_id"],
                normalized["date_of_birth"],
                normalized["gender"],
                clean_address,
                clean_notes,
                clean_medical_notes,
                safe_is_active,
                customer_id
            ))

            new_payload = json.dumps({
                "name": normalized["name"],
                "phone": normalized["phone"],
                "email": normalized["email"],
                "national_id": normalized["national_id"],
                "date_of_birth": normalized["date_of_birth"],
                "gender": normalized["gender"],
                "address": clean_address,
                "notes": clean_notes,
                "medical_notes": clean_medical_notes,
                "is_active": safe_is_active
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'customers', ?, ?, ?)
            """, (requester_id, customer_id, old_payload, new_payload))

            conn.commit()

            if same_name_count > 0:
                return True, "تم تحديث بيانات العميل/المريض بنجاح. تنبيه: يوجد سجل آخر بنفس الاسم، يرجى التحقق من الهوية أو الهاتف لتفادي الالتباس."
            return True, "تم تحديث بيانات العميل/المريض بنجاح."

        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()

            if "phone" in error_msg:
                return False, "رقم الهاتف مستخدم مسبقاً."
            if "email" in error_msg:
                return False, "البريد الإلكتروني مستخدم مسبقاً."
            if "national_id" in error_msg:
                return False, "رقم الهوية مستخدم مسبقاً."

            return False, "حدث تعارض تكاملي أثناء تحديث بيانات العميل/المريض."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def delete_customer(self, requester_id, customer_id):
        """
        الحذف الإداري الآمن للعميل/المريض.
        [Deep RBAC]: Admin only.
        [Data Integrity]: يمنع الحذف إذا وُجد تاريخ مالي أو سريري أو رقابي.
        """
        if not requester_id or not customer_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            requester_row = self._ensure_requester_active(cursor, requester_id)
            requester_role = requester_row[1]

            if requester_role != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized attempt to delete customer ID: {customer_id}")
                conn.commit()
                raise ValueError("صلاحيات غير كافية. الحذف الإداري للعميل/المريض يتطلب صلاحية admin.")

            cursor.execute("""
                SELECT name, phone, email, national_id
                FROM customers
                WHERE id = ?
            """, (customer_id,))
            cust_data = cursor.fetchone()

            if not cust_data:
                raise ValueError("العميل/المريض غير موجود.")

            cust_name, cust_phone, cust_email, cust_nid = cust_data

            # حماية مالية وسريرية
            cursor.execute("SELECT COUNT(id) FROM sales WHERE customer_id = ?", (customer_id,))
            sales_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM prescriptions WHERE customer_id = ?", (customer_id,))
            prescriptions_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM controlled_dispensing_log WHERE customer_id = ?", (customer_id,))
            ctrl_disp_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM controlled_return_log WHERE customer_id = ?", (customer_id,))
            ctrl_return_count = cursor.fetchone()[0]

            if sales_count > 0 or prescriptions_count > 0 or ctrl_disp_count > 0 or ctrl_return_count > 0:
                raise ValueError(
                    f"رفض أمني: لا يمكن حذف العميل/المريض ({cust_name}) لوجود سجل مالي أو سريري أو رقابي مرتبط به."
                )

            audit_payload = json.dumps({
                "deleted_customer": cust_name,
                "phone": cust_phone,
                "email": cust_email,
                "national_id": cust_nid,
                "reason": "Hard Delete (No Financial/Clinical/Controlled History)"
            }, ensure_ascii=False)

            cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values)
                VALUES (?, 'DELETE', 'customers', ?, ?)
            """, (requester_id, customer_id, audit_payload))

            conn.commit()
            return True, f"تم حذف العميل/المريض ({cust_name}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()