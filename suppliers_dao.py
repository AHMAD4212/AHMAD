"""
وظيفة الملف: كائن الوصول لبيانات الموردين (Suppliers DAO).
الطبقة: Data Access Layer / Business Logic

ملاحظة معمارية ومحاسبية:
- [Deep RBAC]&#58; العمليات الإدارية (إضافة، تعديل، تعطيل، حذف) محصورة بمدير النظام (admin).
- [Financial Integrity]&#58; يمنع قطعياً حذف أي مورد له رصيد مالي، أو فواتير شراء سابقة،
  أو أوامر شراء سابقة، أو أدوية مرتبطة به.
- [Identity Integrity - V25]&#58;   1) الهاتف لم يعد مفتاح تفرد.
  2) التفرد المنطقي للمورد النشط يعتمد على (name + company_name).
  3) البريد الإلكتروني -إن وجد- يجب أن يكون فريداً بين الموردين النشطين.
- [Soft Lifecycle Support]&#58; دعم التعطيل المنطقي للموردين عبر is_active دون كسر التاريخ المحاسبي.
- [Audit Trails]&#58; تسجيل كافة التعديلات الأمنية ومحاولات التجاوز.
- [Backward Compatibility]&#58; الإرجاع الافتراضي للدوال العامة ما يزال متوافقاً مع الواجهات القديمة
  عبر أول خمسة أعمدة الأساسية، مع دعم موسّع عند الطلب.
"""

from database.db_manager import DatabaseManager
import json
import sqlite3
import logging

logger = logging.getLogger(__name__)


class SuppliersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # Helpers داخلية
    # ==========================================
    def _json_dump(self, payload):
        return json.dumps(payload, ensure_ascii=False)

    def _log_breach(self, cursor, user_id, action_desc):
        """توثيق محاولة التجاوز الأمني."""
        breach_payload = self._json_dump({"SECURITY_BREACH": action_desc})
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, old_values)
            VALUES (?, 'UPDATE', 'suppliers', ?)
        """, (user_id, breach_payload))

    def _normalize_text(self, value):
        if value is None:
            return None
        value = str(value).strip()
        return value if value else None

    def _normalize_email(self, value):
        value = self._normalize_text(value)
        return value.lower() if value else None

    def _normalize_phone(self, value):
        return self._normalize_text(value)

    def _normalize_supplier_payload(self, name, phone=None, company=None, email=None, address=None, notes=None):
        clean_name = self._normalize_text(name)
        clean_phone = self._normalize_phone(phone)
        clean_company = self._normalize_text(company)
        clean_email = self._normalize_email(email)
        clean_address = self._normalize_text(address)
        clean_notes = self._normalize_text(notes)

        return {
            "name": clean_name,
            "phone": clean_phone,
            "company_name": clean_company,
            "email": clean_email,
            "address": clean_address,
            "notes": clean_notes
        }

    def _validate_supplier_payload(self, payload):
        if not payload["name"]:
            return False, "اسم المورد/المندوب حقل إلزامي."

        if payload["email"] and "@" not in payload["email"]:
            return False, "البريد الإلكتروني غير صالح."

        return True, None

    def _check_admin_access(self, cursor, requester_id, action_desc_for_breach=None):
        cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
        req_user = cursor.fetchone()

        if not req_user or req_user[0] != 'admin':
            if action_desc_for_breach:
                self._log_breach(cursor, requester_id, action_desc_for_breach)
            raise Exception("صلاحيات غير كافية. إدارة الموردين تتطلب صلاحية 'مدير النظام'.")

    def _fetch_supplier_row(self, cursor, supplier_id):
        cursor.execute("""
            SELECT
                id, name, phone, company_name, balance,
                email, address, notes, is_active, created_at, updated_at
            FROM suppliers
            WHERE id = ?
        """, (supplier_id,))
        return cursor.fetchone()

    def _identity_conflict_exists(self, cursor, name, company_name, exclude_supplier_id=None):
        """
        التحقق من وجود مورد نشط آخر يملك نفس الهوية المنطقية:
        (name + company_name)
        """
        normalized_name = (name or "").strip().lower()
        normalized_company = (company_name or "").strip().lower()

        query = """
            SELECT id, name, company_name
            FROM suppliers
            WHERE is_active = 1
              AND LOWER(TRIM(name)) = ?
              AND LOWER(TRIM(COALESCE(company_name, ''))) = ?
        """
        params = [normalized_name, normalized_company]

        if exclude_supplier_id is not None:
            query += " AND id <> ?"
            params.append(exclude_supplier_id)

        cursor.execute(query, tuple(params))
        return cursor.fetchone()

    def _email_conflict_exists(self, cursor, email, exclude_supplier_id=None):
        """
        التحقق من تفرد الإيميل بين الموردين النشطين فقط.
        """
        if not email:
            return None

        query = """
            SELECT id, name, company_name
            FROM suppliers
            WHERE is_active = 1
              AND email IS NOT NULL
              AND LOWER(TRIM(email)) = ?
        """
        params = [email.strip().lower()]

        if exclude_supplier_id is not None:
            query += " AND id <> ?"
            params.append(exclude_supplier_id)

        cursor.execute(query, tuple(params))
        return cursor.fetchone()

    def _assert_no_duplicate_supplier(self, cursor, payload, exclude_supplier_id=None):
        identity_conflict = self._identity_conflict_exists(
            cursor,
            payload["name"],
            payload["company_name"],
            exclude_supplier_id=exclude_supplier_id
        )
        if identity_conflict:
            conflict_name = identity_conflict[1] or "غير معروف"
            conflict_company = identity_conflict[2] or "بدون شركة"
            raise Exception(
                f"رفض منطقي: يوجد مورد نشط مسجل مسبقاً بنفس الهوية "
                f"(الاسم: {conflict_name} / الشركة: {conflict_company})."
            )

        email_conflict = self._email_conflict_exists(
            cursor,
            payload["email"],
            exclude_supplier_id=exclude_supplier_id
        )
        if email_conflict:
            raise Exception("رفض منطقي: البريد الإلكتروني مسجل مسبقاً لمورد نشط آخر.")

    def _handle_integrity_error(self, err):
        msg = str(err).lower()

        if "uq_suppliers_identity_active" in msg:
            return "رفض منطقي: يوجد مورد نشط آخر بنفس الاسم والشركة."
        if "uq_suppliers_email_active" in msg:
            return "رفض منطقي: البريد الإلكتروني مسجل مسبقاً لمورد نشط آخر."
        if "unique constraint failed" in msg:
            return "تم رفض العملية بسبب تعارض تفرد في بيانات المورد."
        return str(err)

    def _build_select_query(self, include_extended=False, active_only=True):
        if include_extended:
            select_part = """
                SELECT
                    id, name, phone, company_name, balance,
                    email, address, notes, is_active, created_at, updated_at
                FROM suppliers
            """
        else:
            # الحفاظ على التوافق مع الواجهات القديمة:
            # id, name, phone, company_name, balance
            select_part = """
                SELECT
                    id, name, phone, company_name, balance
                FROM suppliers
            """

        where_parts = []
        if active_only:
            where_parts.append("is_active = 1")

        query = select_part
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)

        query += " ORDER BY name ASC, company_name ASC, id ASC"
        return query

    # ==========================================
    # القراءة والاستعلام
    # ==========================================
    def get_all_suppliers(self, active_only=True, include_extended=False):
        """
        جلب الموردين.
        افتراضياً:
        - active_only=True
        - include_extended=False للحفاظ على التوافق مع الواجهات القديمة.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute(self._build_select_query(include_extended=include_extended, active_only=active_only))
            return cursor.fetchall()
        except Exception as e:
            logger.exception(f"Error fetching suppliers: {e}")
            return []
        finally:
            conn.close()

    def search_supplier(self, text, active_only=True, include_extended=False):
        """
        البحث عن مورد بالاسم أو الشركة أو الهاتف أو الإيميل.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            search_term = f"%{str(text).strip()}%"

            if include_extended:
                select_part = """
                    SELECT
                        id, name, phone, company_name, balance,
                        email, address, notes, is_active, created_at, updated_at
                    FROM suppliers
                """
            else:
                select_part = """
                    SELECT
                        id, name, phone, company_name, balance
                    FROM suppliers
                """

            where_clause = """
                WHERE (
                    name LIKE ?
                    OR COALESCE(company_name, '') LIKE ?
                    OR COALESCE(phone, '') LIKE ?
                    OR COALESCE(email, '') LIKE ?
                )
            """
            params = [search_term, search_term, search_term, search_term]

            if active_only:
                where_clause += " AND is_active = 1"

            query = select_part + where_clause + " ORDER BY name ASC, company_name ASC, id ASC"
            cursor.execute(query, tuple(params))
            return cursor.fetchall()

        except Exception as e:
            logger.exception(f"Error searching suppliers: {e}")
            return []
        finally:
            conn.close()

    def get_supplier_by_id(self, supplier_id, include_inactive=True):
        """
        جلب مورد واحد بكل حقوله.
        """
        conn = self.db.connect()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            query = """
                SELECT
                    id, name, phone, company_name, balance,
                    email, address, notes, is_active, created_at, updated_at
                FROM suppliers
                WHERE id = ?
            """
            params = [supplier_id]

            if not include_inactive:
                query += " AND is_active = 1"

            cursor.execute(query, tuple(params))
            return cursor.fetchone()
        except Exception as e:
            logger.exception(f"Error fetching supplier by ID: {e}")
            return None
        finally:
            conn.close()

    # ==========================================
    # الإضافة
    # ==========================================
    def add_supplier(self, requester_id, name, phone=None, company=None, email=None, address=None, notes=None):
        """
        إضافة مورد جديد.
        [Deep RBAC]: Admin only.
        [V25]: دعم الحقول الجديدة ومنع التكرار المنطقي.
        ملاحظة: الرصيد الافتتاحي يجب أن يكون 0.0 برمجياً لحماية التسوية المحاسبية.
        """
        if not requester_id:
            return False, "المستخدم غير محدد."

        payload = self._normalize_supplier_payload(
            name=name,
            phone=phone,
            company=company,
            email=email,
            address=address,
            notes=notes
        )

        is_valid, validation_msg = self._validate_supplier_payload(payload)
        if not is_valid:
            return False, validation_msg

        conn = self.db.connect()
        if not conn:
            return False, "تعذر الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            self._check_admin_access(
                cursor,
                requester_id,
                action_desc_for_breach=f"Unauthorized attempt to add supplier: {payload['name']}"
            )

            self._assert_no_duplicate_supplier(cursor, payload)

            cursor.execute("""
                INSERT INTO suppliers (
                    name, phone, company_name, email, address, notes,
                    balance, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, 0.0, 1)
            """, (
                payload["name"],
                payload["phone"],
                payload["company_name"],
                payload["email"],
                payload["address"],
                payload["notes"]
            ))

            supplier_id = cursor.lastrowid

            audit_payload = self._json_dump({
                "name": payload["name"],
                "phone": payload["phone"],
                "company_name": payload["company_name"],
                "email": payload["email"],
                "address": payload["address"],
                "notes": payload["notes"],
                "balance": 0.0,
                "is_active": 1
            })

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'suppliers', ?, ?)
            """, (requester_id, supplier_id, audit_payload))

            conn.commit()
            return True, "تمت إضافة المورد بنجاح."

        except sqlite3.IntegrityError as e:
            conn.rollback()
            return False, self._handle_integrity_error(e)
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ==========================================
    # التعديل
    # ==========================================
    def update_supplier(self, requester_id, supplier_id, name, phone=None, company=None, email=None, address=None, notes=None):
        """
        تعديل البيانات الأساسية للمورد.
        [Deep RBAC]: Admin only.
        [V25]: لا يتم تعديل الرصيد من هنا، الرصيد يتعدل عبر المشتريات والتسويات فقط.
        """
        if not requester_id or not supplier_id:
            return False, "بيانات غير مكتملة."

        payload = self._normalize_supplier_payload(
            name=name,
            phone=phone,
            company=company,
            email=email,
            address=address,
            notes=notes
        )

        is_valid, validation_msg = self._validate_supplier_payload(payload)
        if not is_valid:
            return False, validation_msg

        conn = self.db.connect()
        if not conn:
            return False, "تعذر الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            self._check_admin_access(
                cursor,
                requester_id,
                action_desc_for_breach=f"Unauthorized attempt to update supplier ID: {supplier_id}"
            )

            old_row = self._fetch_supplier_row(cursor, supplier_id)
            if not old_row:
                raise Exception("المورد غير موجود.")

            old_payload = self._json_dump({
                "name": old_row[1],
                "phone": old_row[2],
                "company_name": old_row[3],
                "balance": old_row[4],
                "email": old_row[5],
                "address": old_row[6],
                "notes": old_row[7],
                "is_active": old_row[8]
            })

            self._assert_no_duplicate_supplier(cursor, payload, exclude_supplier_id=supplier_id)

            cursor.execute("""
                UPDATE suppliers
                SET
                    name = ?,
                    phone = ?,
                    company_name = ?,
                    email = ?,
                    address = ?,
                    notes = ?
                WHERE id = ?
            """, (
                payload["name"],
                payload["phone"],
                payload["company_name"],
                payload["email"],
                payload["address"],
                payload["notes"],
                supplier_id
            ))

            if cursor.rowcount == 0:
                raise Exception("تعذر تحديث المورد المطلوب.")

            new_payload = self._json_dump({
                "name": payload["name"],
                "phone": payload["phone"],
                "company_name": payload["company_name"],
                "email": payload["email"],
                "address": payload["address"],
                "notes": payload["notes"]
            })

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'suppliers', ?, ?, ?)
            """, (requester_id, supplier_id, old_payload, new_payload))

            conn.commit()
            return True, "تم تحديث بيانات المورد بنجاح."

        except sqlite3.IntegrityError as e:
            conn.rollback()
            return False, self._handle_integrity_error(e)
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ==========================================
    # التعطيل المنطقي
    # ==========================================
    def archive_supplier(self, requester_id, supplier_id, reason=""):
        """
        تعطيل منطقي للمورد دون حذفه.
        هذا المسار آمن ويفضل استخدامه عندما يكون المورد لم يعد مستخدماً
        لكن توجد رغبة بالحفاظ على السجل التاريخي.
        """
        if not requester_id or not supplier_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            self._check_admin_access(
                cursor,
                requester_id,
                action_desc_for_breach=f"Unauthorized attempt to archive supplier ID: {supplier_id}"
            )

            row = self._fetch_supplier_row(cursor, supplier_id)
            if not row:
                raise Exception("المورد غير موجود.")

            if int(row[8] or 0) == 0:
                return True, "المورد معطل مسبقاً."

            old_payload = self._json_dump({
                "name": row[1],
                "company_name": row[3],
                "is_active": row[8]
            })

            cursor.execute("""
                UPDATE suppliers
                SET is_active = 0
                WHERE id = ?
            """, (supplier_id,))

            new_payload = self._json_dump({
                "name": row[1],
                "company_name": row[3],
                "is_active": 0,
                "reason": reason or "Manual archive"
            })

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'suppliers', ?, ?, ?)
            """, (requester_id, supplier_id, old_payload, new_payload))

            conn.commit()
            return True, f"تم تعطيل المورد ({row[1]}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ==========================================
    # الحذف الإداري النهائي
    # ==========================================
    def delete_supplier(self, requester_id, supplier_id):
        """
        الحذف الإداري الآمن للمورد.
        [Deep RBAC]: Admin only.
        [Financial Lock]: يمنع الحذف إذا كان هناك:
        - رصيد مالي
        - فواتير مشتريات
        - أوامر شراء
        - أدوية مرتبطة
        """
        if not requester_id or not supplier_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            self._check_admin_access(
                cursor,
                requester_id,
                action_desc_for_breach=f"Unauthorized attempt to delete supplier ID: {supplier_id}"
            )

            sup_data = self._fetch_supplier_row(cursor, supplier_id)
            if not sup_data:
                raise Exception("المورد غير موجود.")

            sup_name = sup_data[1]
            balance = float(sup_data[4] or 0.0)

            if abs(balance) > 0.001:
                raise Exception(
                    f"رفض محاسبي: المورد ({sup_name}) له رصيد مالي قائم ({balance:.2f}). يجب تصفية الحساب أولاً."
                )

            cursor.execute("SELECT COUNT(id) FROM purchase_invoices WHERE supplier_id = ?", (supplier_id,))
            invoices_count = cursor.fetchone()[0]
            if invoices_count > 0:
                raise Exception("رفض أمني: لا يمكن حذف المورد لوجود فواتير مشتريات تاريخية مسجلة باسمه.")

            cursor.execute("SELECT COUNT(id) FROM purchase_orders WHERE supplier_id = ?", (supplier_id,))
            orders_count = cursor.fetchone()[0]
            if orders_count > 0:
                raise Exception("رفض أمني: لا يمكن حذف المورد لوجود أوامر شراء تاريخية مرتبطة به.")

            cursor.execute("SELECT COUNT(id) FROM medicines WHERE supplier_id = ?", (supplier_id,))
            medicines_count = cursor.fetchone()[0]
            if medicines_count > 0:
                raise Exception("رفض أمني: لا يمكن حذف المورد لارتباطه كـ 'مورد افتراضي' لبعض الأدوية في المخزون.")

            cursor.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            if cursor.rowcount == 0:
                raise Exception("تعذر حذف المورد المطلوب.")

            audit_payload = self._json_dump({
                "deleted_supplier": sup_name,
                "reason": "Hard Delete (No Financial/Purchase/Inventory History)"
            })

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values)
                VALUES (?, 'DELETE', 'suppliers', ?, ?)
            """, (requester_id, supplier_id, audit_payload))

            conn.commit()
            return True, f"تم حذف المورد ({sup_name}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()