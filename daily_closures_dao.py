"""
وظيفة الملف: النواة السيادية للإقفال اليومي وتسوية العمليات (Daily Closures DAO).
الطبقة: Data Access Layer / Business Logic
- [Constitution - Business Date]: اليوم التشغيلي يُعرّف بـ DATE(opened_at). أي وردية تُدرج ضمن الإقفال الخاص بتاريخ فتحها.
- [Atomic Execution - No TOCTOU]: دالة الاعتماد (create) تعيد الفحص والتجميع والإدراج داخل معاملة ذرية واحدة (BEGIN IMMEDIATE).
- [Top-Down Aggregation]: يجمع البيانات من الورديات المغلقة كمصدر أساسي، ومن (transactions) كداعم رقابي.
- [Prerequisite Guard]: يمنع الإقفال إذا وجدت أي وردية تتقاطع مع (business_date) أو تسبقه وما تزال مفتوحة. يعيد البيانات كمهيكل (Structured Data).
- [Precision Accounting]: تطبيق (Quantize D_2) على كافة المخرجات المالية في التجميع والتقارير.
- [Date Validation Guard]: يفحص صحة صيغة وتكوين التاريخ (YYYY-MM-DD) قبل البدء في أي استعلام لضمان النزاهة الهيكلية.
- [DRY Architecture]: استخراج المنطق الداخلي للجاهزية والتجميع في دالة (_collect_daily_closure_payload) لمنع تضارب الحقيقة بين المعاينة والاعتماد.
"""

from database.db_manager import DatabaseManager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import re

logger = logging.getLogger(__name__)

D_0 = Decimal('0.00')
D_2 = Decimal('0.01')

class DailyClosuresDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _validate_date(self, date_str):
        """[Date Validation Guard]: يضمن أن التاريخ المدخل بالصيغة الصحيحة وحقيقي فعلياً."""
        if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            raise ValueError("صيغة التاريخ غير صالحة. يرجى استخدام YYYY-MM-DD.")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError("التاريخ المدخل غير موجود فعلياً في التقويم.")

    def _collect_daily_closure_payload(self, cursor, business_date):
        """
        [Helper Function - Single Source of Truth]: دالة مساعدة معمارية تجمع بيانات الإقفال
        أو تعيد أسباب المنع. يتم استدعاؤها من (preview) للعرض، ومن (create) داخل الـ Transaction للاعتماد.
        """
        # 1. Prerequisite Guard (Blocking Shifts Structured Return)
        cursor.execute("""
            SELECT s.id, u.username, s.opened_at 
            FROM shifts s
            JOIN users u ON s.user_id = u.id
            WHERE s.status = 'open' AND DATE(s.opened_at) <= ?
        """, (business_date,))
        open_shifts = cursor.fetchall()

        if open_shifts:
            blocking_list = [{"shift_id": r[0], "username": r[1], "opened_at": r[2]} for r in open_shifts]
            return False, {
                "type": "blocking_shifts",
                "message": "لا يمكن إقفال اليوم. توجد ورديات ما تزال مفتوحة تمنع التسوية.",
                "blocking_open_shifts": blocking_list
            }

        # 2. Aggregation
        cursor.execute("""
            SELECT id, opening_cash, expected_cash, actual_cash, variance 
            FROM shifts 
            WHERE status = 'closed' 
              AND DATE(opened_at) = ? 
              AND id NOT IN (SELECT shift_id FROM daily_closure_shifts)
        """, (business_date,))

        target_shifts = cursor.fetchall()
        if not target_shifts:
            return False, {"type": "empty", "message": f"لا توجد ورديات مغلقة قابلة للإقفال لليوم التشغيلي ({business_date})."}

        shift_ids = []
        total_opening = D_0
        total_expected = D_0
        total_actual = D_0
        total_variance = D_0

        for s in target_shifts:
            shift_ids.append(s[0])
            total_opening += Decimal(str(s[1]))
            total_expected += Decimal(str(s[2]))
            total_actual += Decimal(str(s[3]))
            total_variance += Decimal(str(s[4]))

        placeholders = ','.join(['?'] * len(shift_ids))
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0) 
            FROM transactions 
            WHERE reference_type = 'cash_drop' AND shift_id IN ({placeholders})
        """, tuple(shift_ids))
        total_cash_drops = Decimal(str(cursor.fetchone()[0]))

        payload = {
            "business_date": business_date,
            "total_shifts_count": len(shift_ids),
            "shift_ids": shift_ids,
            "total_opening_cash": total_opening.quantize(D_2, rounding=ROUND_HALF_UP),
            "total_expected_cash": total_expected.quantize(D_2, rounding=ROUND_HALF_UP),
            "total_actual_cash": total_actual.quantize(D_2, rounding=ROUND_HALF_UP),
            "total_variance": total_variance.quantize(D_2, rounding=ROUND_HALF_UP),
            "total_cash_drops": total_cash_drops.quantize(D_2, rounding=ROUND_HALF_UP)
        }
        return True, payload

    # ==========================================
    # 1. المعاينة والجاهزية (Diagnostic / UI Support)
    # ==========================================
    def preview_daily_closure(self, requester_id, business_date):
        """
        يفحص جاهزية اليوم للإقفال ويعيد المجاميع أو قائمة الورديات المانعة.
        [Contract]: يعيد (True, Data_Dict) أو (False, Error_Dict_Structured).
        """
        if not requester_id:
            return False, {"type": "validation", "message": "معرّف المستخدم مفقود."}

        try:
            self._validate_date(business_date)
        except ValueError as ve:
            return False, {"type": "validation", "message": str(ve)}

        conn = self.db.connect()
        if not conn: return False, {"type": "connection", "message": "فشل الاتصال بقاعدة البيانات."}

        try:
            cursor = conn.cursor()

            # 1. RBAC
            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (requester_id,))
            u_row = cursor.fetchone()
            if not u_row or u_row[1] != 1 or u_row[0] != 'admin':
                return False, {"type": "rbac", "message": "الإقفال اليومي مقتصر حصراً على مدير النظام."}

            # 2. Idempotency
            cursor.execute("SELECT id FROM daily_closures WHERE business_date = ?", (business_date,))
            if cursor.fetchone():
                return False, {"type": "duplicate", "message": f"اليوم التشغيلي ({business_date}) مُقفل مسبقاً."}

            # 3. الاعتماد على المساعد (Helper) للحسابات
            return self._collect_daily_closure_payload(cursor, business_date)

        except Exception as e:
            logger.exception("Error in preview_daily_closure:")
            return False, {"type": "internal_error", "message": "خطأ داخلي أثناء حساب معاينة الإقفال."}
        finally:
            conn.close()

    # ==========================================
    # 2. التنفيذ السيادي للإقفال (Atomic Execution)
    # ==========================================
    def create_daily_closure(self, requester_id, business_date, notes=""):
        """
        [No TOCTOU Guarantee]: يُعيد تنفيذ كافة الفحوصات والحسابات داخل الـ Transaction
        التي ستقوم بالإدراج عبر دالة المساعد (_collect_daily_closure_payload).
        """
        if not requester_id:
            return False, "معرّف المستخدم مفقود."

        try:
            self._validate_date(business_date)
        except ValueError as ve:
            return False, str(ve)

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            # بدء المعاملة الذرية الصارمة
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE") # Lock the database for writing

            # 1. RBAC
            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (requester_id,))
            u_row = cursor.fetchone()
            if not u_row or u_row[1] != 1 or u_row[0] != 'admin':
                raise ValueError("الإقفال اليومي مقتصر حصراً على مدير النظام.")

            # 2. Idempotency Guard
            cursor.execute("SELECT id FROM daily_closures WHERE business_date = ?", (business_date,))
            if cursor.fetchone():
                raise ValueError(f"اليوم التشغيلي ({business_date}) مُقفل مسبقاً.")

            # 3. إعادة الفحص والتجميع عبر الـ Helper لضمان الـ Consistency
            success, payload = self._collect_daily_closure_payload(cursor, business_date)
            if not success:
                # payload هنا عبارة عن Dictionary مهيكل بالخطأ
                raise ValueError(payload.get("message", "لا يمكن اعتماد الإقفال لسبب غير معروف."))

            # 4. Insert Header
            safe_notes = notes.strip()
            cursor.execute("""
                INSERT INTO daily_closures 
                (business_date, total_shifts_count, total_opening_cash, total_expected_cash, 
                 total_actual_cash, total_variance, total_cash_drops, closed_by_user_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload["business_date"],
                payload["total_shifts_count"],
                float(payload["total_opening_cash"]),
                float(payload["total_expected_cash"]),
                float(payload["total_actual_cash"]),
                float(payload["total_variance"]),
                float(payload["total_cash_drops"]),
                requester_id,
                safe_notes
            ))
            closure_id = cursor.lastrowid

            # 5. Insert Lines (Mapping)
            for s_id in payload["shift_ids"]:
                cursor.execute("""
                    INSERT INTO daily_closure_shifts (daily_closure_id, shift_id)
                    VALUES (?, ?)
                """, (closure_id, s_id))

            # 6. Audit Log
            audit_payload = json.dumps({
                "business_date": business_date,
                "total_shifts_count": payload["total_shifts_count"],
                "total_variance": float(payload["total_variance"]),
                "total_cash_drops": float(payload["total_cash_drops"])
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'daily_closures', ?, ?)
            """, (requester_id, closure_id, audit_payload))

            conn.commit()
            return True, {"closure_id": closure_id, "message": f"تم اعتماد الإقفال اليومي لتاريخ {business_date} بنجاح نهائي."}

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("Atomic execution failed in create_daily_closure:")
            return False, "فشل داخلي أثناء اعتماد الإقفال. تم التراجع كلياً لحماية البيانات."
        finally:
            conn.close()

    # ==========================================
    # 3. التقارير الإدارية (Quantized Read-Only)
    # ==========================================
    def get_daily_closure_summary(self, requester_id, closure_id):
        """[Quantized Output]: يجلب ملخص الإقفال بدقة مالية صلبة."""
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT role FROM users WHERE id = ?", (requester_id,))
            u_row = cursor.fetchone()
            if not u_row or u_row[0] != 'admin': return None

            cursor.execute("""
                SELECT dc.id, dc.business_date, dc.total_shifts_count, dc.total_opening_cash,
                       dc.total_expected_cash, dc.total_actual_cash, dc.total_variance,
                       dc.total_cash_drops, u.username, dc.notes, dc.created_at
                FROM daily_closures dc
                JOIN users u ON dc.closed_by_user_id = u.id
                WHERE dc.id = ?
            """, (closure_id,))
            h_row = cursor.fetchone()
            if not h_row: return None

            header = {
                "closure_id": h_row[0],
                "business_date": h_row[1],
                "total_shifts_count": h_row[2],
                "total_opening_cash": float(Decimal(str(h_row[3])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "total_expected_cash": float(Decimal(str(h_row[4])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "total_actual_cash": float(Decimal(str(h_row[5])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "total_variance": float(Decimal(str(h_row[6])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "total_cash_drops": float(Decimal(str(h_row[7])).quantize(D_2, rounding=ROUND_HALF_UP)),
                "closed_by": h_row[8],
                "notes": h_row[9] or "-",
                "created_at": h_row[10]
            }

            cursor.execute("""
                SELECT s.id, u.username, s.actual_cash, s.variance, s.opened_at, s.closed_at
                FROM daily_closure_shifts dcs
                JOIN shifts s ON dcs.shift_id = s.id
                JOIN users u ON s.user_id = u.id
                WHERE dcs.daily_closure_id = ?
            """, (closure_id,))

            shifts = []
            for r in cursor.fetchall():
                shifts.append({
                    "shift_id": r[0],
                    "username": r[1],
                    "actual_cash": float(Decimal(str(r[2])).quantize(D_2, rounding=ROUND_HALF_UP)) if r[2] is not None else 0.0,
                    "variance": float(Decimal(str(r[3])).quantize(D_2, rounding=ROUND_HALF_UP)) if r[3] is not None else 0.0,
                    "opened_at": r[4],
                    "closed_at": r[5]
                })

            return {"header": header, "shifts": shifts}
        except Exception as e:
            logger.error(f"Error fetching daily closure summary: {e}")
            return None
        finally:
            conn.close()

    def get_all_daily_closures(self, requester_id, limit=50):
        """[Quantized Output]: السجل التاريخي للإقفالات."""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT role FROM users WHERE id = ?", (requester_id,))
            u_row = cursor.fetchone()
            if not u_row or u_row[0] != 'admin': return []

            cursor.execute("""
                SELECT dc.id, dc.business_date, dc.total_shifts_count, dc.total_actual_cash, 
                       dc.total_variance, dc.total_cash_drops, u.username, dc.created_at
                FROM daily_closures dc
                JOIN users u ON dc.closed_by_user_id = u.id
                ORDER BY dc.business_date DESC
                LIMIT ?
            """, (limit,))

            closures = []
            for r in cursor.fetchall():
                closures.append({
                    "closure_id": r[0],
                    "business_date": r[1],
                    "total_shifts_count": r[2],
                    "total_actual_cash": float(Decimal(str(r[3])).quantize(D_2, rounding=ROUND_HALF_UP)),
                    "total_variance": float(Decimal(str(r[4])).quantize(D_2, rounding=ROUND_HALF_UP)),
                    "total_cash_drops": float(Decimal(str(r[5])).quantize(D_2, rounding=ROUND_HALF_UP)),
                    "closed_by": r[6],
                    "created_at": r[7]
                })
            return closures
        except Exception as e:
            logger.error(f"Error fetching all daily closures: {e}")
            return []
        finally:
            conn.close()