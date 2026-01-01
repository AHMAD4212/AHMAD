import sqlite3
import hashlib

class DatabaseManager:
    _instance = None  # نمط Singleton لمنع تكرار الاتصال والانهيار

    def __new__(cls, db_name="pharma_system.db"):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance.db_name = db_name
            cls._instance.conn = None
            # الاستدعاء مرة واحدة فقط عند بداية تشغيل التطبيق
            cls._instance.create_tables()
        return cls._instance

    def connect(self):
        """إنشاء اتصال بقاعدة البيانات"""
        try:
            self.conn = sqlite3.connect(self.db_name)
            # تفعيل دعم المفاتيح الأجنبية (Foreign Keys) لضمان ترابط البيانات
            self.conn.execute("PRAGMA foreign_keys = ON")
            return self.conn
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            return None

    def create_tables(self):
        """إنشاء الهيكلية الكاملة لقاعدة البيانات (شاملة نظام التشغيلات - Batches)"""

        # قائمة الجداول كاملة ومرتبة حسب الاعتمادية
        queries = [
            # 1. جدول المستخدمين (الصيادلة والمدير)
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'pharmacist',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",

            # 2. جدول الموردين
            """CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                company_name TEXT,
                balance REAL DEFAULT 0.0
            )""",

            # 3. جدول العملاء
            """CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",

            # 4. جدول الأدوية (البيانات الأساسية فقط)
            """CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                active_ingredient TEXT,       
                description TEXT,
                -- هذه الحقول ستبقى كقيم مرجعية أو افتراضية، لكن المخزون الفعلي في Batches
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                quantity INTEGER DEFAULT 0,
                expiry_date DATE,
                supplier_id INTEGER,
                min_stock_alert INTEGER DEFAULT 10,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )""",

            # 5. جدول التشغيلات (Batches) - (الجدول الجديد لنظام تعدد الأسعار والتواريخ)
            """CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medicine_id INTEGER NOT NULL,
                batch_number TEXT,          -- رقم التشغيلة
                expiry_date DATE NOT NULL,  -- تاريخ الانتهاء الخاص بهذه الدفعة
                buy_price REAL NOT NULL,    -- سعر الشراء لهذه الدفعة
                sell_price REAL NOT NULL,   -- سعر البيع لهذه الدفعة
                quantity INTEGER NOT NULL,  -- الكمية المتبقية في هذه الدفعة
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
            )""",

            # 6. جدول المبيعات (الرأس)
            """CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                customer_id INTEGER,          
                doctor_name TEXT,             
                total_amount REAL,
                sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )""",

            # 7. جدول تفاصيل المبيعات (الأصناف) - (تم تحديثه ليرتبط بالتشغيلة)
            """CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER,
                medicine_id INTEGER,
                batch_id INTEGER,             -- هام: لتحديد من أي تشغيلة تم البيع
                quantity INTEGER,
                price_at_sale REAL,
                total_item_price REAL,
                FOREIGN KEY(sale_id) REFERENCES sales(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                FOREIGN KEY(batch_id) REFERENCES batches(id)
            )""",

            # 8. جدول فواتير الشراء (الرأس)
            """CREATE TABLE IF NOT EXISTS purchase_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER,
                invoice_number TEXT,
                invoice_date DATE,
                total_amount REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )""",

            # 9. جدول تفاصيل الشراء (الأصناف)
            """CREATE TABLE IF NOT EXISTS purchase_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER,
                medicine_id INTEGER,
                quantity INTEGER,
                unit_cost REAL,
                total_cost REAL,
                FOREIGN KEY(purchase_id) REFERENCES purchase_invoices(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id)
            )"""
        ]

        try:
            conn = self.connect()
            cursor = conn.cursor()

            # تنفيذ إنشاء جميع الجداول
            for query in queries:
                cursor.execute(query)

            # إنشاء المستخدم المسؤول (Admin) افتراضياً إذا لم يكن موجوداً
            cursor.execute("SELECT * FROM users WHERE username = 'admin'")
            if not cursor.fetchone():
                admin_pass = hashlib.sha256("123456".encode()).hexdigest()
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                               ('admin', admin_pass, 'admin'))
                print("✅ تم إنشاء حساب المدير الافتراضي (admin/123456)")

            conn.commit()
            print("✅ تم بناء قاعدة البيانات وهيكلية الجداول الكاملة (شاملة Batches) بنجاح.")

        except sqlite3.Error as e:
            print(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
        finally:
            if conn:
                conn.close()

# عند تشغيل الملف مباشرة للتجربة
if __name__ == "__main__":
    DatabaseManager()