from database.db_manager import DatabaseManager

class CustomersDAO:
    def __init__(self):
        self.db = DatabaseManager()
        self.create_table()

    def create_table(self):
        """إنشاء جدول العملاء إذا لم يكن موجوداً"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()

    def add_customer(self, name, phone, email, notes):
        """إضافة عميل جديد"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO customers (name, phone, email, notes) VALUES (?, ?, ?, ?)",
                               (name, phone, email, notes))
                conn.commit()
                return True, "تمت إضافة العميل بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "تعذر الاتصال بقاعدة البيانات"

    def get_all_customers(self):
        """جلب جميع العملاء"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, phone, email, notes FROM customers ORDER BY id DESC")
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def delete_customer(self, customer_id):
        """حذف عميل"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
                conn.commit()
                return True, "تم الحذف بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "فشل الاتصال"

    def search_customer(self, text):
        """البحث عن عميل بالاسم أو الهاتف"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """SELECT id, name, phone, email, notes 
                       FROM customers 
                       WHERE name LIKE ? OR phone LIKE ?"""
            search_term = f"%{text}%"
            cursor.execute(query, (search_term, search_term))
            data = cursor.fetchall()
            conn.close()
            return data
        return []