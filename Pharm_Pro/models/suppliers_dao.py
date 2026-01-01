from database.db_manager import DatabaseManager


class SuppliersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def add_supplier(self, name, phone, company, balance=0.0):
        """إضافة مورد جديد"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO suppliers (name, phone, company_name, balance) VALUES (?, ?, ?, ?)",
                               (name, phone, company, balance))
                conn.commit()
                return True, "تمت إضافة المورد بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "تعذر الاتصال بقاعدة البيانات"

    def get_all_suppliers(self):
        """جلب جميع الموردين"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, phone, company_name, balance FROM suppliers")
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def delete_supplier(self, supplier_id):
        """حذف مورد"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # التحقق أولاً هل للمورد أدوية مرتبطة به؟ (اختياري، لسلامة البيانات)
                cursor.execute("SELECT COUNT(*) FROM medicines WHERE supplier_id = ?", (supplier_id,))
                if cursor.fetchone()[0] > 0:
                    return False, "لا يمكن حذف المورد لوجود أدوية مرتبطة به في المخزون."

                cursor.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
                conn.commit()
                return True, "تم الحذف بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "فشل الاتصال"

    def search_supplier(self, text):
        """البحث عن مورد بالاسم أو الشركة"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """SELECT id, name, phone, company_name, balance 
                       FROM suppliers 
                       WHERE name LIKE ? OR company_name LIKE ?"""
            search_term = f"%{text}%"
            cursor.execute(query, (search_term, search_term))
            data = cursor.fetchall()
            conn.close()
            return data
        return []