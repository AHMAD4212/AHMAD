"""
وظيفة الملف: النواة السيادية لمعالجة المبيعات (Sales Execution Core).
الطبقة: Data Access Layer / Business Logic
- [Iron Wall Guard]&#58; يمنع قطعياً تنفيذ أي مبيعات على وردية مغلقة (يحمي Transactions من الفساد).
- [Clinical Guard]&#58; يمنع قطعياً صرف وصفة طبية لغير صاحبها (يطابق customer_id).
- [Identity Guard]&#58; يضمن تفرد الهوية السطرية (line_id) مبكراً لمنع تضارب الذاكرة.
- [Zero-Trust Validation]&#58; النواة لا تثق بأي تسعير أو تجميع من الواجهة؛ تعيد تجميع الكميات وتسعيرها داخلياً.
- [Strict Shift Ownership]&#58; يمنع أي مستخدم (بما في ذلك المدير) من البيع على وردية موظف آخر. المسؤولية فردية صارمة.
- [Safe Atomic Updates]&#58; يخصم المخزون باستخدام شرط (quantity >= ?) ويفحص (rowcount) لمنع الانزلاق للسالب.
- [Batch Splitting Engine]&#58; يوفر دالة (FIFO) لتوزيع الكميات على التشغيلات لدعم الواجهة.
- [Alternative Routing Support]&#58; إضافة دالة تعريف هوية الدواء حتى لو كان غير متاح للبيع حالياً،
  لتمكين اقتراح البدائل الدوائية بدقة دون خلط بين (عدم الوجود) و(وجود بلا رصيد).
- [Requirement 19 - Print Support]&#58; إضافة دالة سيادية لجلب بيانات فاتورة البيع النهائية
  بشكل جاهز للطباعة / PDF من السجلات المعتمدة فعلياً في قاعدة البيانات.
"""

