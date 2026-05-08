"""
وظيفة الملف: كائن الوصول لبيانات الوصفات الطبية (Prescriptions DAO).
الطبقة: Data Access Layer / Business Logic

ملاحظة معمارية وأمنية:
- [Strict RBAC]&#58; الإضافة والإلغاء محصورة بـ (Admin, Pharmacist) مع تحقق صريح من قاعدة البيانات.
- [Atomic Reconciliation]&#58; محرك تسوية ذري يعتمد على تمرير الـ Cursor لضمان تطابق المبيعات والمرتجعات مع الوصفة.
- [V10 Patch]&#58; استقبال وحفظ (days_supply) لعمل محرك التنبيهات للأدوية المزمنة.
- [V11 Patch - Controlled Drugs]&#58; حراسة الوصفة بقواعد صارمة تمنع خلط الأدوية الرقابية مع الوصفات العادية والعكس.
- [V24 Compatibility]&#58; التحقق من أن المريض موجود ونشط (is_active = 1) بما يتوافق مع البنية الجديدة لجدول customers.
- [POS Contract Fix]&#58; إرجاع customer_id و doctor_id عند استدعاء الوصفة من صفحة المبيعات.
- [Manual RX Number Support]&#58; دعم تمرير رقم وصفة يدوي من الواجهة مع التحقق من التفرد.
"""

from database.db_manager import DatabaseManager
from datetime import datetime
import sqlite3
import json
import logging

logger = logging.getLogger(__name__)


class PrescriptionsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # Helpers
    # ==========================================
    def _sanitize_text(self, value):
        if value is None:
            return ""
        return " ".join(str(value).strip().split())

    def _generate_rx_number(self, cursor, issue_date_str):
        date_clean = issue_date_str.replace("-", "")
        prefix = f"RX-{date_clean}-"
        cursor.execute("""
            SELECT prescription_number
            FROM prescriptions
            WHERE prescription_number LIKE ?
            ORDER BY prescription_number DESC
            LIMIT 1
        """, (f"{prefix}%",))
        last_rx = cursor.fetchone()
        new_seq = (int(last_rx[0].split("-")[-1]) + 1) if last_rx else 1
        return f"{prefix}{new_seq:03d}"

    def _log_audit(self, cursor, user_id, action, table_name, record_id, old_val, new_val):
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            action,
            table_name,
            record_id,
            json.dumps(old_val, ensure_ascii=False),
            json.dumps(new_val, ensure_ascii=False)
        ))

    def _check_rbac(self, cursor, user_id, allowed_roles=None):
        if allowed_roles is None:
            allowed_roles = ['admin', 'pharmacist']

        cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user or user[1] == 0:
            raise Exception("المستخدم غير موجود أو حسابه معطل.")

        if user[0] not in allowed_roles:
            raise Exception(f"صلاحيات غير كافية. هذه العملية تتطلب دور: {', '.join(allowed_roles)}")

        return True

    def _validate_date_order(self, issue_date, expiry_date):
        try:
            issue_obj = datetime.strptime(issue_date, "%Y-%m-%d").date()
            expiry_obj = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        except ValueError:
            raise Exception("صيغة التاريخ غير صحيحة. الصيغة المعتمدة هي YYYY-MM-DD.")

        if issue_obj > expiry_obj:
            raise Exception("تاريخ الانتهاء يجب أن يكون بعد تاريخ الإصدار أو يساويه.")

    def _update_prescription_status(self, cursor, prescription_id):
        """
        تحديث حالة الوصفة بناءً على إجمالي المصروف من بنودها.
        لا يعبث بحالات الإلغاء أو الانتهاء.
        """
        cursor.execute("SELECT status FROM prescriptions WHERE id = ?", (prescription_id,))
        rx_row = cursor.fetchone()
        if not rx_row:
            return

        current_status = rx_row[0]
        if current_status in ('cancelled', 'expired'):
            return

        cursor.execute("""
            SELECT prescribed_qty, dispensed_qty
            FROM prescription_items
            WHERE prescription_id = ?
        """, (prescription_id,))
        items = cursor.fetchall()

        if not items:
            return

        total_prescribed = sum(i[0] for i in items)
        total_dispensed = sum(i[1] for i in items)

        if total_dispensed <= 0:
            new_status = 'active'
        elif total_dispensed >= total_prescribed:
            new_status = 'fully_dispensed'
        else:
            new_status = 'partially_dispensed'

        cursor.execute("""
            UPDATE prescriptions
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, prescription_id))

    # ==========================================
    # Create / Save
    # ==========================================
    def add_prescription(
        self,
        requester_id,
        customer_id,
        doctor_id,
        p_type,
        issue_date,
        expiry_date,
        notes,
        items,
        prescription_number=None
    ):
        if not requester_id:
            return False, "تعذر تحديد المستخدم الحالي."

        if not customer_id:
            return False, "يجب تحديد المريض."

        if not doctor_id:
            return False, "يجب تحديد الطبيب."

        if not items:
            return False, "لا يمكن حفظ وصفة فارغة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # 1) الحراسة الأمنية
            self._check_rbac(cursor, requester_id, allowed_roles=['admin', 'pharmacist'])

            # 2) الحراسة الزمنية
            self._validate_date_order(issue_date, expiry_date)

            # 3) حراسة نوع الوصفة
            allowed_types = {'regular', 'chronic', 'controlled', 'insurance'}
            if p_type not in allowed_types:
                raise Exception("نوع الوصفة غير صالح.")

            # 4) التحقق من المريض
            cursor.execute("""
                SELECT id, is_active
                FROM customers
                WHERE id = ?
            """, (customer_id,))
            customer_row = cursor.fetchone()
            if not customer_row:
                raise Exception("المريض غير موجود.")
            if int(customer_row[1]) != 1:
                raise Exception("المريض المحدد غير نشط ولا يمكن إنشاء وصفة باسمه.")

            # 5) التحقق من الطبيب
            cursor.execute("""
                SELECT id
                FROM doctors
                WHERE id = ? AND is_active = 1
            """, (doctor_id,))
            if not cursor.fetchone():
                raise Exception("الطبيب غير موجود أو معطل.")

            # 6) التحقق من البنود
            med_ids = []
            normalized_items = []

            for item in items:
                med_id = item.get('medicine_id')

                try:
                    prescribed_qty = int(item.get('prescribed_qty', 0))
                except (ValueError, TypeError):
                    raise Exception(f"الكمية الموصوفة غير صالحة للدواء رقم {med_id}.")

                try:
                    days_supply = int(item.get('days_supply', 0))
                except (ValueError, TypeError):
                    raise Exception(f"قيمة أيام التغطية غير صالحة للدواء رقم {med_id}.")

                if not med_id:
                    raise Exception("يوجد بند داخل الوصفة بدون medicine_id.")
                if prescribed_qty <= 0:
                    raise Exception(f"الكمية الموصوفة يجب أن تكون أكبر من صفر للدواء رقم {med_id}.")
                if days_supply <= 0:
                    raise Exception(f"أيام التغطية يجب أن تكون أكبر من صفر للدواء رقم {med_id}.")

                med_ids.append(med_id)
                normalized_items.append({
                    "medicine_id": med_id,
                    "prescribed_qty": prescribed_qty,
                    "days_supply": days_supply,
                    "dosage": self._sanitize_text(item.get('dosage', '')),
                    "notes": self._sanitize_text(item.get('notes', ''))
                })

            if len(med_ids) != len(set(med_ids)):
                raise Exception("يوجد دواء مكرر داخل نفس الوصفة. يجب أن يظهر كل دواء مرة واحدة فقط.")

            # 7) التحقق من وجود الأدوية وتصنيفها الرقابي
            placeholders = ",".join(["?"] * len(med_ids))
            cursor.execute(f"""
                SELECT id, name, is_controlled
                FROM medicines
                WHERE id IN ({placeholders})
            """, tuple(med_ids))
            med_rows = cursor.fetchall()

            if len(med_rows) != len(set(med_ids)):
                found_ids = {row[0] for row in med_rows}
                missing = [str(mid) for mid in set(med_ids) if mid not in found_ids]
                raise Exception(f"بعض الأدوية غير موجودة في قاعدة البيانات: {', '.join(missing)}")

            med_ctrl_map = {row[0]: int(row[2]) for row in med_rows}
            has_controlled_drug = any(med_ctrl_map.get(m_id, 0) == 1 for m_id in med_ids)

            if has_controlled_drug and p_type != 'controlled':
                raise Exception("تحتوي الوصفة على دواء رقابي/مخدر. يمنع حفظها إلا إذا كان نوع الوصفة (controlled).")

            if p_type == 'controlled' and not has_controlled_drug:
                raise Exception("نوع الوصفة محدد كـ (controlled)، لكن قائمة الأدوية لا تحتوي على أي دواء رقابي.")

            # 8) تحديد رقم الوصفة
            clean_rx_number = self._sanitize_text(prescription_number)
            if clean_rx_number:
                cursor.execute("""
                    SELECT id
                    FROM prescriptions
                    WHERE prescription_number = ?
                """, (clean_rx_number,))
                if cursor.fetchone():
                    raise Exception("رقم الوصفة المدخل مستخدم مسبقاً. يرجى إدخال رقم مختلف.")
                final_rx_number = clean_rx_number
                rx_number_source = "manual"
            else:
                final_rx_number = self._generate_rx_number(cursor, issue_date)
                rx_number_source = "auto"

            clean_notes = self._sanitize_text(notes)

            # 9) إدراج رأس الوصفة
            cursor.execute("""
                INSERT INTO prescriptions
                (
                    prescription_number,
                    customer_id,
                    doctor_id,
                    prescription_type,
                    status,
                    issue_date,
                    expiry_date,
                    notes,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """, (
                final_rx_number,
                customer_id,
                doctor_id,
                p_type,
                issue_date,
                expiry_date,
                clean_notes,
                requester_id
            ))

            rx_id = cursor.lastrowid

            # 10) إدراج البنود
            for item in normalized_items:
                cursor.execute("""
                    INSERT INTO prescription_items
                    (
                        prescription_id,
                        medicine_id,
                        prescribed_qty,
                        dispensed_qty,
                        days_supply,
                        dosage_instructions,
                        notes
                    )
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                """, (
                    rx_id,
                    item["medicine_id"],
                    item["prescribed_qty"],
                    item["days_supply"],
                    item["dosage"],
                    item["notes"]
                ))

            # 11) التوثيق
            self._log_audit(
                cursor,
                requester_id,
                'INSERT',
                'prescriptions',
                rx_id,
                {},
                {
                    "prescription_number": final_rx_number,
                    "prescription_number_source": rx_number_source,
                    "customer_id": customer_id,
                    "doctor_id": doctor_id,
                    "prescription_type": p_type,
                    "items_count": len(normalized_items)
                }
            )

            conn.commit()
            return True, f"تم تسجيل الوصفة بنجاح: {final_rx_number}"

        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()

            if "prescription_number" in error_msg:
                return False, "رقم الوصفة مستخدم مسبقاً."
            if "unique" in error_msg and "prescription_id" in error_msg:
                return False, "لا يمكن تكرار نفس الدواء داخل الوصفة الواحدة."
            return False, "حدث خطأ في تكامل البيانات أثناء حفظ الوصفة."

        except Exception as e:
            conn.rollback()
            return False, str(e)

        finally:
            conn.close()

    # ==========================================
    # Read / POS Integration
    # ==========================================
    def get_prescription_for_pos(self, rx_number):
        clean_rx_number = self._sanitize_text(rx_number)
        if not clean_rx_number:
            return False, "رقم الوصفة غير صالح."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")

            cursor.execute("""
                SELECT
                    p.id,
                    p.prescription_number,
                    p.customer_id,
                    c.name,
                    p.doctor_id,
                    d.name,
                    p.status,
                    p.expiry_date,
                    p.prescription_type
                FROM prescriptions p
                JOIN customers c ON p.customer_id = c.id
                JOIN doctors d ON p.doctor_id = d.id
                WHERE p.prescription_number = ?
            """, (clean_rx_number,))

            rx = cursor.fetchone()
            if not rx:
                return False, "رقم الوصفة غير صحيح."

            rx_id = rx[0]
            rx_number_db = rx[1]
            customer_id = rx[2]
            customer_name = rx[3]
            doctor_id = rx[4]
            doctor_name = rx[5]
            status = rx[6]
            expiry = rx[7]
            rx_type = rx[8]

            if expiry < today_str:
                cursor.execute("""
                    UPDATE prescriptions
                    SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (rx_id,))
                conn.commit()
                return False, "الوصفة منتهية الصلاحية."

            if status in ('fully_dispensed', 'cancelled', 'expired'):
                return False, f"لا يمكن الصرف من هذه الوصفة. حالتها الحالية: {status}"

            cursor.execute("""
                SELECT
                    pi.id,
                    pi.medicine_id,
                    m.name,
                    pi.prescribed_qty,
                    pi.dispensed_qty,
                    (pi.prescribed_qty - pi.dispensed_qty) AS remaining_qty,
                    pi.dosage_instructions,
                    pi.days_supply,
                    m.is_controlled
                FROM prescription_items pi
                JOIN medicines m ON pi.medicine_id = m.id
                WHERE pi.prescription_id = ?
                  AND (pi.prescribed_qty - pi.dispensed_qty) > 0
            """, (rx_id,))

            items = []
            for row in cursor.fetchall():
                items.append({
                    "prescription_item_id": row[0],
                    "medicine_id": row[1],
                    "medicine_name": row[2],
                    "prescribed_qty": row[3],
                    "dispensed_qty": row[4],
                    "remaining_qty": row[5],
                    "dosage": row[6],
                    "days_supply": row[7],
                    "is_controlled": row[8]
                })

            if not items:
                cursor.execute("""
                    UPDATE prescriptions
                    SET status = 'fully_dispensed', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (rx_id,))
                conn.commit()
                return False, "تم صرف جميع أصناف هذه الوصفة."

            return True, {
                "prescription_id": rx_id,
                "prescription_number": rx_number_db,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "prescription_type": rx_type,
                "items": items
            }

        finally:
            conn.close()

    def get_all_prescriptions(self, status_filter='all'):
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")

            # تحديث استباقي للحالات المنتهية
            cursor.execute("""
                UPDATE prescriptions
                SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('active', 'partially_dispensed')
                  AND expiry_date < ?
            """, (today_str,))

            base_query = """
                SELECT
                    p.id,
                    p.prescription_number,
                    c.name,
                    d.name,
                    p.status,
                    p.issue_date,
                    p.expiry_date
                FROM prescriptions p
                JOIN customers c ON p.customer_id = c.id
                JOIN doctors d ON p.doctor_id = d.id
            """

            if status_filter != 'all':
                cursor.execute(base_query + " WHERE p.status = ? ORDER BY p.id DESC", (status_filter,))
            else:
                cursor.execute(base_query + " ORDER BY p.id DESC")

            return cursor.fetchall()

        finally:
            conn.close()

    # ==========================================
    # Cancel
    # ==========================================
    def cancel_prescription(self, requester_id, prescription_id, reason):
        if not requester_id:
            return False, "تعذر تحديد المستخدم الحالي."

        clean_reason = self._sanitize_text(reason)
        if not clean_reason:
            return False, "سبب الإلغاء إلزامي."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_rbac(cursor, requester_id, allowed_roles=['admin', 'pharmacist'])

            cursor.execute("""
                SELECT status, prescription_number
                FROM prescriptions
                WHERE id = ?
            """, (prescription_id,))
            rx = cursor.fetchone()

            if not rx:
                raise Exception("الوصفة غير موجودة.")

            old_status = rx[0]
            rx_number = rx[1]

            if old_status in ('partially_dispensed', 'fully_dispensed'):
                raise Exception("لا يمكن إلغاء وصفة تم البدء بصرفها أو اكتملت.")
            if old_status == 'cancelled':
                raise Exception("هذه الوصفة ملغاة مسبقاً.")
            if old_status == 'expired':
                raise Exception("لا يمكن إلغاء وصفة منتهية الصلاحية. حالتها بالفعل expired.")

            cursor.execute("""
                UPDATE prescriptions
                SET status = 'cancelled',
                    updated_by_user_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (requester_id, prescription_id))

            self._log_audit(
                cursor,
                requester_id,
                'UPDATE',
                'prescriptions',
                prescription_id,
                {"status": old_status, "prescription_number": rx_number},
                {"status": "cancelled", "reason": clean_reason}
            )

            conn.commit()
            return True, "تم إلغاء الوصفة بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)

        finally:
            conn.close()

    # ==========================================
    # Atomic Reconciliation
    # ==========================================
    def reconcile_sale(self, cursor, sale_id):
        """[Atomic] تحديث كميات الوصفات بعد البيع."""
        cursor.execute("""
            SELECT prescription_item_id, quantity
            FROM sale_items
            WHERE sale_id = ? AND prescription_item_id IS NOT NULL
        """, (sale_id,))
        items = cursor.fetchall()

        affected_prescriptions = set()

        for pi_id, qty in items:
            cursor.execute("""
                UPDATE prescription_items
                SET dispensed_qty = dispensed_qty + ?
                WHERE id = ?
            """, (qty, pi_id))

            cursor.execute("SELECT prescription_id FROM prescription_items WHERE id = ?", (pi_id,))
            row = cursor.fetchone()
            if row:
                affected_prescriptions.add(row[0])

        for rx_id in affected_prescriptions:
            self._update_prescription_status(cursor, rx_id)

    def reconcile_return(self, cursor, return_id):
        """[Atomic] عكس الكميات المصروفة عند إنشاء مرتجع."""
        cursor.execute("""
            SELECT si.prescription_item_id, ri.quantity
            FROM return_items ri
            JOIN sale_items si ON ri.sale_item_id = si.id
            WHERE ri.return_id = ? AND si.prescription_item_id IS NOT NULL
        """, (return_id,))
        items = cursor.fetchall()

        affected_prescriptions = set()

        for pi_id, qty in items:
            cursor.execute("""
                UPDATE prescription_items
                SET dispensed_qty = CASE
                    WHEN dispensed_qty >= ? THEN dispensed_qty - ?
                    ELSE 0
                END
                WHERE id = ?
            """, (qty, qty, pi_id))

            cursor.execute("SELECT prescription_id FROM prescription_items WHERE id = ?", (pi_id,))
            row = cursor.fetchone()
            if row:
                affected_prescriptions.add(row[0])

        for rx_id in affected_prescriptions:
            self._update_prescription_status(cursor, rx_id)

    def reconcile_return_reversal(self, cursor, return_id):
        """[Atomic] إعادة تسجيل الكميات كمصروفة عند إلغاء المرتجع إدارياً."""
        cursor.execute("""
            SELECT si.prescription_item_id, ri.quantity
            FROM return_items ri
            JOIN sale_items si ON ri.sale_item_id = si.id
            WHERE ri.return_id = ? AND si.prescription_item_id IS NOT NULL
        """, (return_id,))
        items = cursor.fetchall()

        affected_prescriptions = set()

        for pi_id, qty in items:
            cursor.execute("""
                UPDATE prescription_items
                SET dispensed_qty = dispensed_qty + ?
                WHERE id = ?
            """, (qty, pi_id))

            cursor.execute("SELECT prescription_id FROM prescription_items WHERE id = ?", (pi_id,))
            row = cursor.fetchone()
            if row:
                affected_prescriptions.add(row[0])

        for rx_id in affected_prescriptions:
            self._update_prescription_status(cursor, rx_id)