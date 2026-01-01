from database.db_manager import DatabaseManager
from datetime import datetime


class SalesDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def get_medicine_by_barcode_or_name(self, text):
        """
        البحث عن دواء لإضافته للسلة.
        يعيد الكمية الإجمالية المتوفرة في كل التشغيلات.
        """
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            # البحث يعيد الكمية الإجمالية من جدول batches أو medicines (حسب التصميم، هنا نعتمد على medicines المحدث)
            query = """SELECT id, name, sell_price, quantity, barcode 
                       FROM medicines 
                       WHERE (barcode = ? OR name LIKE ?) AND quantity > 0 LIMIT 1"""
            cursor.execute(query, (text, f"%{text}%"))
            data = cursor.fetchone()
            conn.close()
            return data
        return None

    def process_sale(self, user_id, cart_items, total_amount, customer_id=None, doctor_name=""):
        """
        تنفيذ عملية البيع بنظام التشغيلات (FIFO):
        1. إنشاء فاتورة.
        2. لكل دواء: نجلب التشغيلات المرتبة حسب تاريخ الانتهاء.
        3. نخصم الكمية من التشغيلات الأقدم فالأجدد.
        4. نسجل تفاصيل البيع مع رقم التشغيلة (batch_id).
        """
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()
            sale_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 1. إنشاء سجل الفاتورة (Header)
            query_sale = """INSERT INTO sales (user_id, customer_id, doctor_name, total_amount, sale_date) 
                            VALUES (?, ?, ?, ?, ?)"""
            cursor.execute(query_sale, (user_id, customer_id, doctor_name, total_amount, sale_date))
            sale_id = cursor.lastrowid

            # 2. معالجة الأصناف (Items)
            for item in cart_items:
                med_id = item['id']
                qty_needed = item['qty']  # الكمية المطلوبة من الزبون
                sell_price = item['price']

                # جلب تشغيلات هذا الدواء مرتبة حسب الأقدم (FIFO) والتي بها كمية > 0
                cursor.execute("""
                    SELECT id, quantity FROM batches 
                    WHERE medicine_id = ? AND quantity > 0 
                    ORDER BY expiry_date ASC
                """, (med_id,))

                available_batches = cursor.fetchall()

                qty_remaining_to_sell = qty_needed

                # المرور على التشغيلات وسحب الكمية
                for batch in available_batches:
                    if qty_remaining_to_sell <= 0:
                        break

                    batch_id = batch[0]
                    batch_qty = batch[1]

                    # تحديد الكمية التي ستؤخذ من هذه التشغيلة
                    take_qty = min(qty_remaining_to_sell, batch_qty)

                    # حساب إجمالي السعر لهذا الجزء
                    line_total = take_qty * sell_price

                    # أ. تسجيل هذا الجزء في sale_items مع batch_id
                    cursor.execute("""
                        INSERT INTO sale_items (sale_id, medicine_id, batch_id, quantity, price_at_sale, total_item_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (sale_id, med_id, batch_id, take_qty, sell_price, line_total))

                    # ب. إنقاص الكمية من جدول التشغيلات (batches)
                    cursor.execute("UPDATE batches SET quantity = quantity - ? WHERE id = ?", (take_qty, batch_id))

                    # ج. إنقاص الكمية الإجمالية من جدول الأدوية (medicines) لتبقى الأرقام متطابقة
                    cursor.execute("UPDATE medicines SET quantity = quantity - ? WHERE id = ?", (take_qty, med_id))

                    qty_remaining_to_sell -= take_qty

                # التحقق: هل تم تلبية كامل الكمية المطلوبة؟
                if qty_remaining_to_sell > 0:
                    raise Exception(f"الكمية المتوفرة في التشغيلات للدواء رقم {med_id} غير كافية!")

            conn.commit()
            # نعيد sale_id لنستخدمه في الطباعة
            return True, sale_id

        except Exception as e:
            conn.rollback()
            return False, f"خطأ أثناء البيع: {e}"
        finally:
            conn.close()