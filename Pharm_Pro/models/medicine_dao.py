from database.db_manager import DatabaseManager
import sqlite3


class MedicineDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def add_medicine(self, barcode, name, active_ingredient, buy_price, sell_price, quantity, expiry, supplier_id=None):
        """
        إضافة دواء جديد:
        تقوم هذه الدالة بإنشاء سجل للدواء، وإنشاء 'تشغيلة افتتاحية' بالكمية والسعر المدخلين.
        """
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # 1. إدراج الدواء في الجدول الرئيسي (medicines)
                query_med = """INSERT INTO medicines 
                           (barcode, name, active_ingredient, buy_price, sell_price, quantity, expiry_date, supplier_id) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
                cursor.execute(query_med,
                               (barcode, name, active_ingredient, buy_price, sell_price, quantity, expiry, supplier_id))

                # الحصول على معرف الدواء الجديد (Medicine ID)
                medicine_id = cursor.lastrowid

                # 2. إدراج بيانات الكمية والسعر في جدول التشغيلات (batches)
                # نعتبر هذه الدفعة هي 'رصيد افتتاحي' (OPENING_STOCK)
                query_batch = """INSERT INTO batches 
                                 (medicine_id, batch_number, expiry_date, buy_price, sell_price, quantity) 
                                 VALUES (?, ?, ?, ?, ?, ?)"""
                cursor.execute(query_batch, (medicine_id, "OPENING_STOCK", expiry, buy_price, sell_price, quantity))

                conn.commit()
                return True, "تمت إضافة الدواء والتشغيلة الافتتاحية بنجاح"

            except sqlite3.IntegrityError:
                return False, "الباركود موجود مسبقاً! يرجى التحقق من البيانات."
            except Exception as e:
                conn.rollback()  # التراجع عن التغييرات في حال حدوث أي خطأ
                return False, f"خطأ غير متوقع: {e}"
            finally:
                conn.close()
        return False, "تعذر الاتصال بقاعدة البيانات"

    def get_all_medicines(self):
        """جلب جميع الأدوية"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, barcode, name, active_ingredient, buy_price, sell_price, quantity, expiry_date FROM medicines ORDER BY id DESC")
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def delete_medicine(self, medicine_id):
        """حذف دواء (مع حماية وإرجاع كود خطأ خاص إذا كان مرتبطاً بمبيعات)"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # محاولة الحذف
                cursor.execute("DELETE FROM medicines WHERE id = ?", (medicine_id,))
                conn.commit()
                return True, "تم حذف الدواء وسجلاته بنجاح"
            except sqlite3.Error as e:
                # التحقق مما إذا كان الخطأ بسبب ارتباط الدواء بمبيعات أو مشتريات سابقة
                if "FOREIGN KEY" in str(e):
                    # نرجع كود خاص لنتعامل معه في الواجهة
                    return False, "FOREIGN_KEY_ERROR"
                return False, f"خطأ في قاعدة البيانات: {e}"
            finally:
                conn.close()
        return False, "فشل الاتصال"

    def clear_medicine_stock(self, medicine_id):
        """تصفير كمية الدواء في المخزون الرئيسي وفي جميع التشغيلات"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # 1. تصفير كل التشغيلات لهذا الدواء
                cursor.execute("UPDATE batches SET quantity = 0 WHERE medicine_id = ?", (medicine_id,))

                # 2. تصفير المخزون الكلي للدواء
                cursor.execute("UPDATE medicines SET quantity = 0 WHERE id = ?", (medicine_id,))

                conn.commit()
                return True, "تم تصفير كمية الدواء بنجاح (أصبح خارج المخزون)"
            except Exception as e:
                conn.rollback()
                return False, f"خطأ أثناء التصفير: {e}"
            finally:
                conn.close()
        return False, "فشل الاتصال"

    def search_medicine(self, text):
        """بحث ذكي يشمل الاسم، الباركود، والمادة الفعالة"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """SELECT id, barcode, name, active_ingredient, buy_price, sell_price, quantity, expiry_date 
                       FROM medicines 
                       WHERE name LIKE ? OR barcode LIKE ? OR active_ingredient LIKE ?"""
            search_term = f"%{text}%"
            cursor.execute(query, (search_term, search_term, search_term))
            data = cursor.fetchall()
            conn.close()
            return data
        return []