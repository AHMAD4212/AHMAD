"""
وظيفة الملف: كائن الوصول لبيانات تنبيهات إعادة التعبئة (Chronic Refill Alerts DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية وسريرية:
- [Data Integrity]: حساب موعد الاستحقاق يعتمد حصراً على الحقل الهيكلي (days_supply) وتاريخ آخر صرف فعلي مسجل في المبيعات، ولا يعتمد على النصوص الحرة.
- [Clinical Assumption]: يفترض النظام أن (days_supply) يمثل التغطية الفعلية للكمية المصروفة في آخر عملية بيع. إذا تم صرف كمية جزئية لا تكفي لهذه الأيام، يجب أن يُعدّل الصيدلي الـ days_supply وقت الصرف.
- يستهدف فقط الوصفات من نوع (chronic) والتي حالتها (active) أو (partially_dispensed).
"""

from database.db_manager import DatabaseManager
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

class RefillAlertsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _validate_days(self, days):
        """[Guard]: حارس للتحقق من أن نطاق الأيام صالح رياضياً لمنع أخطاء الـ SQL"""
        try:
            d = int(days)
            if d < 0: raise ValueError
            return d
        except (TypeError, ValueError):
            logger.warning(f"Invalid days_ahead value '{days}' passed. Defaulting to 7.")
            return 7

    def get_due_refills(self, days_ahead=7):
        """
        يجلب الأصناف المزمنة التي اقترب موعد نفادها من المريض.
        المعادلة: تاريخ آخر صرف + أيام التغطية (days_supply) <= اليوم + أيام التنبيه المسبق.
        """
        valid_days = self._validate_days(days_ahead)
        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    p.id AS prescription_id,
                    p.prescription_number,
                    c.name AS customer_name,
                    c.phone AS customer_phone,
                    d.name AS doctor_name,
                    m.name AS medicine_name,
                    pi.prescribed_qty,
                    pi.dispensed_qty,
                    pi.days_supply,
                    MAX(s.sale_date) AS last_dispensed_date,
                    date(MAX(s.sale_date), '+' || pi.days_supply || ' days') AS expected_exhaustion_date
                FROM prescription_items pi
                JOIN prescriptions p ON pi.prescription_id = p.id
                JOIN customers c ON p.customer_id = c.id
                JOIN doctors d ON p.doctor_id = d.id
                JOIN medicines m ON pi.medicine_id = m.id
                JOIN sale_items si ON pi.id = si.prescription_item_id
                JOIN sales s ON si.sale_id = s.id
                WHERE p.prescription_type = 'chronic'
                  AND p.status IN ('active', 'partially_dispensed')
                  AND pi.dispensed_qty > 0
                GROUP BY pi.id
                HAVING expected_exhaustion_date <= date('now', '+' || ? || ' days')
                ORDER BY expected_exhaustion_date ASC
            """

            cursor.execute(query, (valid_days,))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except Exception as e:
            logger.exception("Error fetching due refills:")
            return []
        finally:
            conn.close()

    def get_expiring_prescriptions(self, days_ahead=14):
        """
        تنبيه زمني بسيط: يجلب الوصفات المزمنة التي اقترب تاريخ انتهائها الكلي (expiry_date).
        """
        valid_days = self._validate_days(days_ahead)
        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    p.id AS prescription_id,
                    p.prescription_number,
                    c.name AS customer_name,
                    c.phone AS customer_phone,
                    d.name AS doctor_name,
                    p.status,
                    p.issue_date,
                    p.expiry_date
                FROM prescriptions p
                JOIN customers c ON p.customer_id = c.id
                JOIN doctors d ON p.doctor_id = d.id
                WHERE p.prescription_type = 'chronic'
                  AND p.status IN ('active', 'partially_dispensed')
                  AND p.expiry_date <= date('now', '+' || ? || ' days')
                  AND p.expiry_date >= date('now') -- استبعاد المنتهية فعلياً
                ORDER BY p.expiry_date ASC
            """

            cursor.execute(query, (valid_days,))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except Exception as e:
            logger.exception("Error fetching expiring prescriptions:")
            return []
        finally:
            conn.close()

    def get_patient_refill_alerts(self, customer_id, days_ahead=7):
        """
        دالة الحقن التفاعلي (Reactive Alert) لشاشة الـ POS.
        """
        if not customer_id: return []
        valid_days = self._validate_days(days_ahead)

        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    m.name AS medicine_name,
                    date(MAX(s.sale_date), '+' || pi.days_supply || ' days') AS expected_exhaustion_date
                FROM prescription_items pi
                JOIN prescriptions p ON pi.prescription_id = p.id
                JOIN medicines m ON pi.medicine_id = m.id
                JOIN sale_items si ON pi.id = si.prescription_item_id
                JOIN sales s ON si.sale_id = s.id
                WHERE p.customer_id = ?
                  AND p.prescription_type = 'chronic'
                  AND p.status IN ('active', 'partially_dispensed')
                  AND pi.dispensed_qty > 0
                GROUP BY pi.id
                HAVING expected_exhaustion_date <= date('now', '+' || ? || ' days')
                ORDER BY expected_exhaustion_date ASC
            """

            cursor.execute(query, (customer_id, valid_days))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except Exception as e:
            logger.exception("Error fetching patient specific alerts:")
            return []
        finally:
            conn.close()

    def log_reminder_simulation(self, user_id, patient_name, phone, context_msg):
        """
        [Audit Trail & RBAC Guard]: توثيق عملية المحاكاة في سجلات النظام مع التحقق الصارم من الصلاحيات.
        """
        if not user_id: return False
        conn = self.db.connect()
        if not conn: return False

        try:
            cursor = conn.cursor()

            # --- حارس الصلاحيات (RBAC Guard) ---
            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            if not user_row or user_row[1] != 1 or user_row[0] not in ['admin', 'pharmacist']:
                logger.warning(f"Unauthorized attempt to log reminder simulation by user_id: {user_id}")
                return False

            payload = json.dumps({
                "patient": patient_name,
                "phone": phone,
                "message_context": context_msg,
                "status": "simulated_success",
                "channel": "WhatsApp/SMS Placeholder"
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, new_values)
                VALUES (?, 'SIMULATE_REMINDER', 'notifications_queue', ?)
            """, (user_id, payload))

            conn.commit()
            return True
        except Exception as e:
            logger.exception("Error logging reminder simulation:")
            return False
        finally:
            conn.close()