from database.db_manager import DatabaseManager
from models.offers_dao import OffersDAO
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class SalesDAO:
    def __init__(self):
        self.db = DatabaseManager()
        self.offers_dao = OffersDAO()

    # ==========================================
    # Helpers داخلية
    # ==========================================
    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    # ==========================================
    # 1. دوال العرض والتحضير للواجهة (Read-Only)
    # ==========================================
    def get_medicine_by_barcode_or_name(self, text):
        """يجلب بيانات الدواء الأساسية للـ POS كواجهة عرض مبدئية."""
        conn = self.db.connect()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")

            query = """
                SELECT
                    m.id,
                    m.name,
                    (SELECT sell_price
                     FROM batches
                     WHERE medicine_id = m.id
                       AND status = 'active'
                       AND quantity > 0
                       AND expiry_date >= ?
                     ORDER BY expiry_date ASC
                     LIMIT 1) as current_sell_price,
                    SUM(b.quantity) as sellable_qty,
                    m.barcode,
                    m.is_controlled,
                    m.controlled_class,
                    m.is_hazardous
                FROM medicines m
                JOIN batches b ON m.id = b.medicine_id
                WHERE (m.barcode = ? OR m.name LIKE ?)
                  AND b.status = 'active'
                  AND b.quantity > 0
                  AND b.expiry_date >= ?
                GROUP BY m.id
                LIMIT 1
            """
            cursor.execute(query, (today_str, text, f"%{text}%", today_str))
            return cursor.fetchone()

        except Exception as e:
            logger.error(f"Search Error: {e}")
            return None
        finally:
            conn.close()

    def get_medicine_identity_by_barcode_or_name(self, text):
        """
        يجلب هوية الدواء الأساسية حتى لو لم يكن قابلاً للبيع حالياً.
        الهدف:
        - التمييز بين:
          1) دواء غير موجود أصلاً في النظام
          2) دواء موجود لكنه غير متاح حالياً بسبب نفاد/انتهاء/تعطيل
        - تمكين واجهة POS من استدعاء البدائل الدوائية للدواء الأصلي حتى عند نفاد رصيده.

        المخرجات:
        (id, name, barcode, active_ingredient, dosage_form, strength, is_controlled, controlled_class, is_hazardous)
        """
        conn = self.db.connect()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            query = """
                SELECT
                    id,
                    name,
                    barcode,
                    active_ingredient,
                    dosage_form,
                    strength,
                    is_controlled,
                    controlled_class,
                    is_hazardous
                FROM medicines
                WHERE barcode = ?
                   OR name LIKE ?
                ORDER BY id ASC
                LIMIT 1
            """
            cursor.execute(query, (text, f"%{text}%"))
            return cursor.fetchone()

        except Exception as e:
            logger.error(f"Medicine identity lookup error: {e}")
            return None
        finally:
            conn.close()

    def get_medicine_flags(self, medicine_id):
        """جلب آمن للحالة الرقابية والخطرة عبر الـ ID حصراً"""
        conn = self.db.connect()
        if not conn:
            return 0, 0

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_controlled, is_hazardous FROM medicines WHERE id = ?",
                (medicine_id,)
            )
            row = cursor.fetchone()
            return row if row else (0, 0)
        finally:
            conn.close()

    def get_fifo_batches_for_qty(self, medicine_id, required_qty):
        """
        [Batch Splitting Engine]
        يجلب تشغيلات متعددة (FIFO) لتغطية الكمية المطلوبة بالكامل للواجهة.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT id, batch_number, sell_price, quantity, expiry_date
                FROM batches
                WHERE medicine_id = ? AND status = 'active' AND quantity > 0 AND expiry_date >= ?
                ORDER BY expiry_date ASC
            """, (medicine_id, today_str))

            batches = cursor.fetchall()
            allocated = []
            remaining = required_qty

            for b in batches:
                if remaining <= 0:
                    break

                b_id, b_num, b_price, b_qty, _ = b
                take = min(b_qty, remaining)
                allocated.append({
                    'batch_id': b_id,
                    'batch_number': b_num,
                    'sell_price': b_price,
                    'taken_qty': take,
                    'max_qty': b_qty
                })
                remaining -= take

            return allocated

        except Exception as e:
            logger.error(f"FIFO Batch Allocation Error: {e}")
            return []
        finally:
            conn.close()

    def quote_sale(self, ui_items):
        """
        [Architecture Feature]: دالة التسعير اللحظي (Diagnostic Contract).
        لا تتجاهل السطور المشوهة بصمت، بل تعيد قائمة (invalid_lines) مع سبب الرفض،
        بالإضافة لرسائل الخطأ العامة.
        """
        result = {
            "items": [],
            "invalid_lines": [],
            "gross_subtotal": 0.0,
            "subtotal_amount": 0.0,
            "total_item_discounts": 0.0,
            "cart_discount_amount": 0.0,
            "net_total": 0.0,
            "general_error": None
        }

        if not ui_items:
            return result

        conn = self.db.connect()
        if not conn:
            result["general_error"] = "فشل الاتصال بقاعدة البيانات."
            return result

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")
            engine_input = []

            for item in ui_items:
                l_id = item.get('line_id')
                b_id = item.get('batch_id')
                m_id = item.get('medicine_id')
                qty = item.get('qty')

                if not l_id:
                    result["general_error"] = "يوجد سطر في السلة يفتقد للهوية (line_id مفقود). السلة تالفة."
                    return result

                if not b_id or not m_id:
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": "نقص في بيانات الصنف أو التشغيلة."
                    })
                    continue

                if type(qty) is not int or qty <= 0:
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": "الكمية غير صالحة."
                    })
                    continue

                cursor.execute("""
                    SELECT sell_price, status, expiry_date, quantity
                    FROM batches
                    WHERE id = ? AND medicine_id = ?
                """, (b_id, m_id))
                b_row = cursor.fetchone()

                if not b_row:
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": "التشغيلة غير موجودة أو لا تطابق الدواء."
                    })
                    continue

                if b_row[1] != 'active':
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": "التشغيلة غير نشطة (موقوفة)."
                    })
                    continue

                if b_row[2] < today_str:
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": "التشغيلة منتهية الصلاحية."
                    })
                    continue

                if qty > b_row[3]:
                    result["invalid_lines"].append({
                        "line_id": l_id,
                        "reason": f"تجاوز الرصيد المتاح ({b_row[3]})."
                    })
                    continue

                engine_input.append({
                    'line_id': l_id,
                    'medicine_id': m_id,
                    'qty': qty,
                    'price': b_row[0]
                })

            if engine_input:
                try:
                    pricing_result = self.offers_dao.evaluate_cart(engine_input)
                    result.update(pricing_result)
                except ValueError as ve:
                    result["general_error"] = str(ve)

            return result

        except Exception:
            logger.exception("Quote Sale Error:")
            result["general_error"] = "خطأ داخلي أثناء التسعير."
            return result
        finally:
            conn.close()

    # ==========================================
    # 1.5 دعم الطباعة / الفواتير (Requirement 19)
    # ==========================================
    def get_sale_receipt_data(self, sale_id):
        """
        جلب بيانات فاتورة بيع معتمدة بشكل جاهز للطباعة / PDF.

        المخرجات عند النجاح:
        (True, {
            "sale_id": ...,
            "invoice_number": ...,
            "sale_date": ...,
            "cashier_name": ...,
            "customer_name": ...,
            "customer_phone": ...,
            "doctor_name": ...,
            "subtotal_amount": ...,
            "cart_discount_amount": ...,
            "total_amount": ...,
            "applied_cart_offer_id": ...,
            "items": [
                {
                    "name": ...,
                    "batch": ...,
                    "qty": ...,
                    "price": ...,
                    "total": ...,
                    "discount_amount": ...,
                    "original_unit_price": ...,
                    "final_unit_price": ...
                }
            ]
        })

        عند الفشل:
        (False, "رسالة الخطأ")
        """
        try:
            sale_id = int(sale_id)
            if sale_id <= 0:
                return False, "رقم الفاتورة/البيع غير صالح."
        except (TypeError, ValueError):
            return False, "رقم الفاتورة/البيع غير صالح."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # ------------------------------
            # 1) رأس الفاتورة
            # ------------------------------
            cursor.execute("""
                SELECT
                    s.id,
                    s.sale_date,
                    s.subtotal_amount,
                    s.cart_discount_amount,
                    s.total_amount,
                    s.applied_cart_offer_id,
                    u.username AS cashier_name,
                    COALESCE(c.name, 'عميل نقدي') AS customer_name,
                    COALESCE(c.phone, '') AS customer_phone,
                    COALESCE(s.doctor_name, '') AS doctor_name
                FROM sales s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN customers c ON s.customer_id = c.id
                WHERE s.id = ?
            """, (sale_id,))
            header_row = cursor.fetchone()

            if not header_row:
                return False, "فاتورة البيع المطلوبة غير موجودة."

            receipt_data = {
                "sale_id": header_row[0],
                "invoice_number": f"SALE-{header_row[0]}",
                "sale_date": header_row[1],
                "subtotal_amount": self._safe_float(header_row[2]),
                "cart_discount_amount": self._safe_float(header_row[3]),
                "total_amount": self._safe_float(header_row[4]),
                "applied_cart_offer_id": header_row[5],
                "cashier_name": header_row[6] or "Unknown",
                "customer_name": header_row[7] or "عميل نقدي",
                "customer_phone": header_row[8] or "",
                "doctor_name": header_row[9] or "",
                "items": []
            }

            # ------------------------------
            # 2) أسطر الفاتورة الفعلية
            # ------------------------------
            cursor.execute("""
                SELECT
                    si.id,
                    m.name,
                    COALESCE(b.batch_number, '-') AS batch_number,
                    si.quantity,
                    si.original_unit_price,
                    si.discount_amount,
                    si.final_unit_price,
                    si.total_item_price
                FROM sale_items si
                JOIN medicines m ON si.medicine_id = m.id
                LEFT JOIN batches b ON si.batch_id = b.id
                WHERE si.sale_id = ?
                ORDER BY si.id ASC
            """, (sale_id,))
            item_rows = cursor.fetchall()

            if not item_rows:
                return False, "الفاتورة موجودة ولكن لا تحتوي على أي أصناف صالحة للطباعة."

            items = []
            for row in item_rows:
                items.append({
                    "sale_item_id": row[0],
                    "name": row[1],
                    "batch": row[2],
                    "qty": int(row[3] or 0),
                    "original_unit_price": self._safe_float(row[4]),
                    "discount_amount": self._safe_float(row[5]),
                    "final_unit_price": self._safe_float(row[6]),
                    "price": self._safe_float(row[6]),   # توافق مع pdf_generator الحالي
                    "total": self._safe_float(row[7])    # توافق مع pdf_generator الحالي
                })

            receipt_data["items"] = items
            receipt_data["items_count"] = len(items)

            return True, receipt_data

        except Exception:
            logger.exception("Receipt data fetch error:")
            return False, "حدث خطأ داخلي أثناء تجهيز بيانات الفاتورة للطباعة."
        finally:
            conn.close()

    # ==========================================
    # 2. التنفيذ السيادي للمبيعات (Write / Execution)
    # ==========================================
    def create_sale(self, *args, **kwargs):
        """
        [طبقة توافق - Alias]: تحمي الواجهات القديمة التي تعتمد على اسم (create_sale)
        من الانهيار وتوجهها مباشرة للمحرك الحديث (process_sale).
        """
        return self.process_sale(*args, **kwargs)

    def process_sale(self, user_id, shift_id, customer_id, doctor_name, ui_items, expected_net_total, controlled_data=None):
        """
        ui_items format: [{'line_id': str, 'medicine_id': int, 'batch_id': int, 'qty': int, 'prescription_item_id': int}]
        """
        if not ui_items:
            return False, "سلة المبيعات فارغة."

        # ==========================================
        # 0. التحقق التعاقدي الآمن من المدخلات (Contract Safe Parsing)
        # ==========================================
        try:
            expected_total = float(expected_net_total)
        except (TypeError, ValueError):
            return False, "القيمة المتوقعة لإجمالي الفاتورة غير صالحة."

        if expected_total < 0:
            return False, "القيمة المتوقعة لإجمالي الفاتورة لا يمكن أن تكون سالبة."

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")
            sale_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # ==========================================
            # 🛡️ THE IRON WALL GUARD (حارس الوردية الصارم)
            # ==========================================
            if not shift_id:
                raise ValueError("اختراق أمني: لا يمكن تنفيذ عملية بيع بدون رقم وردية (shift_id).")

            cursor.execute("SELECT status, user_id FROM shifts WHERE id = ?", (shift_id,))
            shift_row = cursor.fetchone()

            if not shift_row:
                raise ValueError("الوردية المحددة غير موجودة في النظام.")

            if shift_row[0] != 'open':
                raise ValueError("رفض سيادي: الوردية المحددة (مغلقة). يُمنع منعاً باتاً تسجيل أي مبيعات أو إدخال نقدية عليها.")

            # [Strict Shift Ownership Policy]
            if shift_row[1] != user_id:
                raise ValueError("الوردية المفتوحة المحددة لا تخص المستخدم الحالي. المسؤولية النقدية فردية ولا يمكن البيع على وردية موظف آخر.")
            # ==========================================

            # ==========================================
            # 1. التدقيق المعماري والرقابي الأساسي (Core RBAC)
            # ==========================================
            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            if not user_row or user_row[1] != 1:
                raise ValueError("المستخدم غير موجود أو الحساب غير نشط.")

            user_role = user_row[0]
            if user_role not in ['admin', 'pharmacist', 'cashier']:
                raise ValueError("صلاحياتك لا تسمح بإتمام عمليات البيع.")

            if customer_id:
                cursor.execute("SELECT id FROM customers WHERE id = ?", (customer_id,))
                if not cursor.fetchone():
                    raise ValueError("العميل المحدد غير موجود في قاعدة البيانات.")

            # ==========================================
            # 2. التجميع الاستباقي وتفرد الهوية (Pre-Aggregation & Identity Guard)
            # ==========================================
            batch_requested_totals = {}
            rx_requested_totals = {}
            seen_line_ids = set()

            for item in ui_items:
                l_id = item.get('line_id')
                b_id = item.get('batch_id')
                m_id = item.get('medicine_id')
                qty = item.get('qty')
                rx_id = item.get('prescription_item_id')

                if not l_id:
                    raise ValueError("كل سطر يجب أن يحتوي على معرف فريد (line_id).")
                if l_id in seen_line_ids:
                    raise ValueError(f"المعرف السطري مكرر داخل السلة: {l_id}")
                seen_line_ids.add(l_id)

                if not b_id or not m_id:
                    raise ValueError(f"بيانات السطر غير مكتملة (نقص في الصنف أو التشغيلة) للسطر {l_id}.")
                if type(qty) is not int or qty <= 0:
                    raise ValueError(f"الكمية غير صالحة للسطر {l_id}.")

                batch_requested_totals[b_id] = batch_requested_totals.get(b_id, 0) + qty
                if rx_id:
                    rx_requested_totals[rx_id] = rx_requested_totals.get(rx_id, 0) + qty

            # ==========================================
            # 3. التحقق السيادي للتشغيلات والوصفات (Zero-Trust DB Validation)
            # ==========================================
            batch_data_map = {}
            has_controlled_drugs = False

            # فحص إجماليات التشغيلات (Batches)
            for b_id, total_qty in batch_requested_totals.items():
                cursor.execute("""
                    SELECT b.sell_price, b.status, b.expiry_date, b.quantity,
                           m.id, m.is_controlled, m.controlled_class, m.is_hazardous, m.name
                    FROM batches b
                    JOIN medicines m ON b.medicine_id = m.id
                    WHERE b.id = ?
                """, (b_id,))
                b_row = cursor.fetchone()

                if not b_row:
                    raise ValueError(f"التشغيلة المحددة ({b_id}) غير موجودة.")
                b_sell_price, b_status, b_expiry, db_b_qty, m_id_db, is_ctrl, ctrl_class, is_haz, med_name = b_row

                if b_status != 'active':
                    raise ValueError(f"التشغيلة للصنف ({med_name}) غير نشطة.")
                if b_expiry < today_str:
                    raise ValueError(f"التشغيلة للصنف ({med_name}) منتهية الصلاحية.")
                if total_qty > db_b_qty:
                    raise ValueError(f"إجمالي الكمية المطلوبة ({total_qty}) يتجاوز الرصيد المتاح ({db_b_qty}) في التشغيلة للصنف ({med_name}).")

                if is_ctrl == 1:
                    has_controlled_drugs = True
                batch_data_map[b_id] = b_row

            # فحص إجماليات الوصفات الطبية (Prescriptions & Clinical Guard)
            rx_data_map = {}
            if rx_requested_totals and not customer_id:
                raise ValueError("يجب تحديد العميل عند بيع أي صنف مرتبط بوصفة طبية.")

            for rx_id, total_qty in rx_requested_totals.items():
                cursor.execute("""
                    SELECT pi.medicine_id, pi.prescribed_qty, pi.dispensed_qty,
                           p.status, p.expiry_date, p.id, p.doctor_id, p.customer_id
                    FROM prescription_items pi
                    JOIN prescriptions p ON pi.prescription_id = p.id
                    WHERE pi.id = ?
                """, (rx_id,))
                rx_row = cursor.fetchone()

                if not rx_row:
                    raise ValueError(f"سطر الوصفة المرجعي ({rx_id}) غير موجود.")
                rx_med_id, prescribed_qty, dispensed_qty, rx_status, rx_expiry, p_id, p_doc_id, p_cust_id = rx_row

                # المطابقة السريرية للعميل
                if p_cust_id != customer_id:
                    raise ValueError(f"الوصفة المرجعية ({rx_id}) لا تخص العميل المحدد في الفاتورة.")

                if rx_status not in ('active', 'partially_dispensed'):
                    raise ValueError(f"الوصفة المرتبطة غير صالحة للصرف (الحالة: {rx_status}).")
                if rx_expiry < today_str:
                    raise ValueError("إحدى الوصفات المرتبطة منتهية الصلاحية.")

                remaining_rx_qty = prescribed_qty - dispensed_qty
                if total_qty > remaining_rx_qty:
                    raise ValueError(f"إجمالي الكمية المطلوبة ({total_qty}) يتجاوز المتبقي في الوصفة ({remaining_rx_qty}).")

                rx_data_map[rx_id] = rx_row

            # ==========================================
            # 4. الرقابة الأمنية المشددة (Controlled Drugs Strict Checks)
            # ==========================================
            if has_controlled_drugs:
                if user_role not in ['admin', 'pharmacist']:
                    raise ValueError("صلاحيات غير كافية. بيع الأدوية الرقابية مقتصر حصراً على 'المدير' أو 'الصيدلي'.")

                if not customer_id:
                    raise ValueError("يجب تحديد ملف العميل لإتمام بيع الأدوية الرقابية/المخدرة.")

                if not controlled_data:
                    raise ValueError("السلة تحتوي أدوية رقابية ولكن بيانات المستلم القانونية مفقودة.")

                recv_name = controlled_data.get('receiver_full_name')
                recv_nid = controlled_data.get('receiver_national_id')
                recv_rel = controlled_data.get('receiver_relation')

                if not recv_name or not str(recv_name).strip():
                    raise ValueError("اسم المستلم إلزامي للأدوية الرقابية.")
                if not recv_nid or not str(recv_nid).strip():
                    raise ValueError("الرقم الوطني/الهوية للمستلم إلزامي.")

                # التحقق الصارم من صلة القرابة
                allowed_relations = {'self', 'parent', 'spouse', 'guardian', 'other'}
                if not recv_rel or recv_rel not in allowed_relations:
                    raise ValueError("قيمة صلة القرابة غير صالحة قانونياً. يجب أن تكون من القيم المعتمدة.")

            # ==========================================
            # 5. بناء معطيات المحرك السعري (Engine Input Builder)
            # ==========================================
            engine_input = []
            line_meta_map = {}

            for item in ui_items:
                l_id = item['line_id']
                b_id = item['batch_id']
                m_id = item['medicine_id']
                rx_id = item.get('prescription_item_id')
                qty = item['qty']

                b_row = batch_data_map[b_id]
                if b_row[4] != m_id:
                    raise ValueError(f"عدم تطابق الدواء مع التشغيلة للسطر {l_id}.")

                if rx_id:
                    rx_row = rx_data_map[rx_id]
                    if rx_row[0] != m_id:
                        raise ValueError(f"الدواء المختار لا يطابق الدواء المسجل في الوصفة للسطر {l_id}.")
                elif b_row[5] == 1:
                    raise ValueError(f"اختراق رقابي: يمنع بيع الدواء الرقابي ({b_row[8]}) دون وصفة طبية.")

                engine_input.append({
                    'line_id': l_id,
                    'medicine_id': m_id,
                    'qty': qty,
                    'price': b_row[0]
                })

                line_meta_map[l_id] = {
                    'batch_id': b_id,
                    'prescription_item_id': rx_id,
                    'is_controlled': b_row[5],
                    'controlled_class': b_row[6],
                    'med_name': b_row[8],
                    'rx_id_for_log': rx_data_map[rx_id][5] if rx_id else None,
                    'rx_doctor_id_for_log': rx_data_map[rx_id][6] if rx_id else None
                }

            # ==========================================
            # 6. التسعير السيادي والحماية ضد التلاعب (Pricing & Anti-Tampering)
            # ==========================================
            try:
                pricing_result = self.offers_dao.evaluate_cart(engine_input)
            except ValueError as ve:
                raise ValueError(f"تم رفض السلة من محرك التسعير: {str(ve)}")

            actual_net_total = pricing_result['net_total']
            if abs(actual_net_total - expected_total) > 0.01:
                raise ValueError(f"تغيرت الأسعار أو العروض (المتوقع: {expected_total}، الفعلي: {actual_net_total}). تم حظر العملية، يرجى إعادة تسعير السلة.")

            # ==========================================
            # 7. الالتزام المحاسبي والمخزني (Atomic Committing)
            # ==========================================
            cursor.execute("""
                INSERT INTO sales (user_id, shift_id, customer_id, doctor_name,
                                   subtotal_amount, cart_discount_amount, total_amount, applied_cart_offer_id, sale_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                shift_id,
                customer_id,
                doctor_name,
                pricing_result['subtotal_amount'],
                pricing_result['cart_discount_amount'],
                actual_net_total,
                pricing_result['applied_cart_offer_id'],
                sale_date
            ))
            sale_id = cursor.lastrowid

            for priced_item in pricing_result['items']:
                l_id = priced_item['line_id']
                meta = line_meta_map[l_id]
                qty = priced_item['qty']

                cursor.execute("""
                    INSERT INTO sale_items (
                        sale_id, medicine_id, batch_id, quantity, prescription_item_id,
                        original_unit_price, discount_amount, final_unit_price, price_at_sale, total_item_price, applied_offer_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sale_id,
                    priced_item['medicine_id'],
                    meta['batch_id'],
                    qty,
                    meta['prescription_item_id'],
                    priced_item['original_unit_price'],
                    priced_item['discount_amount'],
                    priced_item['final_unit_price'],
                    priced_item['final_unit_price'],
                    priced_item['total_item_price'],
                    priced_item['applied_offer_id']
                ))
                sale_item_id = cursor.lastrowid

                # التحديث الآمن للمخزون لمنع الانزلاق
                cursor.execute("""
                    UPDATE batches SET quantity = quantity - ? WHERE id = ? AND quantity >= ?
                """, (qty, meta['batch_id'], qty))
                if cursor.rowcount == 0:
                    raise ValueError(f"تضارب مخزون حرج: تعذر سحب الكمية من التشغيلة ({meta['batch_id']}) للصنف ({meta['med_name']}).")

                cursor.execute(
                    "UPDATE batches SET status = 'depleted' WHERE id = ? AND quantity = 0",
                    (meta['batch_id'],)
                )

                cursor.execute("""
                    UPDATE medicines SET quantity = quantity - ? WHERE id = ? AND quantity >= ?
                """, (qty, priced_item['medicine_id'], qty))
                if cursor.rowcount == 0:
                    raise ValueError(f"تضارب مخزون حرج: الرصيد الإجمالي للصنف ({meta['med_name']}) غير كافٍ.")

                # دفتر المخدرات
                if meta['is_controlled'] == 1:
                    cursor.execute("""
                        INSERT INTO controlled_dispensing_log
                        (sale_id, sale_item_id, prescription_id, prescription_item_id, medicine_id, batch_id, customer_id, doctor_id, pharmacist_user_id, dispensed_qty, receiver_full_name, receiver_national_id, receiver_phone, receiver_relation, controlled_class, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sale_id,
                        sale_item_id,
                        meta['rx_id_for_log'],
                        meta['prescription_item_id'],
                        priced_item['medicine_id'],
                        meta['batch_id'],
                        customer_id,
                        meta['rx_doctor_id_for_log'],
                        user_id,
                        qty,
                        controlled_data.get('receiver_full_name'),
                        controlled_data.get('receiver_national_id'),
                        controlled_data.get('receiver_phone'),
                        controlled_data.get('receiver_relation'),
                        meta['controlled_class'],
                        controlled_data.get('notes')
                    ))

            # ==========================================
            # 8. التوثيق المالي والأمني وتسوية الوصفات (Audit, Trx, Recon)
            # ==========================================
            trans_notes = f"إيراد مبيعات لفاتورة رقم {sale_id}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                VALUES ('in', 'sale', ?, ?, ?, ?, ?)
            """, (sale_id, actual_net_total, user_id, shift_id, trans_notes))

            audit_json = json.dumps({
                "net_total": actual_net_total,
                "subtotal_amount": pricing_result['subtotal_amount'],
                "cart_discount_amount": pricing_result['cart_discount_amount'],
                "items_count": len(pricing_result['items'])
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'sales', ?, ?)
            """, (user_id, sale_id, audit_json))

            from models.prescriptions_dao import PrescriptionsDAO
            PrescriptionsDAO().reconcile_sale(cursor, sale_id)

            conn.commit()
            return True, {
                "sale_id": sale_id,
                "net_total": actual_net_total,
                "items_count": len(pricing_result['items'])
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("انهيار حرج أثناء معالجة عملية البيع (POS Core):")
            return False, "فشل داخلي في اعتماد الفاتورة. تم إلغاء العملية لحماية البيانات."
        finally:
            conn.close()