from database.db_manager import DatabaseManager


class PurchasesDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def add_purchase_invoice(self, supplier_id, invoice_number, invoice_date, total_amount, items, notes=""):
        """
        تسجيل فاتورة شراء جديدة وتحديث المخزون
        items: قائمة تحتوي على قواميس {med_id, quantity, cost}
        """
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()

            # 1. إدراج رأس الفاتورة
            cursor.execute("""
                INSERT INTO purchase_invoices (supplier_id, invoice_number, invoice_date, total_amount, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (supplier_id, invoice_number, invoice_date, total_amount, notes))

            purchase_id = cursor.lastrowid

            # 2. إدراج التفاصيل وتحديث المخزون
            for item in items:
                med_id = item['id']
                qty = item['qty']
                cost = item['cost']
                line_total = qty * cost

                # تسجيل العنصر في الفاتورة
                cursor.execute("""
                    INSERT INTO purchase_items (purchase_id, medicine_id, quantity, unit_cost, total_cost)
                    VALUES (?, ?, ?, ?, ?)
                """, (purchase_id, med_id, qty, cost, line_total))

                # تحديث المخزون (زيادة الكمية + تحديث سعر الشراء الأخير)
                cursor.execute("""
                    UPDATE medicines 
                    SET quantity = quantity + ?, buy_price = ? 
                    WHERE id = ?
                """, (qty, cost, med_id))

            # 3. تحديث رصيد المورد (إضافة قيمة الفاتورة للديون)
            cursor.execute("UPDATE suppliers SET balance = balance + ? WHERE id = ?", (total_amount, supplier_id))

            conn.commit()
            return True, "تم حفظ فاتورة الشراء وتحديث المخزون بنجاح"

        except Exception as e:
            conn.rollback()
            return False, f"خطأ أثناء الحفظ: {e}"
        finally:
            conn.close()