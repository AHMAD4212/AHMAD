"""
وظيفة الملف: كائن الوصول لبيانات الورديات والعهد النقدية وتسوياتها (Shifts DAO).
الطبقة: Data Access Layer / Business Logic
- [Strict Atomicity Guard]: تم تطبيق (BEGIN IMMEDIATE) في عمليات الفتح والإغلاق لقفل قاعدة البيانات ومنع التداخل الزمني (Race Conditions) والفتح المزدوج.
- [Strict Identity Guard]: تحقق متناظر (Role & Active) في فتح وإغلاق الوردية لضمان النزاهة الأمنية.
- [No Silent Failures]: تمييز قطعي بين (عدم وجود وردية) وبين (فشل حرج في الحساب) في دالة get_open_shift.
- [Null-Safe Summaries]: حماية الملخصات والتقارير من قيم None المادية وتوحيدها بـ (ROUND_HALF_UP).
- [SSOT Expected Cash]: الاعتماد الحصري على Transactions لحساب الرصيد النظري (Expected).
- [Temporal Insert Safety]: في الإغلاق، تُدرج القيود (التسويات والتوريد) أولاً، ثم تُغلق الوردية أخيراً لمنع الاصطدام بحراس قاعدة البيانات مستقبلاً.
"""

from database.db_manager import DatabaseManager
from models.expenses_dao import ExpensesDAO
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import logging

logger = logging.getLogger(__name__)

D_0 = Decimal('0.00')
D_2 = Decimal('0.01')
# الأدوار المصرح لها بالتعامل مع الصندوق
AUTHORIZED_ROLES = ['admin', 'pharmacist', 'cashier']

