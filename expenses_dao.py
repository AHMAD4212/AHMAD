"""
وظيفة الملف: كائن الوصول لبيانات المصروفات التشغيلية والنثرية (Strict OPEX DAO).

الطبقة: Data Access Layer / Business Logic

- [Strict OPEX Policy]: هذا الملف مخصص حصراً للنفقات التشغيلية (رواتب، إيجار، تشغيل، مسحوبات ملاك).
  يُمنع قطعياً استخدامه لسداد ذمم الموردين (Accounts Payable) لفصل العمليات المحاسبية.
- [Strict Shift Dependency]: كل مصروف نقدي يرتبط إجبارياً بـ shift_id مفتوح.
- [SSOT Cash Balance]: الرصيد النظري يُحسب من Transactions مع فلترة صارمة لأنواع الحركات النقدية.
- [Purchase Cash Integration]: دفعات المشتريات النقدية تُخصم من رصيد الوردية النظري.
- [Strict Entity Binding]: المستفيد من نوع (employee) يتطلب (payee_id) إلزامي.
- [Voiding Policy]: إبطال المصروف القديم يُسجل كـ (قيد وارد) محمياً بحارس الإقفال اليومي.
"""

from database.db_manager import DatabaseManager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import logging
import re

logger = logging.getLogger(__name__)

D_0 = Decimal('0.00')
D_2 = Decimal('0.01')
CASHIER_EXPENSE_LIMIT = Decimal('1000.00')


class ExpensesDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # 1. دوال العرض والتشخيص (Read-Only)
    # ==========================================
    def get_active_categories(self):
        """يجلب فئات المصروفات المعتمدة والنشطة فقط."""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM expense_categories WHERE is_active = 1 ORDER BY id ASC")
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching expense categories: {e}")
            return []
        finally:
            conn.close()

    def get_active_employees(self):
        """جلب قائمة الموظفين النشطين للواجهة (لصرف السلف والرواتب)."""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username FROM users WHERE is_active = 1 ORDER BY username ASC")
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching employees: {e}")
            return []
        finally:
            conn.close()

    def get_shift_theoretical_balance(self, cursor, shift_id):
        """مصدر الحقيقة الأوحد للنقدية المحمولة في الدرج."""
        cursor.execute("SELECT opening_cash FROM shifts WHERE id = ?", (shift_id,))
        shift_row = cursor.fetchone()
        if not shift_row: raise ValueError("الوردية غير موجودة.")

        opening_cash = Decimal(str(shift_row[0]))

        # الأنواع التي تدخل وتخرج فعلياً إلى درج النقدية
        in_types = ('sale', 'expense_void', 'return_void')
        out_types = ('return', 'expense', 'purchase')

        in_placeholders = ','.join(['?'] * len(in_types))
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE shift_id = ? AND transaction_type = 'in' AND reference_type IN ({in_placeholders})
        """, (shift_id, *in_types))
        total_in = Decimal(str(cursor.fetchone()[0]))

        out_placeholders = ','.join(['?'] * len(out_types))
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE shift_id = ? AND transaction_type = 'out' AND reference_type IN ({out_placeholders})
        """, (shift_id, *out_types))
        total_out = Decimal(str(cursor.fetchone()[0]))

        current_balance = opening_cash + total_in - total_out
        return current_balance

    def get_all_expenses(self, shift_id=None, start_date=None, end_date=None):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT e.id, c.name, e.amount, e.expense_date, e.payee_type, e.payee_name,
                       e.status, u.username, e.notes, e.shift_id, e.category_id, e.payee_id, e.created_at
                FROM expenses e
                JOIN expense_categories c ON e.category_id = c.id
                JOIN users u ON e.user_id = u.id
                WHERE 1=1
            """
            params = []
            if shift_id:
                query += " AND e.shift_id = ?"
                params.append(shift_id)
            if start_date and end_date:
                query += " AND e.expense_date BETWEEN ? AND ?"
                params.extend([start_date, end_date])
            query += " ORDER BY e.created_at DESC"

            cursor.execute(query, params)
            expenses = []
            for row in cursor.fetchall():
                expenses.append({
                    "id": row[0], "category_name": row[1], "amount": row[2],
                    "expense_date": row[3], "payee_type": row[4], "payee_name": row[5],
                    "status": row[6], "username": row[7], "notes": row[8],
                    "shift_id": row[9], "category_id": row[10], "payee_id": row[11],
                    "created_at": row[12]
                })
            return expenses
        except Exception as e:
            logger.error(f"Error fetching expenses: {e}")
            return []
        finally:
            conn.close()

    # ==========================================
    # 2. التنفيذ السيادي للمصروفات التشغيلية (Write / Execution)
    # ==========================================
    def process_expense(self, user_id, shift_id, category_id, amount, expense_date, payee_type, payee_name=None, payee_id=None, notes=""):
        if not user_id or not shift_id: return False, "بيانات المستخدم أو الوردية مفقودة."
        if not category_id: return False, "يجب اختيار فئة المصروف."

        try:
            amount_dec = Decimal(str(amount)).quantize(D_2, rounding=ROUND_HALF_UP)
            if amount_dec <= D_0: raise ValueError
        except (InvalidOperation, ValueError):
            return False, "قيمة المصروف غير صالحة. يجب أن تكون رقماً موجباً."

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", expense_date): return False, "صيغة التاريخ غير صالحة."

        try:
            exp_dt = datetime.strptime(expense_date, "%Y-%m-%d").date()
            if exp_dt > datetime.now().date(): return False, "لا يمكن تسجيل مصروف لتاريخ مستقبلي."
        except ValueError:
            return False, "تاريخ المصروف غير موجود فعلياً."

        # [Architectural Enforcement]: منع استخدام 'vendor' هنا نهائياً
        allowed_payees = ['employee', 'operational', 'owner_draw', 'other']
        if payee_type not in allowed_payees:
            return False, "نوع المستفيد غير صالح. (سداد الموردين يتم عبر وحدة سداد الذمم المستقلة)."

        clean_payee_name = (payee_name or "").strip()

        if payee_type in ['operational', 'owner_draw', 'other'] and not clean_payee_name:
            return False, "يجب تحديد اسم أو وصف المستفيد صراحة لهذه الفئة."

        if payee_type == 'employee' and not payee_id:
            return False, "يجب تحديد هوية الموظف (payee_id) بشكل إلزامي عندما يكون المستفيد موظفاً."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            if payee_type == 'employee':
                cursor.execute("SELECT username FROM users WHERE id = ?", (payee_id,))
                emp_row = cursor.fetchone()
                if not emp_row: raise ValueError("الموظف المحدد غير موجود في قاعدة البيانات.")
                final_payee_name = emp_row[0]
            else:
                final_payee_name = clean_payee_name

            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            if not user_row or user_row[1] != 1: raise ValueError("المستخدم غير موجود أو غير نشط.")
            user_role = user_row[0]

            if user_role == 'cashier' and amount_dec > CASHIER_EXPENSE_LIMIT:
                raise ValueError(f"المبلغ يتجاوز صلاحياتك (الحد الأقصى للكاشير: {CASHIER_EXPENSE_LIMIT}).")

            cursor.execute("SELECT status FROM shifts WHERE id = ? AND user_id = ?", (shift_id, user_id))
            shift_row = cursor.fetchone()
            if not shift_row or shift_row[0] != 'open':
                raise ValueError("الوردية الحالية مغلقة. تسجيل المصروف النقدي يستوجب وردية مفتوحة.")

            current_theory_balance = self.get_shift_theoretical_balance(cursor, shift_id)
            if amount_dec > current_theory_balance:
                raise ValueError(f"رصيد الوردية النظري ({current_theory_balance:,.2f}) لا يغطي قيمة المصروف.")

            cursor.execute("SELECT name FROM expense_categories WHERE id = ? AND is_active = 1", (category_id,))
            cat_row = cursor.fetchone()
            if not cat_row: raise ValueError("الفئة المحاسبية المحددة غير صالحة أو معطلة.")
            category_name = cat_row[0]

            cursor.execute("""
                INSERT INTO expenses (category_id, user_id, shift_id, amount, expense_date, payment_method, payee_type, payee_id, payee_name, status, notes)
                VALUES (?, ?, ?, ?, ?, 'cash', ?, ?, ?, 'completed', ?)
            """, (category_id, user_id, shift_id, float(amount_dec), expense_date, payee_type, payee_id, final_payee_name, notes))
            expense_id = cursor.lastrowid

            trans_notes = f"مصروف نقدي (تشغيلي): {category_name} | المستفيد: {final_payee_name} | ملاحظات: {notes}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                VALUES ('out', 'expense', ?, ?, ?, ?, ?)
            """, (expense_id, float(amount_dec), user_id, shift_id, trans_notes))

            audit_payload = json.dumps({"category": category_name, "amount": float(amount_dec), "payee_type": payee_type, "payee_name": final_payee_name}, ensure_ascii=False)
            cursor.execute("INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values) VALUES (?, 'INSERT', 'expenses', ?, ?)", (user_id, expense_id, audit_payload))

            conn.commit()
            return True, {"expense_id": expense_id, "amount": float(amount_dec), "category": category_name}

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ داخلي أثناء تسجيل المصروف التشغيلي:")
            return False, "فشل داخلي في الاعتماد."
        finally:
            conn.close()

    # ==========================================
    # 3. إبطال المصروفات (Immutability & Voiding)
    # ==========================================
    def void_expense(self, requester_id, current_shift_id, expense_id, void_reason=""):
        if not requester_id or not current_shift_id or not expense_id: return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            user_role = cursor.fetchone()
            if not user_role or user_role[0] != 'admin': raise ValueError("صلاحيات غير كافية.")

            cursor.execute("SELECT status FROM shifts WHERE id = ? AND user_id = ?", (current_shift_id, requester_id))
            shift_row = cursor.fetchone()
            if not shift_row or shift_row[0] != 'open': raise ValueError("الوردية الحالية مغلقة. الإبطال يستدعي قيداً وارداً للتسوية.")

            cursor.execute("""
                SELECT e.amount, e.status, c.name, e.shift_id FROM expenses e
                JOIN expense_categories c ON e.category_id = c.id WHERE e.id = ?
            """, (expense_id,))
            exp_row = cursor.fetchone()
            if not exp_row: raise ValueError("المصروف غير موجود.")
            exp_amount, current_status, cat_name, orig_shift_id = exp_row

            if current_status == 'voided': raise ValueError("هذا المصروف مُبطل مسبقاً.")

            cursor.execute("""
                SELECT dc.business_date FROM daily_closure_shifts dcs
                JOIN daily_closures dc ON dcs.daily_closure_id = dc.id WHERE dcs.shift_id = ?
            """, (orig_shift_id,))
            if cursor.fetchone(): raise ValueError("رفض سيادي: الوردية الأصلية لهذه الحركة أُقفلت وتم ترحيلها محاسبياً. يُمنع التعديل أو الإبطال.")

            new_notes = f" [أُبطل إدارياً: {void_reason}]" if void_reason else " [أُبطل إدارياً]"
            cursor.execute("UPDATE expenses SET status = 'voided', notes = COALESCE(notes, '') || ? WHERE id = ?", (new_notes, expense_id))

            trans_notes = f"قيد عكسي: إبطال مصروف ({cat_name}) رقم {expense_id} من الوردية الأصلية {orig_shift_id}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                VALUES ('in', 'expense_void', ?, ?, ?, ?, ?)
            """, (expense_id, exp_amount, requester_id, current_shift_id, trans_notes))

            audit_payload = json.dumps({"voided_expense_id": expense_id, "amount_reversed": exp_amount, "original_shift_id": orig_shift_id, "void_reason": void_reason}, ensure_ascii=False)
            cursor.execute("INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values) VALUES (?, 'UPDATE', 'expenses', ?, ?)", (requester_id, expense_id, audit_payload))

            conn.commit()
            return True, f"تم إبطال المصروف بنجاح. تم إصدار قيد مالي عكسي (وارد) بمبلغ {exp_amount:,.2f} في ورديتك الحالية."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ داخلي أثناء إبطال المصروف:")
            return False, "فشل داخلي."
        finally:
            conn.close()