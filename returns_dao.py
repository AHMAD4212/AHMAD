"""
وظيفة الملف: كائن الوصول لبيانات المرتجعات (Returns DAO).
الطبقة: Data Access Layer / Business Logic
- [Iron Wall Guard]: يمنع تنفيذ أي مرتجع أو سحب نقدي من وردية مغلقة (يحمي Transactions من الفساد).
- [Single Source of Logic]: توحيد منطق التسعير العكسي في دالة (_evaluate_return_request) تخدم الـ Quote والـ Process معاً لمنع انقسام الحقيقة.
- [Pro-Rata Financial SSOT]: (refund_amount) الإجمالي هو مصدر الحقيقة الأوحد. تطبيق Quantize بدقة D_2 لمنع الفروق الهللية.
- [Reverse Legal Audit]: إبطال المرتجع ينسحب أثره على السجل الرقابي مع استخدام (COALESCE) لحماية الملاحظات القديمة من الضياع.
- [Pre-Aggregation Guard]: دمج السطور المطلوبة بناءً على (sale_item_id) قبل المعالجة لمنع ثغرات التجاوز المزدوج.
- [Current Shift Voiding Policy]: إبطال المرتجعات يتم حصراً عبر قيد تسوية (in) في وردية المدير "الحالية المفتوحة" ولا يمس الوردية الأصلية المغلقة.
"""

from database.db_manager import DatabaseManager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

logger = logging.getLogger(__name__)

D_0 = Decimal('0.00')
D_2 = Decimal('0.01')
D_4 = Decimal('0.0000')

class ReturnsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # 1. دوال العرض والتشخيص (Read-Only)
    # ==========================================
    def get_sale_for_return(self, sale_id):
        """
        يجلب رأس الفاتورة والسطور القابلة للإرجاع بصيغة آمنة للواجهة.
        """
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT s.id, s.sale_date, s.total_amount, c.name, u.username, s.customer_id, s.shift_id
                FROM sales s
                LEFT JOIN customers c ON s.customer_id = c.id
                JOIN users u ON s.user_id = u.id
                WHERE s.id = ?
            """, (sale_id,))
            header_row = cursor.fetchone()

            if not header_row: return None

            header = {
                "sale_id": header_row[0],
                "sale_date": header_row[1],
                "total_amount": header_row[2],
                "customer_name": header_row[3] if header_row[3] else "عميل نقدي",
                "cashier_name": header_row[4],
                "customer_id": header_row[5],
                "original_shift_id": header_row[6]
            }

            cursor.execute("""
                SELECT 
                    si.id AS sale_item_id,
                    m.id AS medicine_id,
                    m.name AS medicine_name,
                    b.id AS batch_id,
                    b.batch_number,
                    si.quantity AS sold_qty,
                    si.total_item_price,
                    COALESCE((SELECT SUM(ri.quantity) FROM return_items ri JOIN returns r ON ri.return_id = r.id WHERE ri.sale_item_id = si.id AND r.status != 'voided'), 0) AS already_returned_qty,
                    m.is_controlled,
                    si.prescription_item_id
                FROM sale_items si
                JOIN medicines m ON si.medicine_id = m.id
                JOIN batches b ON si.batch_id = b.id
                WHERE si.sale_id = ?
            """, (sale_id,))

            lines = []
            for row in cursor.fetchall():
                sold_qty = row[5]
                already_returned = row[7]
                returnable_qty = sold_qty - already_returned

                if returnable_qty > 0:
                    lines.append({
                        'sale_item_id': row[0],
                        'medicine_id': row[1],
                        'medicine_name': row[2],
                        'batch_id': row[3],
                        'batch_number': row[4],
                        'sold_qty': sold_qty,
                        'already_returned_qty': already_returned,
                        'returnable_qty': returnable_qty,
                        'historical_line_total': row[6],
                        'is_controlled': row[8],
                        'prescription_item_id': row[9]
                    })

            return {"header": header, "lines": lines}
        except Exception as e:
            logger.error(f"Error fetching sale for return: {e}")
            return None
        finally:
            conn.close()

    # ==========================================
    # 2. المحرك المركزي للتسعير العكسي (Single Source of Logic)
    # ==========================================
    def _evaluate_return_request(self, cursor, sale_id, requested_lines):
        """
        المحرك السيادي الذي يخدم الـ Quote والـ Process معاً.
        يستقبل: [{'sale_item_id': int, 'return_qty': int}]
        يقوم بدمج الطلبات، التحقق من السجل التاريخي، وحساب الرد المالي (Pro-Rata).
        """
        result = {
            "eligible_lines": [],
            "invalid_lines": [],
            "total_refund_amount": 0.0,
            "has_controlled": False
        }

        # 1. التجميع المسبق (Pre-Aggregation Guard)
        aggregated_request = {}
        for req in requested_lines:
            si_id = req.get('sale_item_id')
            qty_val = req.get('return_qty')

            if not si_id or type(qty_val) is not int or qty_val <= 0:
                result["invalid_lines"].append({"sale_item_id": si_id, "reason": "بيانات سطر غير صالحة أو كمية سالبة."})
                continue

            aggregated_request[si_id] = aggregated_request.get(si_id, 0) + qty_val

        if not aggregated_request:
            return result

        # 2. جلب الحقيقة التاريخية
        placeholders = ','.join(['?'] * len(aggregated_request))
        si_ids = list(aggregated_request.keys())

        cursor.execute(f"""
            SELECT si.id, si.quantity, si.total_item_price, m.name, b.id, b.batch_number, m.id, m.is_controlled, m.controlled_class, si.prescription_item_id,
                   COALESCE((SELECT SUM(ri.quantity) FROM return_items ri JOIN returns r ON ri.return_id = r.id WHERE ri.sale_item_id = si.id AND r.status != 'voided'), 0) AS already_returned_qty,
                   COALESCE((SELECT SUM(ri.total_item_amount) FROM return_items ri JOIN returns r ON ri.return_id = r.id WHERE ri.sale_item_id = si.id AND r.status != 'voided'), 0) AS already_returned_amt
            FROM sale_items si
            JOIN medicines m ON si.medicine_id = m.id
            JOIN batches b ON si.batch_id = b.id
            WHERE si.id IN ({placeholders}) AND si.sale_id = ?
        """, tuple(si_ids) + (sale_id,))

        db_truth = {row[0]: {
            'sold_qty': Decimal(str(row[1])),
            'total_price': Decimal(str(row[2])),
            'med_name': row[3],
            'batch_id': row[4],
            'batch_number': row[5],
            'med_id': row[6],
            'is_ctrl': row[7],
            'ctrl_class': row[8],
            'rx_id': row[9],
            'ret_qty': Decimal(str(row[10])),
            'ret_amt': Decimal(str(row[11]))
        } for row in cursor.fetchall()}

        total_refund = D_0

        # 3. الحساب المالي العكسي الصارم (Pro-Rata Refund Rule)
        for si_id, req_qty_val in aggregated_request.items():
            req_qty = Decimal(str(req_qty_val))
            truth = db_truth.get(si_id)

            if not truth:
                result["invalid_lines"].append({"sale_item_id": si_id, "reason": "السطر غير موجود أو لا يتبع لهذه الفاتورة."})
                continue

            allowed_qty = truth['sold_qty'] - truth['ret_qty']
            if req_qty > allowed_qty:
                result["invalid_lines"].append({"sale_item_id": si_id, "reason": f"الكمية المطلوبة ({req_qty}) تتجاوز المتاح للإرجاع ({allowed_qty})."})
                continue

            # [Architectural Fix 4]: توحيد التقريب (Quantization) لكل المسارات المالية بدقة D_2
            if req_qty == allowed_qty:
                # إرجاع كلي للمتبقي (التقاط كسور متراكمة)
                line_refund = (truth['total_price'] - truth['ret_amt']).quantize(D_2, rounding=ROUND_HALF_UP)
            else:
                # إرجاع جزئي تناسبي
                unit_refund = truth['total_price'] / truth['sold_qty']
                line_refund = (unit_refund * req_qty).quantize(D_2, rounding=ROUND_HALF_UP)

            total_refund += line_refund

            if truth['is_ctrl'] == 1:
                result["has_controlled"] = True

            # حقل توثيقي فقط للواجهة وقاعدة البيانات
            doc_price = (line_refund / req_qty).quantize(D_4, rounding=ROUND_HALF_UP)

            result["eligible_lines"].append({
                "sale_item_id": si_id,
                "medicine_id": truth['med_id'],
                "batch_id": truth['batch_id'],
                "medicine_name": truth['med_name'],
                "batch_number": truth['batch_number'],
                "return_qty": int(req_qty),
                "max_returnable_qty": int(allowed_qty),
                "sold_qty": int(truth['sold_qty']),
                "already_returned_qty": int(truth['ret_qty']),
                "historical_line_total": float(truth['total_price']),
                "refund_amount": float(line_refund),
                "documented_unit_refund": float(doc_price),
                "is_controlled": truth['is_ctrl'],
                "ctrl_class": truth['ctrl_class'],
                "prescription_item_id": truth['rx_id']
            })

        result["total_refund_amount"] = float(total_refund)
        return result

    def quote_return(self, sale_id, return_lines):
        """
        واجهة استهلاك المحرك السعري لأغراض العرض فقط (Diagnostic UI Contract).
        [Architectural Fix 1]: ثبات العقد (Dictionary Structure) حتى في حالة الفشل.
        """
        default_result = {
            "general_error": "فشل الاتصال بقاعدة البيانات.",
            "eligible_lines": [],
            "invalid_lines": [],
            "total_refund_amount": 0.0,
            "has_controlled": False
        }

        conn = self.db.connect()
        if not conn:
            return default_result

        try:
            cursor = conn.cursor()
            eval_result = self._evaluate_return_request(cursor, sale_id, return_lines)

            # التأكد من عدم وجود أخطاء صامتة تسقط الحقول الأساسية
            default_result.update(eval_result)
            default_result["general_error"] = None
            return default_result

        except Exception as e:
            logger.exception("Quote Return Error:")
            default_result["general_error"] = "خطأ داخلي أثناء حساب المرتجع."
            return default_result
        finally:
            if conn: conn.close()

    # ==========================================
    # 3. التنفيذ السيادي للمرتجعات (Write / Execution)
    # ==========================================
    def process_return(self, sale_id, user_id, shift_id, items_to_return, reason=""):
        """
        القلعة السيادية للمرتجع. تعتمد على المحرك الموحد (_evaluate_return_request) وتنفذ الالتزام المالي.
        """
        if not user_id: return False, "تعذر تحديد المستخدم لإتمام المرتجع."
        if not items_to_return: return False, "لا توجد أصناف محددة للإرجاع."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()

            # ==========================================
            # 🛡️ THE IRON WALL GUARD (حارس الوردية الصارم)
            # ==========================================
            if not shift_id:
                raise ValueError("اختراق أمني: لا يمكن تنفيذ مرتجع مالي بدون رقم وردية (shift_id).")

            cursor.execute("SELECT status, user_id FROM shifts WHERE id = ?", (shift_id,))
            shift_row = cursor.fetchone()

            if not shift_row:
                raise ValueError("الوردية المحددة غير موجودة في النظام.")

            if shift_row[0] != 'open':
                raise ValueError("رفض سيادي: الوردية المحددة (مغلقة). يُمنع سحب أي نقدية للمرتجعات منها.")

            if shift_row[1] != user_id:
                raise ValueError("الوردية المفتوحة المحددة لا تخص المستخدم الحالي. المسؤولية النقدية فردية ولا يمكن الإرجاع من درج موظف آخر.")
            # ==========================================

            # 1. RBAC
            cursor.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            if not user_row or user_row[1] != 1:
                raise ValueError("المستخدم غير موجود أو غير نشط.")

            user_role = user_row[0]
            if user_role not in ['admin', 'pharmacist', 'cashier']:
                raise ValueError("صلاحيات غير كافية لتنفيذ المرتجعات.")

            # 2. الفاتورة الأصلية وحمايتها
            cursor.execute("SELECT total_amount, customer_id FROM sales WHERE id = ?", (sale_id,))
            sale_row = cursor.fetchone()
            if not sale_row: raise ValueError("فاتورة البيع الأصلية غير موجودة.")
            historical_sale_total = Decimal(str(sale_row[0]))
            sale_customer_id = sale_row[1]

            # 3. استدعاء المحرك الموحد
            engine_result = self._evaluate_return_request(cursor, sale_id, items_to_return)

            if engine_result.get("invalid_lines"):
                invalid_reasons = " | ".join([f"السطر {i['sale_item_id']}: {i['reason']}" for i in engine_result["invalid_lines"]])
                raise ValueError(f"يوجد سطور مرفوضة: {invalid_reasons}")

            validated_items = engine_result["eligible_lines"]
            if not validated_items:
                raise ValueError("لا توجد سطور صالحة للاعتماد.")

            total_return_amount = Decimal(str(engine_result["total_refund_amount"]))
            has_controlled_return = engine_result["has_controlled"]

            # 4. الرقابة الأمنية (RBAC Control)
            if has_controlled_return and user_role not in ['admin', 'pharmacist']:
                raise ValueError("إرجاع الأدوية الرقابية مقتصر حصراً على 'المدير' أو 'الصيدلي'.")

            # 5. Safety Net: منع تجاوز الإجمالي
            cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM returns WHERE sale_id = ? AND status != 'voided'", (sale_id,))
            previous_returns_total = Decimal(str(cursor.fetchone()[0]))
            if (previous_returns_total + total_return_amount) > historical_sale_total:
                raise ValueError("تضارب مالي: إجمالي المبالغ المستردة سيتجاوز قيمة الفاتورة الأصلية.")

            now_dt = datetime.now()
            return_date = now_dt.strftime("%Y-%m-%d %H:%M:%S")

            # 6. الحفظ في قاعدة البيانات
            cursor.execute("""
                INSERT INTO returns (sale_id, user_id, shift_id, return_date, total_amount, reason, status)
                VALUES (?, ?, ?, ?, ?, ?, 'completed')
            """, (sale_id, user_id, shift_id, return_date, float(total_return_amount), reason))
            return_id = cursor.lastrowid

            for v_item in validated_items:
                cursor.execute("""
                    INSERT INTO return_items (return_id, sale_item_id, medicine_id, batch_id, quantity, documented_unit_refund, total_item_amount, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (return_id, v_item['sale_item_id'], v_item['medicine_id'], v_item['batch_id'],
                      v_item['return_qty'], v_item['documented_unit_refund'], v_item['refund_amount'], reason))
                ret_item_id = cursor.lastrowid

                # الرد المخزني الحتمي
                cursor.execute("SELECT quantity, status FROM batches WHERE id = ?", (v_item['batch_id'],))
                current_batch_qty, current_status = cursor.fetchone()
                new_batch_qty = current_batch_qty + v_item['return_qty']
                new_status = 'active' if current_status == 'depleted' and new_batch_qty > 0 else current_status

                cursor.execute("UPDATE batches SET quantity = ?, status = ? WHERE id = ?", (new_batch_qty, new_status, v_item['batch_id']))
                cursor.execute("UPDATE medicines SET quantity = quantity + ? WHERE id = ?", (v_item['return_qty'], v_item['medicine_id']))

                # التسجيل الرقابي الإلزامي
                if v_item['is_controlled'] == 1:
                    cursor.execute("""
                        INSERT INTO controlled_return_log (return_id, return_item_id, sale_item_id, medicine_id, batch_id, customer_id, user_id, returned_qty, controlled_class, notes, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')
                    """, (return_id, ret_item_id, v_item['sale_item_id'], v_item['medicine_id'], v_item['batch_id'], sale_customer_id, user_id, v_item['return_qty'], v_item['ctrl_class'], reason))

            # 7. التوثيق المالي والرقابي
            trans_notes = f"مرتجع مبيعات للفاتورة {sale_id} - رقم المرتجع {return_id}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                VALUES ('out', 'return', ?, ?, ?, ?, ?)
            """, (return_id, float(total_return_amount), user_id, shift_id, trans_notes))

            audit_info = {
                "original_sale_id": sale_id,
                "total_refunded": float(total_return_amount),
                "items_count": len(validated_items),
                "has_controlled": has_controlled_return
            }
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'returns', ?, ?)
            """, (user_id, return_id, json.dumps(audit_info, ensure_ascii=False)))

            # تسوية الوصفات العكسية
            from models.prescriptions_dao import PrescriptionsDAO
            PrescriptionsDAO().reconcile_return(cursor, return_id)

            conn.commit()
            return True, {
                "return_id": return_id,
                "total_return_amount": float(total_return_amount),
                "returned_lines_count": len(validated_items)
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("انهيار أثناء تنفيذ المرتجع:")
            return False, "خطأ داخلي في اعتماد المرتجع. تم إلغاء العملية لحماية البيانات."
        finally:
            conn.close()

    # ==========================================
    # 3. إبطال المرتجعات (Immutability & Voiding)
    # ==========================================
    def void_return(self, requester_id, shift_id, return_id, void_reason=""):
        """
        [Admin Immutability Guard]: لا يوجد حذف. الإلغاء يعكس المخزون والتسويات، ويعدل الحالة لـ (voided).
        ويوثق الإبطال الرقابي في controlled_return_log بشكل آمن ضد الـ NULL.
        """
        if not requester_id or not return_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # ==========================================
            # 🛡️ THE IRON WALL GUARD (حارس وردية المدير الصارم)
            # ==========================================
            if not shift_id:
                raise ValueError("اختراق أمني: يجب أن تكون لديك وردية مفتوحة لتتمكن من إبطال المرتجع (لأن الإبطال سيولد قيداً وارداً في صندوقك).")

            cursor.execute("SELECT status, user_id FROM shifts WHERE id = ?", (shift_id,))
            shift_row = cursor.fetchone()

            if not shift_row:
                raise ValueError("الوردية المحددة غير موجودة في النظام.")

            if shift_row[0] != 'open':
                raise ValueError("رفض سيادي: ورديتك الحالية مغلقة أو غير صالحة. لا يمكن تسوية الإبطال النقدي.")

            if shift_row[1] != requester_id:
                raise ValueError("الوردية لا تخص المدير الحالي الذي يقوم بعملية الإبطال.")
            # ==========================================

            # 1. RBAC: Admin Only
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            user_role = cursor.fetchone()
            if not user_role or user_role[0] != 'admin':
                breach_payload = json.dumps({"SECURITY_BREACH": f"Unauthorized void attempt for return: {return_id}"})
                cursor.execute("INSERT INTO audit_logs (user_id, action, table_name, old_values) VALUES (?, 'UPDATE', 'returns', ?)", (requester_id, breach_payload))
                conn.commit()
                raise ValueError("صلاحيات غير كافية. إبطال المرتجعات يتطلب صلاحية 'مدير النظام'.")

            cursor.execute("SELECT total_amount, sale_id, status, shift_id FROM returns WHERE id = ?", (return_id,))
            ret_data = cursor.fetchone()
            if not ret_data: raise ValueError("المرتجع المحدد غير موجود.")

            total_refunded, sale_id, current_status, orig_shift_id = ret_data
            if current_status == 'voided':
                raise ValueError("هذا المرتجع مُبطل مسبقاً.")
            # ==========================================
            # 👇👇 ضَع الحارس هنا بالضبط 👇👇
            # ==========================================
            # 🛡️ THE DAILY CLOSURE GUARD (حارس الإقفال اليومي)
            cursor.execute("""
                        SELECT dc.business_date 
                        FROM daily_closure_shifts dcs
                        JOIN daily_closures dc ON dcs.daily_closure_id = dc.id
                        WHERE dcs.shift_id = ?
                    """, (orig_shift_id,))
            closure_row = cursor.fetchone()

            if closure_row:
                raise ValueError(
                    f"رفض سيادي: الوردية الأصلية لهذه الحركة أُقفلت وتم ترحيلها محاسبياً "
                    f"ضمن الإقفال اليومي لتاريخ ({closure_row[0]}). يُمنع التعديل أو الإبطال."
                )
            # ==========================================
            # 👆👆 نهاية الحارس 👆👆
            # 3. عكس المخزون (استقطاع ما تم إرجاعه)
            cursor.execute("SELECT medicine_id, batch_id, quantity FROM return_items WHERE return_id = ?", (return_id,))
            items_to_reverse = cursor.fetchall()

            for m_id, b_id, qty in items_to_reverse:
                cursor.execute("""
                    UPDATE batches SET quantity = quantity - ? WHERE id = ? AND quantity >= ?
                """, (qty, b_id, qty))

                if cursor.rowcount == 0:
                    raise ValueError(f"لا يمكن إبطال المرتجع. الرصيد الحالي للتشغيلة (ID: {b_id}) غير كافٍ لاستقطاع الكمية ({qty}) التي رُدت سابقاً. (يُحتمل أنه تم بيعها مجدداً).")

                cursor.execute("SELECT quantity FROM batches WHERE id = ?", (b_id,))
                new_qty = cursor.fetchone()[0]
                if new_qty == 0:
                    cursor.execute("UPDATE batches SET status = 'depleted' WHERE id = ?", (b_id,))

                cursor.execute("UPDATE medicines SET quantity = quantity - ? WHERE id = ?", (qty, m_id))

            # 4. تحديث الحالة إلى مبطل (Immutability)
            cursor.execute("UPDATE returns SET status = 'voided' WHERE id = ?", (return_id,))

            # 5. [Architectural Fix 2]: حماية الـ NULL (Reverse Legal Audit)
            cursor.execute("""
                UPDATE controlled_return_log 
                SET status = 'voided', 
                    notes = COALESCE(notes, '') || ? 
                WHERE return_id = ?
            """, (f" [تم الإبطال: {void_reason}]", return_id))

            # 6. التسوية العكسية للوصفات
            from models.prescriptions_dao import PrescriptionsDAO
            PrescriptionsDAO().reconcile_return_reversal(cursor, return_id)

            # 7. القيد المالي العكسي للتسوية النقدية (يتم في الوردية الحالية للمدير shift_id)
            trans_notes = f"قيد عكسي: إبطال مرتجع رقم {return_id} للفاتورة {sale_id} | المبرر: {void_reason}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                VALUES ('in', 'return_void', ?, ?, ?, ?, ?)
            """, (return_id, total_refunded, requester_id, shift_id, trans_notes))

            audit_payload = json.dumps({"voided_return_id": return_id, "amount_reversed": float(total_refunded), "sale_id": sale_id, "reason": void_reason})
            cursor.execute("INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values) VALUES (?, 'UPDATE', 'returns', ?, ?)", (requester_id, return_id, audit_payload))

            conn.commit()
            return True, f"تم إبطال المرتجع بنجاح وإصدار قيد مالي عكسي لتسوية الصندوق."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("خطأ داخلي أثناء إبطال المرتجع:")
            return False, "فشل داخلي. تم التراجع عن العملية لحماية البيانات."
        finally:
            conn.close()

    def get_all_returns(self, start_date=None, end_date=None):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT r.id, r.sale_id, u.username, r.return_date, r.total_amount, r.reason, r.status
                FROM returns r
                JOIN users u ON r.user_id = u.id
            """
            params = []
            if start_date and end_date:
                query += " WHERE date(r.return_date) BETWEEN date(?) AND date(?)"
                params.extend([start_date, end_date])

            query += " ORDER BY r.return_date DESC"
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            conn.close()