class ShiftsDAO:
    def __init__(self):
        self.db = DatabaseManager()
        self.expenses_dao = ExpensesDAO()

    # ==========================================
    # 1. الاستعلام والتشخيص
    # ==========================================
    def get_open_shift(self, user_id):
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, opening_cash, opened_at, opening_notes
                FROM shifts
                WHERE user_id = ? AND status = 'open'
                LIMIT 1
            """, (user_id,))
            row = cursor.fetchone()

            if not row:
                return None

            shift_id = row[0]
            opening_cash = Decimal(str(row[1]))

            try:
                expected_cash = self.expenses_dao.get_shift_theoretical_balance(cursor, shift_id)
            except Exception as e:
                logger.error(f"Critical calculation error for shift {shift_id}: {e}")
                raise RuntimeError(f"فشل حرج في حساب الرصيد النظري للوردية: {str(e)}")

            return {
                "shift_id": shift_id,
                "opening_cash": float(opening_cash.quantize(D_2, rounding=ROUND_HALF_UP)),
                "expected_cash": float(expected_cash.quantize(D_2, rounding=ROUND_HALF_UP)),
                "opened_at": row[2],
                "opening_notes": row[3]
            }
        except Exception as e:
            if not isinstance(e, RuntimeError):
                logger.error(f"Database error in get_open_shift: {e}")
            raise
        finally:
            conn.close()

    def get_shift_summary(self, shift_id):
        """جلب ملخص شامل للوردية مع حماية ضد قيم None وتوحيد التقريب."""
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, u.username, s.opening_cash, s.expected_cash, s.actual_cash, 
                       s.variance, s.opened_at, s.closed_at, s.status, s.opening_notes, s.closing_notes
                FROM shifts s
                JOIN users u ON s.user_id = u.id
                WHERE s.id = ?
            """, (shift_id,))
            row = cursor.fetchone()
            if not row: return None

            actual_cash_dec = Decimal(str(row[4])) if row[4] is not None else D_0

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM transactions 
                WHERE shift_id = ? AND reference_type = 'cash_drop'
            """, (shift_id,))
            drop_amount_dec = Decimal(str(cursor.fetchone()[0]))

            remaining_after = (actual_cash_dec - drop_amount_dec).quantize(D_2, rounding=ROUND_HALF_UP)

            return {
                "shift_id": row[0],
                "username": row[1],
                "opening_cash": float(Decimal(str(row[2])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "expected_cash": float(Decimal(str(row[3])).quantize(D_2, rounding=ROUND_HALF_UP)) if row[3] is not None else 0.0,
                "actual_cash": float(actual_cash_dec.quantize(D_2, rounding=ROUND_HALF_UP)),
                "variance": float(Decimal(str(row[5])).quantize(D_2, rounding=ROUND_HALF_UP)) if row[5] is not None else 0.0,
                "opened_at": row[6],
                "closed_at": row[7],
                "status": row[8],
                "opening_notes": row[9] or "-",
                "closing_notes": row[10] or "-",
                "cash_drop_amount": float(drop_amount_dec.quantize(D_2, rounding=ROUND_HALF_UP)),
                "remaining_cash_after_drop": float(remaining_after)
            }
        finally:
            conn.close()

    def get_all_shifts(self, status=None, user_id=None, date_from=None, date_to=None):
        """جلب سجل الورديات للإدارة مع توحيد مالي كامل للحقول."""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT s.id, u.username, s.opening_cash, s.expected_cash, s.actual_cash, 
                       s.variance, s.status, s.opened_at, s.closed_at, s.opening_notes, s.closing_notes
                FROM shifts s
                JOIN users u ON s.user_id = u.id
                WHERE 1=1
            """
            params = []
            if status:
                query += " AND s.status = ?"
                params.append(status)
            if user_id:
                query += " AND s.user_id = ?"
                params.append(user_id)
            if date_from and date_to:
                query += " AND DATE(s.opened_at) BETWEEN ? AND ?"
                params.extend([date_from, date_to])

            query += " ORDER BY s.opened_at DESC"
            cursor.execute(query, params)

            shifts = []
            for r in cursor.fetchall():
                shifts.append({
                    "shift_id": r[0],
                    "username": r[1],
                    "opening_cash": float(Decimal(str(r[2])).quantize(D_2, rounding=ROUND_HALF_UP)),
                    "expected_cash": float(Decimal(str(r[3])).quantize(D_2, rounding=ROUND_HALF_UP)) if r[3] is not None else 0.0,
                    "actual_cash": float(Decimal(str(r[4])).quantize(D_2, rounding=ROUND_HALF_UP)) if r[4] is not None else 0.0,
                    "variance": float(Decimal(str(r[5])).quantize(D_2, rounding=ROUND_HALF_UP)) if r[5] is not None else 0.0,
                    "status": r[6],
                    "opened_at": r[7],
                    "closed_at": r[8],
                    "opening_notes": r[9] or "-",
                    "closing_notes": r[10] or "-"
                })
            return shifts
        finally:
            conn.close()

    # ==========================================
    # 2. فتح الوردية
    # ==========================================
    def open_shift(self, user_id, opening_cash, opening_notes=""):
        if not user_id: return False, "المستخدم غير صالح."

        try:
            open_cash_dec = Decimal(str(opening_cash)).quantize(D_2, rounding=ROUND_HALF_UP)
            if open_cash_dec < D_0: raise ValueError
        except (InvalidOperation, ValueError):
            return False, "قيمة العهدة الافتتاحية يجب أن تكون رقماً موجباً أو صفراً."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            # [Strict Atomicity Guard]: قفل قاعدة البيانات للكتابة لمنع الفتح المزدوج المتزامن
            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()

            # [Transaction Hygiene]: استخدام rollback صريح قبل أي خروج مبكر لفك القفل فوراً
            if not u_row or u_row[1] != 1:
                conn.rollback()
                return False, "الحساب غير موجود أو موقوف."

            if u_row[0] not in AUTHORIZED_ROLES:
                conn.rollback()
                return False, "غير مصرح لك بفتح وردية مالية."

            cursor.execute("SELECT id FROM shifts WHERE user_id = ? AND status = 'open'", (user_id,))
            if cursor.fetchone():
                conn.rollback()
                return False, "لديك وردية مفتوحة بالفعل."

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            safe_notes = opening_notes.strip()

            cursor.execute("""
                INSERT INTO shifts (user_id, opening_cash, status, opened_at, opening_notes)
                VALUES (?, ?, 'open', ?, ?)
            """, (user_id, float(open_cash_dec), now_str, safe_notes))

            shift_id = cursor.lastrowid

            audit_payload = json.dumps({
                "opening_cash": float(open_cash_dec),
                "opened_at": now_str,
                "opening_notes": safe_notes
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'shifts', ?, ?)
            """, (user_id, shift_id, audit_payload))

            conn.commit()
            return True, {"shift_id": shift_id, "message": "تم فتح الوردية بنجاح."}

        except Exception as e:
            conn.rollback()
            logger.exception("خطأ داخلي أثناء فتح الوردية:")
            return False, "فشل داخلي في فتح الوردية."
        finally:
            conn.close()

    # ==========================================
    # 3. الإغلاق والتسوية (The Accounting Finish Line)
    # ==========================================
    def close_shift(self, user_id, actual_cash, cash_drop_amount, closing_notes=""):
        if not user_id: return False, "المستخدم غير صالح."

        try:
            actual_dec = Decimal(str(actual_cash)).quantize(D_2, rounding=ROUND_HALF_UP)
            drop_dec = Decimal(str(cash_drop_amount)).quantize(D_2, rounding=ROUND_HALF_UP)
            if actual_dec < D_0 or drop_dec < D_0: raise ValueError("القيم النقدية لا يمكن أن تكون سالبة.")
            if drop_dec > actual_dec: raise ValueError("مبلغ التوريد لا يمكن أن يتجاوز النقد الفعلي.")
        except (InvalidOperation, ValueError) as ve:
            return False, str(ve) if str(ve) else "قيم النقدية المدخلة غير صالحة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            # [Strict Atomicity Guard]: قفل قاعدة البيانات لمنع أي تعديلات متزامنة أثناء الإغلاق
            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()
            if not u_row or u_row[1] != 1: raise ValueError("حساب المستخدم غير صالح أو تم إيقافه.")
            if u_row[0] not in AUTHORIZED_ROLES: raise ValueError("غير مصرح لك بإغلاق وردية مالية.")

            cursor.execute("SELECT id FROM shifts WHERE user_id = ? AND status = 'open'", (user_id,))
            row = cursor.fetchone()
            if not row: raise ValueError("لا توجد وردية مفتوحة لهذا المستخدم.")
            shift_id = row[0]

            expected_dec = self.expenses_dao.get_shift_theoretical_balance(cursor, shift_id)
            variance_dec = actual_dec - expected_dec
            safe_notes = closing_notes.strip()

            if variance_dec != D_0 and not safe_notes:
                raise ValueError("يجب إدخال مبرر للعجز أو الزيادة قبل الإغلاق.")

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rem = (actual_dec - drop_dec).quantize(D_2, rounding=ROUND_HALF_UP)

            # [Temporal Insert Safety]: إدراج الحركات المالية الفرعية (Transactions) أولاً
            # لتجنب الاصطدام بأي حراس (Triggers/Guards) يمنعون الكتابة على وردية مغلقة.

            # 1. تسوية الفارق (Forced Reconciliation)
            if variance_dec != D_0:
                trans_type = 'out' if variance_dec < D_0 else 'in'
                v_notes = f"تسوية إغلاق: {'عجز' if variance_dec < D_0 else 'زيادة'} | مبرر: {safe_notes}"
                cursor.execute("""
                    INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                    VALUES (?, 'cash_over_short', ?, ?, ?, ?, ?)
                """, (trans_type, shift_id, float(abs(variance_dec)), user_id, shift_id, v_notes))

            # 2. توريد النقدية (Cash Drop)
            if drop_dec > D_0:
                d_notes = f"توريد نقدية عند الإغلاق | المتبقي وصفي في الدرج: {rem}"
                cursor.execute("""
                    INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                    VALUES ('out', 'cash_drop', ?, ?, ?, ?, ?)
                """, (shift_id, float(drop_dec), user_id, shift_id, d_notes))

            # 3. توثيق سجل التدقيق (Audit Log) قبل تغيير الحالة النهائية
            audit_payload = json.dumps({
                "expected_cash_snapshot": float(expected_dec),
                "actual_cash": float(actual_dec),
                "variance": float(variance_dec),
                "cash_drop_amount": float(drop_dec),
                "remaining_cash_after_drop": float(rem),
                "closed_at": now_str,
                "closing_notes": safe_notes
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'shifts', ?, ?)
            """, (user_id, shift_id, audit_payload))

            # 4. التحديث النهائي لحالة الوردية (الختم الفولاذي)
            cursor.execute("""
                UPDATE shifts 
                SET expected_cash = ?, actual_cash = ?, variance = ?, status = 'closed', closed_at = ?, closing_notes = ?
                WHERE id = ?
            """, (float(expected_dec), float(actual_dec), float(variance_dec), now_str, safe_notes, shift_id))

            conn.commit()
            return True, {"message": "تم الإغلاق والتسوية بنجاح.", "summary": self.get_shift_summary(shift_id)}

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("Error closing shift:")
            return False, "فشل داخلي أثناء إغلاق الوردية."
        finally:
            conn.close()