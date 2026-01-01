from database.db_manager import DatabaseManager
import hashlib

class UsersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def get_all_users(self):
        """جلب جميع المستخدمين"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, role, created_at FROM users")
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def add_user(self, username, password, role):
        """إضافة مستخدم جديد مع تشفير كلمة المرور"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # 1. التحقق من عدم تكرار الاسم
                cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
                if cursor.fetchone():
                    return False, "اسم المستخدم موجود مسبقاً!"

                # 2. تشفير كلمة المرور (SHA256)
                hashed_pass = hashlib.sha256(password.encode()).hexdigest()

                # 3. الإضافة
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                               (username, hashed_pass, role))
                conn.commit()
                return True, "تم إضافة المستخدم بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "تعذر الاتصال بقاعدة البيانات"

    def delete_user(self, user_id):
        """حذف مستخدم"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # منع حذف المدير الرئيسي (admin) للحماية
                cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                if user and user[0] == 'admin':
                    return False, "لا يمكن حذف المدير الرئيسي للنظام!"

                cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
                return True, "تم الحذف بنجاح"
            except Exception as e:
                return False, f"خطأ: {e}"
            finally:
                conn.close()
        return False, "فشل الاتصال"