"""
وظيفة الملف: كائن الوصول لبيانات المشتريات (Purchases DAO).
الطبقة: Data Access Layer / Execution Workflow
ملاحظة معمارية وأمنية:
- [Strict Accrual/Cash Hybrid Core]: معالجة المشتريات (نقدية، آجلة، مختلطة) بشكل محاسبي دقيق.
- [Shift & Cash Guard]: يمنع سحب أي مبلغ نقدي دون وجود وردية مفتوحة تخص المستخدم الحالي.
- [Security Fix]: تسجيل محاولة الاختراق باتصال منفصل لضمان عدم ضياعه مع التراجع (Rollback).
- [Data Integrity]: حظر تمرير po_item_id إذا لم تكن الفاتورة مرتبطة بـ PO، وتطابق الأصناف إلزامياً.
"""

from database.db_manager import DatabaseManager
import json
import logging

logger = logging.getLogger(__name__)

class PurchasesDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _log_security_breach(self, user_id, invoice_number):
        """[إصلاح 1]: تسجيل الاختراق عبر اتصال مستقل لضمان النجاة من Rollback الفاتورة"""
        conn = self.db.connect()
        if conn:
            try:
                cursor = conn.cursor()
                breach = json.dumps({"SECURITY_BREACH": "Unauthorized Purchase Invoice Attempt", "invoice": invoice_number}, ensure_ascii=False)
                cursor.execute("""
                    INSERT INTO audit_logs (user_id, action, table_name, old_values)
                    VALUES (?, 'INSERT', 'purchase_invoices', ?)
                """, (user_id, breach))
                conn.commit()
            except Exception as e:
                logger.error(f"فشل تسجيل خرق أمني: {e}")
            finally:
                conn.close()

    def add_purchase_invoice(self, supplier_id, invoice_number, invoice_date, total_amount, items, user_id, notes="", purchase_order_id=None, paid_amount=0.0, shift_id=None):
        """
        [The Core Fix]: تسجيل الفاتورة وتوجيهها محاسبياً بشكل سيادي (نقد / ذمم).
        """
        # ==========================================
        # 1. التحقق الحسابي والمنطقي (Contract Guards)
        # ==========================================
        if not user_id: return False, "تعذر تحديد المستخدم."
        if not items or len(items) == 0: return False, "الفاتورة فارغة."
        if total_amount <= 0: return False, "إجمالي الفاتورة يجب أن يكون أكبر من الصفر."

        if paid_amount < 0 or paid_amount > total_amount:
            return False, "المبلغ المدفوع نقدًا يجب أن يكون رقماً منطقياً (أكبر من أو يساوي صفر ولا يتجاوز إجمالي الفاتورة)."

        unpaid_amount = total_amount - paid_amount

        # تحديد الحالة المحاسبية للفاتورة
        if paid_amount == total_amount:
            payment_status = 'paid'
        elif paid_amount > 0:
            payment_status = 'partial'
        else:
            payment_status = 'unpaid'

        # فتح اتصال الفاتورة الأساسي
        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()

            # ==========================================
            # 2. حارس الصلاحيات (RBAC) وحارس الوردية
            # ==========================================
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()

            if not user_row or user_row[0] != 'admin':
                self._log_security_breach(user_id, invoice_number)
                raise ValueError("تسجيل المشتريات يتطلب صلاحية 'مدير النظام'.")

            # [حارس النقد]: لا يتم التحقق من الوردية إلا إذا كان هناك دفع نقدي
            if paid_amount > 0:
                if not shift_id:
                    raise ValueError("رفض محاسبي: لا يمكن تسجيل دفعة نقدية (شراء نقدي) بدون تحديد وردية مالية (shift_id).")

                cursor.execute("SELECT status, user_id FROM shifts WHERE id = ?", (shift_id,))
                shift_row = cursor.fetchone()

                if not shift_row:
                    raise ValueError("الوردية المالية المحددة غير موجودة في النظام.")
                if shift_row[0] != 'open':
                    raise ValueError("رفض سيادي: الوردية المالية مغلقة. لا يمكن سحب نقدية منها.")
                if shift_row[1] != user_id:
                    raise ValueError("الوردية المالية لا تخص المستخدم الحالي. المسؤولية النقدية فردية.")

            # ==========================================
            # 3. معالجة ارتباط الفاتورة بأمر الشراء (PO Integration)
            # ==========================================
            po_items_map = {}
            if purchase_order_id:
                cursor.execute("SELECT status, supplier_id FROM purchase_orders WHERE id = ?", (purchase_order_id,))
                po_row = cursor.fetchone()

                if not po_row:
                    raise ValueError("أمر الشراء المحدد غير موجود في النظام.")
                if po_row[0] not in ['approved', 'partially_received']:
                    raise ValueError(f"لا يمكن الاستلام من أمر شراء بحالة '{po_row[0]}'.")
                if po_row[1] != supplier_id:
                    raise ValueError("المورد في الفاتورة لا يطابق المورد المحدد في أمر الشراء.")

                cursor.execute("""
                    SELECT poi.id, poi.medicine_id, poi.requested_qty,
                    COALESCE((SELECT SUM(quantity) FROM purchase_items WHERE purchase_order_item_id = poi.id), 0) as received_qty
                    FROM purchase_order_items poi
                    WHERE poi.purchase_order_id = ?
                """, (purchase_order_id,))

                for r in cursor.fetchall():
                    po_items_map[r[0]] = {
                        "medicine_id": r[1],
                        "remaining_qty": r[2] - r[3]
                    }

            # ==========================================
            # 4. إدراج الفاتورة بالهيكل المحاسبي الجديد
            # ==========================================
            cursor.execute("""
                INSERT INTO purchase_invoices (
                    supplier_id, invoice_number, invoice_date, total_amount, 
                    paid_amount, unpaid_amount, payment_status, shift_id, notes, purchase_order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (supplier_id, invoice_number, invoice_date, total_amount, paid_amount, unpaid_amount, payment_status, shift_id, notes, purchase_order_id))

            purchase_id = cursor.lastrowid
            calculated_total = 0.0

            # ==========================================
            # 5. إدراج البنود وتحديث المخزون (Medicines & Batches)
            # ==========================================
            for item in items:
                med_id = item.get('id')
                batch_number = item.get('batch')
                expiry_date = item.get('expiry')
                qty = item.get('qty')
                unit_cost = item.get('cost')
                sell_price = item.get('sell_price')
                po_item_id = item.get('po_item_id')

                if qty <= 0 or unit_cost < 0 or sell_price < 0:
                    raise ValueError(f"قيم غير صالحة للصنف ذو المعرف {med_id}.")

                if not purchase_order_id and po_item_id:
                    raise ValueError(f"لا يجوز تمرير معرف بند الطلب دون ربط الفاتورة بأمر شراء صريح.")

                if purchase_order_id:
                    if not po_item_id:
                        raise ValueError(f"كل بند في الفاتورة المرتبطة بطلب شراء يجب أن يملك معرف بند الطلب (po_item_id). الصنف: {med_id}")
                    if po_item_id not in po_items_map:
                        raise ValueError(f"بند الطلب (ID: {po_item_id}) لا ينتمي لأمر الشراء المعتمد.")
                    if po_items_map[po_item_id]["medicine_id"] != med_id:
                        raise ValueError(f"عدم تطابق: الدواء المستلم ({med_id}) لا يطابق الدواء المسجل في أمر الشراء ({po_items_map[po_item_id]['medicine_id']}).")
                    if qty > po_items_map[po_item_id]["remaining_qty"]:
                        raise ValueError(f"الكمية المستلمة ({qty}) للصنف ({med_id}) تتجاوز الكمية المتبقية ({po_items_map[po_item_id]['remaining_qty']}).")

                    po_items_map[po_item_id]["remaining_qty"] -= qty

                calculated_total += (qty * unit_cost)

                cursor.execute("""
                    INSERT INTO purchase_items (
                        purchase_id, medicine_id, batch_number, expiry_date, 
                        quantity, unit_cost, sell_price, total_cost, purchase_order_item_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (purchase_id, med_id, batch_number, expiry_date, qty, unit_cost, sell_price, (qty * unit_cost), po_item_id))

                cursor.execute("""
                    INSERT INTO batches (
                        medicine_id, batch_number, expiry_date, buy_price, sell_price, quantity, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active')
                """, (med_id, batch_number, expiry_date, unit_cost, sell_price, qty))

                cursor.execute("""
                    UPDATE medicines 
                    SET quantity = quantity + ?, buy_price = ?, sell_price = ? 
                    WHERE id = ?
                """, (qty, unit_cost, sell_price, med_id))

            if abs(calculated_total - total_amount) > 0.1:
                 raise ValueError("إجمالي الفاتورة غير متطابق مع مجموع الأصناف جبرياً.")

            # ==========================================
            # 6. التوجيه المحاسبي السيادي (The Core Accounting Fix)
            # ==========================================

            # (أ) الذمم الدائنة الآجلة (التأثير على رصيد المورد فقط للمتبقي)
            if unpaid_amount > 0:
                cursor.execute("UPDATE suppliers SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unpaid_amount, supplier_id))

            # (ب) الخروج النقدي الفعلي (التأثير على الصندوق/الوردية)
            if paid_amount > 0:
                trans_notes = f"دفعة نقدية لشراء فاتورة رقم {invoice_number} من المورد {supplier_id}"
                cursor.execute("""
                    INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes)
                    VALUES ('out', 'purchase', ?, ?, ?, ?, ?)
                """, (purchase_id, paid_amount, user_id, shift_id, trans_notes))

            # ==========================================
            # 7. تحديث حالة أمر الشراء (إن وجد)
            # ==========================================
            if purchase_order_id:
                cursor.execute("""
                    SELECT poi.requested_qty,
                           COALESCE((SELECT SUM(quantity) FROM purchase_items WHERE purchase_order_item_id = poi.id), 0) as received_qty
                    FROM purchase_order_items poi
                    WHERE poi.purchase_order_id = ?
                """, (purchase_order_id,))

                rows = cursor.fetchall()
                all_full = True
                any_received = False

                for req_qty, rec_qty in rows:
                    if rec_qty > 0: any_received = True
                    if rec_qty < req_qty: all_full = False

                new_status = 'approved'
                if all_full and len(rows) > 0:
                    new_status = 'received'
                elif any_received:
                    new_status = 'partially_received'

                cursor.execute("""
                    UPDATE purchase_orders
                    SET status = ?, received_at = CASE WHEN ? = 'received' THEN CURRENT_TIMESTAMP ELSE received_at END
                    WHERE id = ?
                """, (new_status, new_status, purchase_order_id))

            # ==========================================
            # 8. التوثيق الأمني
            # ==========================================
            new_val_json = json.dumps({
                "invoice_number": invoice_number,
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "payment_status": payment_status,
                "po_id": purchase_order_id
            }, ensure_ascii=False)

            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'INSERT', 'purchase_invoices', ?, '{}', ?)
            """, (user_id, purchase_id, new_val_json))

            conn.commit()
            logger.info(f"تم اعتماد الفاتورة {purchase_id} وتوجيهها محاسبياً بنجاح (مدفوع: {paid_amount}, ذمم: {unpaid_amount}). ارتباط بأمر شراء: {purchase_order_id}")
            return True, "تم حفظ الفاتورة وتوجيهها محاسبياً (نقد/ذمم) وبناء التشغيلات بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("خطأ داخلي حرج أثناء حفظ فاتورة المشتريات:")
            return False, "حدث خطأ داخلي أثناء الاعتماد. راجع سجل النظام."
        finally:
            conn.close()

    def get_all_purchases(self):
        """
        جلب الفواتير مع الحقول المحاسبية الجديدة.
        """
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            # استرداد الأعمدة القديمة بالإضافة للحقول المحاسبية الثلاثة الجديدة
            cursor.execute("""
                SELECT 
                    p.id, 
                    s.name, 
                    p.invoice_number, 
                    p.invoice_date, 
                    p.total_amount, 
                    p.paid_amount, 
                    p.unpaid_amount, 
                    p.payment_status, 
                    p.created_at
                FROM purchase_invoices p
                JOIN suppliers s ON p.supplier_id = s.id
                ORDER BY p.id DESC
            """)
            return cursor.fetchall()
        except Exception:
            logger.exception("خطأ أثناء جلب الفواتير:")
            return []
        finally:
            conn.close()