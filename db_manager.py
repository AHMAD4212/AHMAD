"""
وظيفة الملف: مدير قاعدة البيانات (Database Manager) ومحرك التهجير (Migration Engine).
الطبقة: Data Access / Infrastructure

- [SSOT Core Tables]&#58; دالة _create_core_tables تعكس المخطط النهائي (V27) للقواعد الجديدة.
- [Legacy-Safe Migrations]&#58; دالة _run_migrations تقوم بترقية القواعد القديمة فعلياً.
- [SQLite-Safe Migration]&#58; تم تصحيح الترقيات التي كانت تضيف أعمدة عبر ALTER TABLE
  بقيم افتراضية غير ثابتة مثل CURRENT_TIMESTAMP، لأن SQLite يرفض ذلك.
- [ترقية V20]&#58; توسيع قيود audit_logs لدعم (SIMULATE_REMINDER, DISPATCH_REMINDER).
- [ترقية V21]&#58; إضافة (days_supply_at_sale) لجدول sale_items لضمان اللقطة التاريخية للمتطلب 29.
- [ترقية V22]&#58; إضافة الحقول المحاسبية السيادية لجدول purchase_invoices (المتطلب 10 و 21).
- [ترقية V23]&#58; إضافة حقول Lockout للحماية من هجمات Brute-Force (failed_login_attempts و locked_until).
- [ترقية V24]&#58; توسيع جدول العملاء/المرضى بإضافة
  (national_id, date_of_birth, gender, address, medical_notes, is_active, updated_at)
  مع فرض التفرد على (phone, email, national_id) عبر Unique Partial Indexes بعد تطبيع البيانات القديمة.
- [ترقية V25]&#58; توسيع جدول الموردين/الشركات بإضافة
  (email, address, notes, is_active, created_at)
  مع فرض سياسات تفرد أكثر نضجاً:
  1) عدم اعتبار الهاتف مفتاحاً فريداً منفرداً.
  2) فرض uniqueness على هوية المورد الفعالة (name + company_name) فقط.
  3) فرض uniqueness على البريد الإلكتروني إذا وُجد.
  4) تسوية التكرارات القديمة عبر أرشفة السجلات المكررة كغير فعالة بدلاً من كسر الإقلاع.
- [ترقية V26]&#58; إعادة بناء جدول التداخلات الدوائية (drug_interactions) ليصبح صالحاً للمتطلب 16
  عبر إضافة:
  (clinical_effect, recommendation, management_plan, source_reference, is_active,
   updated_by_user_id, updated_at)
  مع فرض uniqueness منطقي على الزوج الدوائي بصرف النظر عن ترتيب الإدخال،
  وتسوية السجلات القديمة عبر canonical ordering وأرشفة التكرارات الفعالة بدلاً من فقدانها.
- [ترقية V27]&#58; إضافة البنية الأساسية للمتطلب 23 (التكامل شبه المحلي مع التأمين الصحي) عبر:
  1) insurance_providers
  2) customer_insurance_policies
  3) insurance_claims
  4) insurance_claim_items
  5) insurance_collections
  مع توسيع transactions لدعم reference_type = 'insurance_collection'
  وإضافة القيود والفهارس والـ triggers اللازمة.
- [أمان / Fail-Safe]&#58; يرفض إقلاع النظام تماماً وتوليد قاعدة فارغة بدون متغير بيئة
  يحدد كلمة مرور المدير بقوة كافية.
"""

import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_DB_PATH = os.path.join(APP_DIR, "pharma_system.db")


class DatabaseManager:
    _instance = None

    def __new__(cls, db_name=None):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            raw_path = db_name or DEFAULT_DB_PATH
            cls._instance.db_name = raw_path if os.path.isabs(raw_path) else os.path.join(APP_DIR, raw_path)
            cls._instance.conn = None
            cls._instance.init_database()
        return cls._instance

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            return self.conn
        except sqlite3.Error as e:
            logger.error(f"Error connecting to database: {e}")
            return None

    def init_database(self):
        conn = self.connect()
        if not conn:
            return

        try:
            self._create_core_tables(conn)
            self._run_migrations(conn)
            self._create_triggers_and_indexes(conn)
            self._seed_admin(conn)
            conn.commit()
            logger.info("✅ تم فحص وتحديث قاعدة البيانات بنجاح (V27).")
        except RuntimeError as re:
            logger.critical(str(re))
            conn.rollback()
            raise
        except sqlite3.Error as e:
            logger.critical(f"❌ خطأ حرج في تهيئة قاعدة البيانات: {e}")
            conn.rollback()
        finally:
            conn.close()

    # ==========================================
    # Helpers عامة
    # ==========================================
    def _table_exists(self, cursor, table_name):
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,)
            )
            return cursor.fetchone() is not None
        except Exception:
            return False

    def _column_exists(self, cursor, table_name, column_name):
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [info[1] for info in cursor.fetchall()]
            return column_name in columns
        except Exception:
            return False

    def _normalize_interaction_ingredient(self, text):
        """
        تطبيع المكونات الفعالة الخاصة بالتداخلات:
        - trim
        - lower-case
        - دمج الفراغات المتعددة
        """
        if text is None:
            return ""
        return " ".join(str(text).strip().lower().split())

    def _canonicalize_interaction_pair(self, ingredient_1, ingredient_2):
        """
        يعيد الزوج الدوائي بترتيب canonical ثابت لمنع مشكلة:
        A+B و B+A
        """
        a = self._normalize_interaction_ingredient(ingredient_1)
        b = self._normalize_interaction_ingredient(ingredient_2)

        if not a or not b:
            raise ValueError("زوج التداخل الدوائي يحتوي مادة فعالة فارغة.")
        if a == b:
            raise ValueError("لا يجوز إنشاء تداخل بين المادة نفسها.")

        return (a, b) if a < b else (b, a)

    # ==========================================
    # Helpers تطبيع العملاء
    # ==========================================
    def _normalize_customer_unique_fields(self, cursor):
        """
        تطبيع بيانات العملاء القديمة قبل إنشاء الـ unique indexes:
        - إزالة الفراغات
        - تحويل القيم الفارغة إلى NULL
        - توحيد الإيميل إلى lower-case
        - إزالة التكرارات القديمة في phone/email/national_id بالإبقاء على أقدم سجل
        """
        if not self._table_exists(cursor, "customers"):
            return

        if self._column_exists(cursor, "customers", "phone"):
            cursor.execute("""
                UPDATE customers
                SET phone = NULL
                WHERE phone IS NOT NULL AND TRIM(phone) = ''
            """)
            cursor.execute("""
                UPDATE customers
                SET phone = TRIM(phone)
                WHERE phone IS NOT NULL AND TRIM(phone) <> ''
            """)

        if self._column_exists(cursor, "customers", "email"):
            cursor.execute("""
                UPDATE customers
                SET email = NULL
                WHERE email IS NOT NULL AND TRIM(email) = ''
            """)
            cursor.execute("""
                UPDATE customers
                SET email = LOWER(TRIM(email))
                WHERE email IS NOT NULL AND TRIM(email) <> ''
            """)

        if self._column_exists(cursor, "customers", "national_id"):
            cursor.execute("""
                UPDATE customers
                SET national_id = NULL
                WHERE national_id IS NOT NULL AND TRIM(national_id) = ''
            """)
            cursor.execute("""
                UPDATE customers
                SET national_id = TRIM(national_id)
                WHERE national_id IS NOT NULL AND TRIM(national_id) <> ''
            """)

        self._null_duplicate_customer_field(cursor, "phone")
        self._null_duplicate_customer_field(cursor, "email", use_lower=True)
        self._null_duplicate_customer_field(cursor, "national_id")

    def _null_duplicate_customer_field(self, cursor, field_name, use_lower=False):
        if not self._column_exists(cursor, "customers", field_name):
            return

        group_expr = f"LOWER(TRIM({field_name}))" if use_lower else f"TRIM({field_name})"

        cursor.execute(f"""
            SELECT {group_expr} AS normalized_value, GROUP_CONCAT(id), COUNT(*)
            FROM customers
            WHERE {field_name} IS NOT NULL AND TRIM({field_name}) <> ''
            GROUP BY normalized_value
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()

        for normalized_value, ids_csv, _ in duplicates:
            try:
                ids = sorted(int(x) for x in str(ids_csv).split(",") if str(x).strip())
            except Exception:
                continue

            if len(ids) <= 1:
                continue

            keep_id = ids[0]
            drop_ids = ids[1:]
            placeholders = ",".join("?" for _ in drop_ids)

            cursor.execute(
                f"UPDATE customers SET {field_name} = NULL WHERE id IN ({placeholders})",
                drop_ids
            )

            logger.warning(
                f"تمت تسوية تكرار قديم في customers.{field_name} للقيمة [{normalized_value}] "
                f"بالإبقاء على السجل {keep_id} وتفريغ القيمة من السجلات: {drop_ids}"
            )

    # ==========================================
    # Helpers تطبيع الموردين
    # ==========================================
    def _normalize_supplier_unique_fields(self, cursor):
        """
        تطبيع بيانات الموردين القديمة قبل إنشاء القيود الجديدة:
        - Trim للنصوص
        - تحويل الفراغات إلى NULL للحقول الاختيارية
        - توحيد الإيميل إلى lower-case
        - أي اسم فارغ/NULL يُعالج باسم احتياطي Legacy Supplier #ID
        - أي تكرار قديم في email يُسوى بالإبقاء على أقدم سجل وتفريغ الإيميل من الباقي
        - أي تكرار قديم في هوية المورد (name + company_name) يتم أرشفته عبر is_active = 0
          مع الإبقاء على أقدم سجل فعال فقط
        """
        if not self._table_exists(cursor, "suppliers"):
            return

        if self._column_exists(cursor, "suppliers", "name"):
            cursor.execute("""
                UPDATE suppliers
                SET name = TRIM(name)
                WHERE name IS NOT NULL
            """)
            cursor.execute("""
                UPDATE suppliers
                SET name = ('Legacy Supplier #' || id)
                WHERE name IS NULL OR TRIM(name) = ''
            """)

        for field_name in ["phone", "company_name", "address", "notes"]:
            if self._column_exists(cursor, "suppliers", field_name):
                cursor.execute(f"""
                    UPDATE suppliers
                    SET {field_name} = NULL
                    WHERE {field_name} IS NOT NULL AND TRIM({field_name}) = ''
                """)
                cursor.execute(f"""
                    UPDATE suppliers
                    SET {field_name} = TRIM({field_name})
                    WHERE {field_name} IS NOT NULL AND TRIM({field_name}) <> ''
                """)

        if self._column_exists(cursor, "suppliers", "email"):
            cursor.execute("""
                UPDATE suppliers
                SET email = NULL
                WHERE email IS NOT NULL AND TRIM(email) = ''
            """)
            cursor.execute("""
                UPDATE suppliers
                SET email = LOWER(TRIM(email))
                WHERE email IS NOT NULL AND TRIM(email) <> ''
            """)

        if self._column_exists(cursor, "suppliers", "is_active"):
            cursor.execute("""
                UPDATE suppliers
                SET is_active = 1
                WHERE is_active IS NULL
            """)

        if self._column_exists(cursor, "suppliers", "updated_at"):
            cursor.execute("""
                UPDATE suppliers
                SET updated_at = CURRENT_TIMESTAMP
                WHERE updated_at IS NULL
            """)

        self._null_duplicate_supplier_field(cursor, "email", use_lower=True)
        self._archive_duplicate_supplier_identities(cursor)

    def _null_duplicate_supplier_field(self, cursor, field_name, use_lower=False):
        if not self._column_exists(cursor, "suppliers", field_name):
            return

        group_expr = f"LOWER(TRIM({field_name}))" if use_lower else f"TRIM({field_name})"

        cursor.execute(f"""
            SELECT {group_expr} AS normalized_value, GROUP_CONCAT(id), COUNT(*)
            FROM suppliers
            WHERE {field_name} IS NOT NULL AND TRIM({field_name}) <> ''
            GROUP BY normalized_value
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()

        for normalized_value, ids_csv, _ in duplicates:
            try:
                ids = sorted(int(x) for x in str(ids_csv).split(",") if str(x).strip())
            except Exception:
                continue

            if len(ids) <= 1:
                continue

            keep_id = ids[0]
            drop_ids = ids[1:]
            placeholders = ",".join("?" for _ in drop_ids)

            cursor.execute(
                f"UPDATE suppliers SET {field_name} = NULL WHERE id IN ({placeholders})",
                drop_ids
            )

            logger.warning(
                f"تمت تسوية تكرار قديم في suppliers.{field_name} للقيمة [{normalized_value}] "
                f"بالإبقاء على السجل {keep_id} وتفريغ القيمة من السجلات: {drop_ids}"
            )

    def _archive_duplicate_supplier_identities(self, cursor):
        """
        يمنع سقوط الترقية إذا وُجدت سجلات موردين قديمة مكررة بنفس
        (name + company_name). يتم الإبقاء على أقدم سجل فعال فقط،
        وأرشفة البقية عبر is_active = 0.
        """
        required_columns = ["name", "company_name", "is_active"]
        for col in required_columns:
            if not self._column_exists(cursor, "suppliers", col):
                return

        cursor.execute("""
            SELECT
                LOWER(TRIM(name)) AS normalized_name,
                LOWER(TRIM(COALESCE(company_name, ''))) AS normalized_company,
                GROUP_CONCAT(id),
                COUNT(*)
            FROM suppliers
            WHERE is_active = 1
              AND name IS NOT NULL
              AND TRIM(name) <> ''
            GROUP BY normalized_name, normalized_company
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()

        for normalized_name, normalized_company, ids_csv, _ in duplicates:
            try:
                ids = sorted(int(x) for x in str(ids_csv).split(",") if str(x).strip())
            except Exception:
                continue

            if len(ids) <= 1:
                continue

            keep_id = ids[0]
            archive_ids = ids[1:]
            placeholders = ",".join("?" for _ in archive_ids)

            if self._column_exists(cursor, "suppliers", "updated_at"):
                cursor.execute(
                    f"""
                    UPDATE suppliers
                    SET is_active = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})
                    """,
                    archive_ids
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE suppliers
                    SET is_active = 0
                    WHERE id IN ({placeholders})
                    """,
                    archive_ids
                )

            logger.warning(
                "تم العثور على موردين مكررين بالهوية نفسها "
                f"(name={normalized_name}, company={normalized_company}). "
                f"تم الإبقاء على السجل {keep_id} وأرشفة السجلات: {archive_ids}"
            )

    # ==========================================
    # إنشاء الجداول الأساسية
    # ==========================================
    def _create_core_tables(self, conn):
        """تعكس الحالة النهائية للمخطط (V27) للقواعد التي تنشأ من الصفر."""
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'pharmacist', 'cashier')) DEFAULT 'pharmacist',
                is_active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                opening_cash REAL NOT NULL CHECK(opening_cash >= 0),
                expected_cash REAL DEFAULT 0.0 CHECK(expected_cash >= 0),
                actual_cash REAL,
                variance REAL,
                status TEXT NOT NULL CHECK(status IN ('open', 'closed')) DEFAULT 'open',
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                opening_notes TEXT,
                closing_notes TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                company_name TEXT,
                email TEXT,
                address TEXT,
                notes TEXT,
                balance REAL NOT NULL DEFAULT 0.0 CHECK(balance >= 0 OR balance < 0),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                national_id TEXT,
                date_of_birth DATE,
                gender TEXT CHECK(gender IN ('male', 'female', 'other')),
                address TEXT,
                notes TEXT,
                medical_notes TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==========================================
        # V27: Insurance Providers & Policies
        # ==========================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insurance_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT,
                contact_person TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                notes TEXT,
                default_coverage_percent REAL NOT NULL DEFAULT 80.0 CHECK(default_coverage_percent >= 0 AND default_coverage_percent <= 100),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK(length(trim(name)) > 0)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customer_insurance_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                provider_id INTEGER NOT NULL,
                policy_number TEXT NOT NULL,
                member_number TEXT,
                default_coverage_percent REAL NOT NULL DEFAULT 80.0 CHECK(default_coverage_percent >= 0 AND default_coverage_percent <= 100),
                default_patient_share_percent REAL NOT NULL DEFAULT 20.0 CHECK(default_patient_share_percent >= 0 AND default_patient_share_percent <= 100),
                coverage_limit_amount REAL CHECK(coverage_limit_amount IS NULL OR coverage_limit_amount >= 0),
                valid_from DATE,
                valid_to DATE,
                status TEXT NOT NULL CHECK(status IN ('active', 'expired', 'suspended', 'cancelled')) DEFAULT 'active',
                is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
                notes TEXT,
                created_by_user_id INTEGER NOT NULL,
                updated_by_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(provider_id) REFERENCES insurance_providers(id),
                FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                FOREIGN KEY(updated_by_user_id) REFERENCES users(id),
                CHECK(length(trim(policy_number)) > 0),
                CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
                CHECK(default_coverage_percent + default_patient_share_percent <= 100)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                active_ingredient TEXT,
                dosage_form TEXT,
                strength TEXT,
                description TEXT,
                buy_price REAL NOT NULL CHECK(buy_price >= 0),
                sell_price REAL NOT NULL CHECK(sell_price >= 0),
                quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                expiry_date DATE,
                supplier_id INTEGER,
                min_stock_alert INTEGER NOT NULL DEFAULT 10 CHECK(min_stock_alert >= 0),
                is_controlled INTEGER NOT NULL DEFAULT 0 CHECK(is_controlled IN (0,1)),
                controlled_class TEXT,
                controlled_notes TEXT,
                is_hazardous INTEGER NOT NULL DEFAULT 0 CHECK(is_hazardous IN (0,1)),
                hazard_class TEXT,
                hazard_notes TEXT,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medicine_id INTEGER NOT NULL,
                batch_number TEXT NOT NULL,
                expiry_date DATE NOT NULL,
                buy_price REAL NOT NULL CHECK(buy_price >= 0),
                sell_price REAL NOT NULL CHECK(sell_price >= 0),
                quantity INTEGER NOT NULL CHECK(quantity >= 0),
                status TEXT NOT NULL CHECK(status IN ('active', 'expired', 'depleted', 'recalled')) DEFAULT 'active',
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                offer_type TEXT NOT NULL CHECK(offer_type IN ('simple_discount', 'cart_discount', 'bogo')),
                discount_type TEXT NOT NULL CHECK(discount_type IN ('percent', 'fixed', 'none')),
                discount_value REAL NOT NULL DEFAULT 0.0 CHECK(discount_value >= 0),
                scope_type TEXT NOT NULL CHECK(scope_type IN ('item', 'cart', 'category')),
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_by_user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                CHECK(start_date <= end_date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS offer_medicines (
                offer_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                PRIMARY KEY (offer_id, medicine_id),
                FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE,
                FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                shift_id INTEGER,
                customer_id INTEGER,
                doctor_name TEXT,
                subtotal_amount REAL NOT NULL DEFAULT 0.0 CHECK(subtotal_amount >= 0),
                cart_discount_amount REAL NOT NULL DEFAULT 0.0 CHECK(cart_discount_amount >= 0),
                total_amount REAL NOT NULL CHECK(total_amount >= 0),
                applied_cart_offer_id INTEGER,
                sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(applied_cart_offer_id) REFERENCES offers(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                prescription_item_id INTEGER,
                original_unit_price REAL NOT NULL DEFAULT 0.0 CHECK(original_unit_price >= 0),
                discount_amount REAL NOT NULL DEFAULT 0.0 CHECK(discount_amount >= 0),
                final_unit_price REAL NOT NULL DEFAULT 0.0 CHECK(final_unit_price >= 0),
                price_at_sale REAL NOT NULL CHECK(price_at_sale >= 0),
                total_item_price REAL NOT NULL CHECK(total_item_price >= 0),
                applied_offer_id INTEGER,
                days_supply_at_sale INTEGER,
                FOREIGN KEY(sale_id) REFERENCES sales(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                FOREIGN KEY(batch_id) REFERENCES batches(id),
                FOREIGN KEY(prescription_item_id) REFERENCES prescription_items(id),
                FOREIGN KEY(applied_offer_id) REFERENCES offers(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                shift_id INTEGER,
                return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_amount REAL NOT NULL CHECK(total_amount >= 0),
                reason TEXT,
                status TEXT NOT NULL CHECK(status IN ('completed', 'voided')) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sale_id) REFERENCES sales(id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id INTEGER NOT NULL,
                sale_item_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                documented_unit_refund REAL NOT NULL CHECK(documented_unit_refund >= 0),
                total_item_amount REAL NOT NULL CHECK(total_item_amount >= 0),
                reason TEXT,
                FOREIGN KEY(return_id) REFERENCES returns(id),
                FOREIGN KEY(sale_item_id) REFERENCES sale_items(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                FOREIGN KEY(batch_id) REFERENCES batches(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS controlled_return_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id INTEGER NOT NULL,
                return_item_id INTEGER NOT NULL UNIQUE,
                sale_item_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                returned_qty INTEGER NOT NULL CHECK(returned_qty > 0),
                controlled_class TEXT,
                notes TEXT,
                status TEXT NOT NULL CHECK(status IN ('completed', 'voided')) DEFAULT 'completed',
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                voided_at TIMESTAMP,
                voided_by_user_id INTEGER,
                FOREIGN KEY (return_id) REFERENCES returns(id),
                FOREIGN KEY (return_item_id) REFERENCES return_items(id),
                FOREIGN KEY (sale_item_id) REFERENCES sale_items(id),
                FOREIGN KEY (medicine_id) REFERENCES medicines(id),
                FOREIGN KEY (batch_id) REFERENCES batches(id),
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (voided_by_user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT NOT NULL UNIQUE,
                supplier_id INTEGER,
                status TEXT NOT NULL CHECK(status IN ('draft', 'submitted', 'approved', 'partially_received', 'received', 'cancelled')) DEFAULT 'draft',
                order_date DATE NOT NULL,
                expected_date DATE,
                created_by_user_id INTEGER NOT NULL,
                approved_by_user_id INTEGER,
                approved_at TIMESTAMP,
                received_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                requested_qty INTEGER NOT NULL CHECK(requested_qty > 0),
                estimated_unit_cost REAL CHECK(estimated_unit_cost >= 0),
                notes TEXT,
                FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                UNIQUE(purchase_order_id, medicine_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                purchase_order_id INTEGER REFERENCES purchase_orders(id),
                invoice_number TEXT NOT NULL,
                invoice_date DATE NOT NULL,
                total_amount REAL NOT NULL CHECK(total_amount >= 0),
                paid_amount REAL NOT NULL DEFAULT 0.0 CHECK(paid_amount >= 0),
                unpaid_amount REAL NOT NULL DEFAULT 0.0 CHECK(unpaid_amount >= 0),
                payment_status TEXT NOT NULL CHECK(payment_status IN ('unpaid', 'partial', 'paid')) DEFAULT 'unpaid',
                shift_id INTEGER REFERENCES shifts(id),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL,
                purchase_order_item_id INTEGER REFERENCES purchase_order_items(id),
                medicine_id INTEGER NOT NULL,
                batch_number TEXT NOT NULL,
                expiry_date DATE NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
                sell_price REAL NOT NULL CHECK(sell_price >= 0),
                total_cost REAL NOT NULL CHECK(total_cost >= 0),
                FOREIGN KEY(purchase_id) REFERENCES purchase_invoices(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expense_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                shift_id INTEGER,
                amount REAL NOT NULL CHECK(amount > 0),
                expense_date DATE NOT NULL,
                payment_method TEXT NOT NULL CHECK(payment_method IN ('cash')) DEFAULT 'cash',
                payee_type TEXT NOT NULL CHECK(payee_type IN ('vendor', 'employee', 'operational', 'owner_draw', 'other')),
                payee_id INTEGER,
                payee_name TEXT,
                status TEXT NOT NULL CHECK(status IN ('completed', 'voided')) DEFAULT 'completed',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(category_id) REFERENCES expense_categories(id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id),
                CHECK (payee_name IS NOT NULL OR payee_id IS NOT NULL)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                disposal_date DATE NOT NULL,
                total_cost REAL NOT NULL CHECK(total_cost >= 0),
                reason TEXT NOT NULL CHECK(reason IN ('expired', 'damaged', 'recalled', 'other')) DEFAULT 'expired',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disposal_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disposal_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
                total_item_cost REAL NOT NULL CHECK(total_item_cost >= 0),
                FOREIGN KEY(disposal_id) REFERENCES disposals(id) ON DELETE CASCADE,
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                FOREIGN KEY(batch_id) REFERENCES batches(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hazardous_disposal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disposal_id INTEGER NOT NULL,
                disposal_item_id INTEGER NOT NULL UNIQUE,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                hazard_class TEXT,
                disposal_reason TEXT NOT NULL,
                disposal_method TEXT NOT NULL,
                receiver_entity TEXT,
                manifest_number TEXT,
                notes TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (disposal_id) REFERENCES disposals(id),
                FOREIGN KEY (disposal_item_id) REFERENCES disposal_items(id),
                FOREIGN KEY (medicine_id) REFERENCES medicines(id),
                FOREIGN KEY (batch_id) REFERENCES batches(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('in', 'out')),
                reference_type TEXT NOT NULL CHECK(reference_type IN (
                    'sale', 'purchase', 'expense', 'return', 'disposal',
                    'return_void', 'expense_void', 'shift_opening',
                    'shift_closing_adjustment', 'cash_drop', 'cash_over_short',
                    'insurance_collection'
                )),
                reference_id INTEGER,
                amount REAL NOT NULL CHECK(amount >= 0),
                user_id INTEGER NOT NULL,
                shift_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL CHECK(action IN ('INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'LOGOUT', 'LOGIN_FAILED', 'SIMULATE_REMINDER', 'DISPATCH_REMINDER')),
                table_name TEXT NOT NULL,
                record_id INTEGER,
                old_values TEXT,
                new_values TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialty TEXT,
                phone TEXT,
                license_number TEXT UNIQUE,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prescription_number TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                prescription_type TEXT NOT NULL DEFAULT 'regular'
                    CHECK(prescription_type IN ('regular', 'chronic', 'controlled', 'insurance')),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'partially_dispensed', 'fully_dispensed', 'expired', 'cancelled')),
                issue_date DATE NOT NULL,
                expiry_date DATE NOT NULL,
                notes TEXT,
                created_by_user_id INTEGER NOT NULL,
                updated_by_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                FOREIGN KEY (created_by_user_id) REFERENCES users(id),
                FOREIGN KEY (updated_by_user_id) REFERENCES users(id),
                CHECK(issue_date <= expiry_date)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prescription_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prescription_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                prescribed_qty INTEGER NOT NULL CHECK(prescribed_qty > 0),
                dispensed_qty INTEGER NOT NULL DEFAULT 0 CHECK(dispensed_qty >= 0),
                days_supply INTEGER DEFAULT 30,
                dosage_instructions TEXT,
                notes TEXT,
                FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE,
                FOREIGN KEY (medicine_id) REFERENCES medicines(id),
                CHECK(dispensed_qty <= prescribed_qty),
                UNIQUE(prescription_id, medicine_id)
            )
        """)

        # ==========================================
        # V27: Insurance Claims & Collections
        # ==========================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insurance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_number TEXT NOT NULL UNIQUE,
                provider_id INTEGER NOT NULL,
                policy_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                prescription_id INTEGER,
                sale_id INTEGER,
                status TEXT NOT NULL CHECK(status IN ('draft', 'submitted', 'approved', 'partially_approved', 'rejected', 'collected', 'cancelled')) DEFAULT 'draft',
                service_date DATE NOT NULL DEFAULT CURRENT_DATE,
                claim_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                gross_amount REAL NOT NULL DEFAULT 0.0 CHECK(gross_amount >= 0),
                insurer_amount REAL NOT NULL DEFAULT 0.0 CHECK(insurer_amount >= 0),
                patient_amount REAL NOT NULL DEFAULT 0.0 CHECK(patient_amount >= 0),
                approved_amount REAL NOT NULL DEFAULT 0.0 CHECK(approved_amount >= 0),
                collected_amount REAL NOT NULL DEFAULT 0.0 CHECK(collected_amount >= 0),
                external_claim_number TEXT,
                submission_notes TEXT,
                decision_notes TEXT,
                rejection_reason TEXT,
                created_by_user_id INTEGER NOT NULL,
                updated_by_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(provider_id) REFERENCES insurance_providers(id),
                FOREIGN KEY(policy_id) REFERENCES customer_insurance_policies(id),
                FOREIGN KEY(customer_id) REFERENCES customers(id),
                FOREIGN KEY(prescription_id) REFERENCES prescriptions(id),
                FOREIGN KEY(sale_id) REFERENCES sales(id),
                FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insurance_claim_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id INTEGER NOT NULL,
                sale_item_id INTEGER,
                prescription_item_id INTEGER,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL DEFAULT 0.0 CHECK(unit_price >= 0),
                gross_amount REAL NOT NULL DEFAULT 0.0 CHECK(gross_amount >= 0),
                covered_amount REAL NOT NULL DEFAULT 0.0 CHECK(covered_amount >= 0),
                patient_amount REAL NOT NULL DEFAULT 0.0 CHECK(patient_amount >= 0),
                approval_status TEXT NOT NULL CHECK(approval_status IN ('pending', 'approved', 'partial', 'rejected')) DEFAULT 'pending',
                rejection_reason TEXT,
                notes TEXT,
                FOREIGN KEY(claim_id) REFERENCES insurance_claims(id) ON DELETE CASCADE,
                FOREIGN KEY(sale_item_id) REFERENCES sale_items(id),
                FOREIGN KEY(prescription_item_id) REFERENCES prescription_items(id),
                FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                FOREIGN KEY(batch_id) REFERENCES batches(id),
                UNIQUE(claim_id, sale_item_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insurance_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id INTEGER NOT NULL,
                collection_reference TEXT,
                collection_date DATE NOT NULL DEFAULT CURRENT_DATE,
                amount REAL NOT NULL CHECK(amount > 0),
                payment_method TEXT NOT NULL CHECK(payment_method IN ('cash', 'bank_transfer', 'check', 'other')) DEFAULT 'bank_transfer',
                user_id INTEGER NOT NULL,
                shift_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(claim_id) REFERENCES insurance_claims(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS controlled_dispensing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                sale_item_id INTEGER NOT NULL UNIQUE,
                prescription_id INTEGER NOT NULL,
                prescription_item_id INTEGER NOT NULL,
                medicine_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                pharmacist_user_id INTEGER NOT NULL,
                dispensed_qty INTEGER NOT NULL CHECK(dispensed_qty > 0),
                receiver_full_name TEXT NOT NULL,
                receiver_national_id TEXT NOT NULL,
                receiver_phone TEXT,
                receiver_relation TEXT NOT NULL DEFAULT 'self' CHECK(receiver_relation IN ('self', 'parent', 'spouse', 'guardian', 'other')),
                controlled_class TEXT,
                notes TEXT,
                dispensed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sale_id) REFERENCES sales(id),
                FOREIGN KEY (sale_item_id) REFERENCES sale_items(id),
                FOREIGN KEY (prescription_id) REFERENCES prescriptions(id),
                FOREIGN KEY (prescription_item_id) REFERENCES prescription_items(id),
                FOREIGN KEY (medicine_id) REFERENCES medicines(id),
                FOREIGN KEY (batch_id) REFERENCES batches(id),
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                FOREIGN KEY (pharmacist_user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drug_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_1 TEXT NOT NULL,
                ingredient_2 TEXT NOT NULL,
                severity TEXT NOT NULL CHECK(severity IN ('minor', 'moderate', 'major', 'contraindicated')),
                clinical_effect TEXT NOT NULL,
                recommendation TEXT,
                management_plan TEXT,
                source_reference TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_by_user_id INTEGER NOT NULL,
                updated_by_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                FOREIGN KEY(updated_by_user_id) REFERENCES users(id),
                CHECK(length(trim(ingredient_1)) > 0),
                CHECK(length(trim(ingredient_2)) > 0),
                CHECK(LOWER(TRIM(ingredient_1)) <> LOWER(TRIM(ingredient_2)))
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drug_safety_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                contraindications TEXT,
                max_daily_dose TEXT,
                pregnancy_warning TEXT,
                lactation_warning TEXT,
                renal_warning TEXT,
                hepatic_warning TEXT,
                pediatric_warning TEXT,
                geriatric_warning TEXT,
                counseling_notes TEXT,
                overdose_notes TEXT,
                source_reference TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                created_by_user_id INTEGER NOT NULL,
                updated_by_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK(length(trim(ingredient_key)) > 0),
                FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drug_side_effects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                effect_name TEXT NOT NULL,
                frequency TEXT CHECK(frequency IN ('common', 'uncommon', 'rare', 'very_rare', 'unknown')),
                severity TEXT CHECK(severity IN ('mild', 'moderate', 'severe')),
                notes TEXT,
                FOREIGN KEY(profile_id) REFERENCES drug_safety_profiles(id) ON DELETE CASCADE,
                UNIQUE(profile_id, effect_name)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_date DATE UNIQUE NOT NULL,
                total_shifts_count INTEGER NOT NULL DEFAULT 0,
                total_opening_cash REAL NOT NULL DEFAULT 0.0,
                total_expected_cash REAL NOT NULL DEFAULT 0.0,
                total_actual_cash REAL NOT NULL DEFAULT 0.0,
                total_variance REAL NOT NULL DEFAULT 0.0,
                total_cash_drops REAL NOT NULL DEFAULT 0.0,
                closed_by_user_id INTEGER NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(closed_by_user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_closure_shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_closure_id INTEGER NOT NULL,
                shift_id INTEGER NOT NULL UNIQUE,
                FOREIGN KEY(daily_closure_id) REFERENCES daily_closures(id) ON DELETE CASCADE,
                FOREIGN KEY(shift_id) REFERENCES shifts(id)
            )
        """)

    # ==========================================
    # التهجير
    # ==========================================
    def _run_migrations(self, conn):
        cursor = conn.cursor()

        # ==========================================
        # V1
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 1")
        if not cursor.fetchone():
            if self._column_exists(cursor, 'users', 'id'):
                if not self._column_exists(cursor, 'users', 'password_hash'):
                    cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")

                if not self._column_exists(cursor, 'users', 'is_active'):
                    cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

                if not self._column_exists(cursor, 'users', 'must_change_password'):
                    cursor.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 1")

                if not self._column_exists(cursor, 'users', 'updated_at'):
                    cursor.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP")
                    cursor.execute("""
                        UPDATE users
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """)

                try:
                    cursor.execute("UPDATE users SET password_hash = password WHERE password_hash = ''")
                except Exception:
                    pass

            cursor.execute("INSERT INTO schema_version (version) VALUES (1)")

        # ==========================================
        # V2 -> V17
        # ==========================================
        for v in range(2, 18):
            cursor.execute("SELECT version FROM schema_version WHERE version = ?", (v,))
            if not cursor.fetchone():
                if v == 6:
                    if self._column_exists(cursor, 'sale_items', 'id') and not self._column_exists(cursor, 'sale_items', 'prescription_item_id'):
                        cursor.execute("ALTER TABLE sale_items ADD COLUMN prescription_item_id INTEGER REFERENCES prescription_items(id)")

                elif v == 9:
                    if self._column_exists(cursor, 'medicines', 'id') and not self._column_exists(cursor, 'medicines', 'dosage_form'):
                        cursor.execute("ALTER TABLE medicines ADD COLUMN dosage_form TEXT")
                        cursor.execute("ALTER TABLE medicines ADD COLUMN strength TEXT")

                elif v == 10:
                    if self._column_exists(cursor, 'prescription_items', 'id') and not self._column_exists(cursor, 'prescription_items', 'days_supply'):
                        cursor.execute("ALTER TABLE prescription_items ADD COLUMN days_supply INTEGER DEFAULT 30")

                elif v == 11:
                    if self._column_exists(cursor, 'medicines', 'id') and not self._column_exists(cursor, 'medicines', 'is_controlled'):
                        cursor.execute("ALTER TABLE medicines ADD COLUMN is_controlled INTEGER NOT NULL DEFAULT 0 CHECK(is_controlled IN (0,1))")
                        cursor.execute("ALTER TABLE medicines ADD COLUMN controlled_class TEXT")
                        cursor.execute("ALTER TABLE medicines ADD COLUMN controlled_notes TEXT")

                elif v == 12:
                    if self._column_exists(cursor, 'sales', 'id') and not self._column_exists(cursor, 'sales', 'subtotal_amount'):
                        cursor.execute("ALTER TABLE sales ADD COLUMN subtotal_amount REAL NOT NULL DEFAULT 0.0 CHECK(subtotal_amount >= 0)")
                        cursor.execute("ALTER TABLE sales ADD COLUMN cart_discount_amount REAL NOT NULL DEFAULT 0.0 CHECK(cart_discount_amount >= 0)")
                        cursor.execute("ALTER TABLE sales ADD COLUMN applied_cart_offer_id INTEGER REFERENCES offers(id)")

                    if self._column_exists(cursor, 'sale_items', 'id') and not self._column_exists(cursor, 'sale_items', 'original_unit_price'):
                        cursor.execute("ALTER TABLE sale_items ADD COLUMN original_unit_price REAL NOT NULL DEFAULT 0.0 CHECK(original_unit_price >= 0)")
                        cursor.execute("ALTER TABLE sale_items ADD COLUMN discount_amount REAL NOT NULL DEFAULT 0.0 CHECK(discount_amount >= 0)")
                        cursor.execute("ALTER TABLE sale_items ADD COLUMN final_unit_price REAL NOT NULL DEFAULT 0.0 CHECK(final_unit_price >= 0)")
                        cursor.execute("ALTER TABLE sale_items ADD COLUMN applied_offer_id INTEGER REFERENCES offers(id)")

                elif v == 13:
                    if self._column_exists(cursor, 'medicines', 'id') and not self._column_exists(cursor, 'medicines', 'is_hazardous'):
                        cursor.execute("ALTER TABLE medicines ADD COLUMN is_hazardous INTEGER NOT NULL DEFAULT 0 CHECK(is_hazardous IN (0,1))")
                        cursor.execute("ALTER TABLE medicines ADD COLUMN hazard_class TEXT")
                        cursor.execute("ALTER TABLE medicines ADD COLUMN hazard_notes TEXT")

                elif v == 14:
                    if self._column_exists(cursor, 'sales', 'id') and not self._column_exists(cursor, 'sales', 'shift_id'):
                        cursor.execute("ALTER TABLE sales ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")
                    if self._column_exists(cursor, 'returns', 'id') and not self._column_exists(cursor, 'returns', 'shift_id'):
                        cursor.execute("ALTER TABLE returns ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")
                    if self._column_exists(cursor, 'expenses', 'id') and not self._column_exists(cursor, 'expenses', 'shift_id'):
                        cursor.execute("ALTER TABLE expenses ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")

                elif v == 16:
                    if self._column_exists(cursor, 'purchase_invoices', 'id') and not self._column_exists(cursor, 'purchase_invoices', 'purchase_order_id'):
                        cursor.execute("ALTER TABLE purchase_invoices ADD COLUMN purchase_order_id INTEGER REFERENCES purchase_orders(id)")
                    if self._column_exists(cursor, 'purchase_items', 'id') and not self._column_exists(cursor, 'purchase_items', 'purchase_order_item_id'):
                        cursor.execute("ALTER TABLE purchase_items ADD COLUMN purchase_order_item_id INTEGER REFERENCES purchase_order_items(id)")

                cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))

        # ==========================================
        # V18
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 18")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V18: تحصين المرتجعات، المصروفات، وتحديث المعاملات...")

            if self._column_exists(cursor, 'returns', 'id') and not self._column_exists(cursor, 'returns', 'status'):
                cursor.execute("ALTER TABLE returns ADD COLUMN status TEXT NOT NULL CHECK(status IN ('completed', 'voided')) DEFAULT 'completed'")

            if self._column_exists(cursor, 'return_items', 'id') and not self._column_exists(cursor, 'return_items', 'documented_unit_refund'):
                cursor.execute("ALTER TABLE return_items ADD COLUMN documented_unit_refund REAL NOT NULL DEFAULT 0.0 CHECK(documented_unit_refund >= 0)")
                if self._column_exists(cursor, 'return_items', 'price_at_return'):
                    try:
                        cursor.execute("UPDATE return_items SET documented_unit_refund = price_at_return")
                    except Exception:
                        pass

            default_categories = [
                'operational_expense', 'vendor_payment', 'petty_cash_purchase', 'salary_advance',
                'utility_payment', 'maintenance', 'transport', 'other_approved'
            ]
            for cat in default_categories:
                cursor.execute("INSERT OR IGNORE INTO expense_categories (name) VALUES (?)", (cat,))

            if self._column_exists(cursor, 'expenses', 'id') and not self._column_exists(cursor, 'expenses', 'payee_type'):
                cursor.execute("DROP TABLE IF EXISTS expenses_v18_backup")
                cursor.execute("ALTER TABLE expenses RENAME TO expenses_v18_backup")
                cursor.execute("""
                    CREATE TABLE expenses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        shift_id INTEGER,
                        amount REAL NOT NULL CHECK(amount > 0),
                        expense_date DATE NOT NULL,
                        payment_method TEXT NOT NULL CHECK(payment_method IN ('cash')) DEFAULT 'cash',
                        payee_type TEXT NOT NULL CHECK(payee_type IN ('vendor', 'employee', 'operational', 'owner_draw', 'other')),
                        payee_id INTEGER,
                        payee_name TEXT,
                        status TEXT NOT NULL CHECK(status IN ('completed', 'voided')) DEFAULT 'completed',
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(category_id) REFERENCES expense_categories(id),
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(shift_id) REFERENCES shifts(id),
                        CHECK (payee_name IS NOT NULL OR payee_id IS NOT NULL)
                    )
                """)
                try:
                    cursor.execute("""
                        INSERT INTO expenses (id, category_id, user_id, shift_id, amount, expense_date, payment_method, payee_type, payee_name, status, notes, created_at)
                        SELECT id, category_id, user_id, shift_id, amount, expense_date, 'cash', 'other', 'Migrated Legacy Expense', 'completed', notes, created_at
                        FROM expenses_v18_backup
                    """)
                except Exception as e:
                    logger.warning(f"Could not migrate legacy expenses during V18 upgrade: {e}")

            if self._column_exists(cursor, 'transactions', 'id'):
                if not self._column_exists(cursor, 'transactions', 'shift_id'):
                    cursor.execute("ALTER TABLE transactions ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")

                cursor.execute("DROP TABLE IF EXISTS transactions_v18_backup")
                cursor.execute("ALTER TABLE transactions RENAME TO transactions_v18_backup")
                cursor.execute("""
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        transaction_type TEXT NOT NULL CHECK(transaction_type IN ('in', 'out')),
                        reference_type TEXT NOT NULL CHECK(reference_type IN (
                            'sale', 'purchase', 'expense', 'return', 'disposal',
                            'return_void', 'expense_void', 'shift_opening',
                            'shift_closing_adjustment', 'cash_drop', 'cash_over_short'
                        )),
                        reference_id INTEGER,
                        amount REAL NOT NULL CHECK(amount >= 0),
                        user_id INTEGER NOT NULL,
                        shift_id INTEGER,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(shift_id) REFERENCES shifts(id)
                    )
                """)
                try:
                    cursor.execute("""
                        INSERT INTO transactions
                        SELECT id, transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes, created_at
                        FROM transactions_v18_backup
                    """)
                except Exception as e:
                    logger.warning(f"Could not migrate legacy transactions during V18 upgrade: {e}")

            cursor.execute("INSERT INTO schema_version (version) VALUES (18)")

        # ==========================================
        # V19
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 19")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V19: إضافة جداول الإقفال اليومي للورديات...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_closures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_date DATE UNIQUE NOT NULL,
                    total_shifts_count INTEGER NOT NULL DEFAULT 0,
                    total_opening_cash REAL NOT NULL DEFAULT 0.0,
                    total_expected_cash REAL NOT NULL DEFAULT 0.0,
                    total_actual_cash REAL NOT NULL DEFAULT 0.0,
                    total_variance REAL NOT NULL DEFAULT 0.0,
                    total_cash_drops REAL NOT NULL DEFAULT 0.0,
                    closed_by_user_id INTEGER NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(closed_by_user_id) REFERENCES users(id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_closure_shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    daily_closure_id INTEGER NOT NULL,
                    shift_id INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(daily_closure_id) REFERENCES daily_closures(id) ON DELETE CASCADE,
                    FOREIGN KEY(shift_id) REFERENCES shifts(id)
                )
            """)
            cursor.execute("INSERT INTO schema_version (version) VALUES (19)")

        # ==========================================
        # V20
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 20")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V20: تحديث قيود audit_logs...")
            if self._column_exists(cursor, 'audit_logs', 'id'):
                cursor.execute("DROP TABLE IF EXISTS audit_logs_v20_backup")
                cursor.execute("ALTER TABLE audit_logs RENAME TO audit_logs_v20_backup")
                cursor.execute("""
                    CREATE TABLE audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        action TEXT NOT NULL CHECK(action IN ('INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'LOGOUT', 'LOGIN_FAILED', 'SIMULATE_REMINDER', 'DISPATCH_REMINDER')),
                        table_name TEXT NOT NULL,
                        record_id INTEGER,
                        old_values TEXT,
                        new_values TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                """)
                try:
                    cursor.execute("INSERT INTO audit_logs SELECT * FROM audit_logs_v20_backup")
                except Exception as e:
                    logger.warning(f"V20 Migration warning: {e}")
            cursor.execute("INSERT INTO schema_version (version) VALUES (20)")

        # ==========================================
        # V21
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 21")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V21: إضافة days_supply_at_sale إلى sale_items...")
            if self._column_exists(cursor, 'sale_items', 'id') and not self._column_exists(cursor, 'sale_items', 'days_supply_at_sale'):
                cursor.execute("ALTER TABLE sale_items ADD COLUMN days_supply_at_sale INTEGER")
            cursor.execute("INSERT INTO schema_version (version) VALUES (21)")

        # ==========================================
        # V22
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 22")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V22: إضافة الحقول المحاسبية لفواتير الشراء...")
            if self._column_exists(cursor, 'purchase_invoices', 'id'):
                if not self._column_exists(cursor, 'purchase_invoices', 'paid_amount'):
                    cursor.execute("ALTER TABLE purchase_invoices ADD COLUMN paid_amount REAL NOT NULL DEFAULT 0.0 CHECK(paid_amount >= 0)")
                if not self._column_exists(cursor, 'purchase_invoices', 'unpaid_amount'):
                    cursor.execute("ALTER TABLE purchase_invoices ADD COLUMN unpaid_amount REAL NOT NULL DEFAULT 0.0 CHECK(unpaid_amount >= 0)")
                if not self._column_exists(cursor, 'purchase_invoices', 'payment_status'):
                    cursor.execute("ALTER TABLE purchase_invoices ADD COLUMN payment_status TEXT NOT NULL CHECK(payment_status IN ('unpaid', 'partial', 'paid')) DEFAULT 'unpaid'")
                if not self._column_exists(cursor, 'purchase_invoices', 'shift_id'):
                    cursor.execute("ALTER TABLE purchase_invoices ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")

                cursor.execute("""
                    UPDATE purchase_invoices
                    SET unpaid_amount = total_amount, payment_status = 'unpaid'
                """)

            cursor.execute("INSERT INTO schema_version (version) VALUES (22)")

        # ==========================================
        # V23
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 23")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V23: إضافة نظام القفل المؤقت للحسابات...")
            if self._column_exists(cursor, 'users', 'id'):
                if not self._column_exists(cursor, 'users', 'failed_login_attempts'):
                    cursor.execute("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0")
                if not self._column_exists(cursor, 'users', 'locked_until'):
                    cursor.execute("ALTER TABLE users ADD COLUMN locked_until TIMESTAMP")
            cursor.execute("INSERT INTO schema_version (version) VALUES (23)")

        # ==========================================
        # V24
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 24")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V24: توسيع جدول العملاء/المرضى وفرض التفرد على الهاتف/الإيميل/الهوية...")

            if self._column_exists(cursor, 'customers', 'id'):
                if not self._column_exists(cursor, 'customers', 'national_id'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN national_id TEXT")

                if not self._column_exists(cursor, 'customers', 'date_of_birth'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN date_of_birth DATE")

                if not self._column_exists(cursor, 'customers', 'gender'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN gender TEXT")

                if not self._column_exists(cursor, 'customers', 'address'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN address TEXT")

                if not self._column_exists(cursor, 'customers', 'medical_notes'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN medical_notes TEXT")

                if not self._column_exists(cursor, 'customers', 'is_active'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

                if not self._column_exists(cursor, 'customers', 'updated_at'):
                    cursor.execute("ALTER TABLE customers ADD COLUMN updated_at TIMESTAMP")
                    cursor.execute("""
                        UPDATE customers
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """)

                cursor.execute("""
                    UPDATE customers
                    SET is_active = 1
                    WHERE is_active IS NULL
                """)

                self._normalize_customer_unique_fields(cursor)

            cursor.execute("INSERT INTO schema_version (version) VALUES (24)")

        # ==========================================
        # V25
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 25")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V25: توسيع جدول الموردين/الشركات وفرض التفرد المنطقي...")

            if self._column_exists(cursor, 'suppliers', 'id'):
                if not self._column_exists(cursor, 'suppliers', 'email'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN email TEXT")

                if not self._column_exists(cursor, 'suppliers', 'address'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN address TEXT")

                if not self._column_exists(cursor, 'suppliers', 'notes'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN notes TEXT")

                if not self._column_exists(cursor, 'suppliers', 'is_active'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

                if not self._column_exists(cursor, 'suppliers', 'created_at'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN created_at TIMESTAMP")
                    cursor.execute("""
                        UPDATE suppliers
                        SET created_at = CURRENT_TIMESTAMP
                        WHERE created_at IS NULL
                    """)

                if not self._column_exists(cursor, 'suppliers', 'updated_at'):
                    cursor.execute("ALTER TABLE suppliers ADD COLUMN updated_at TIMESTAMP")
                    cursor.execute("""
                        UPDATE suppliers
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """)

                self._normalize_supplier_unique_fields(cursor)

            cursor.execute("INSERT INTO schema_version (version) VALUES (25)")

        # ==========================================
        # V26
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 26")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V26: إعادة بناء جدول التداخلات الدوائية لتهيئة المتطلب 16...")

            if not self._table_exists(cursor, 'drug_interactions'):
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS drug_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ingredient_1 TEXT NOT NULL,
                        ingredient_2 TEXT NOT NULL,
                        severity TEXT NOT NULL CHECK(severity IN ('minor', 'moderate', 'major', 'contraindicated')),
                        clinical_effect TEXT NOT NULL,
                        recommendation TEXT,
                        management_plan TEXT,
                        source_reference TEXT,
                        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                        created_by_user_id INTEGER NOT NULL,
                        updated_by_user_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                        FOREIGN KEY(updated_by_user_id) REFERENCES users(id),
                        CHECK(length(trim(ingredient_1)) > 0),
                        CHECK(length(trim(ingredient_2)) > 0),
                        CHECK(LOWER(TRIM(ingredient_1)) <> LOWER(TRIM(ingredient_2)))
                    )
                """)
            else:
                required_v26_columns = [
                    "ingredient_1",
                    "ingredient_2",
                    "severity",
                    "clinical_effect",
                    "recommendation",
                    "management_plan",
                    "source_reference",
                    "is_active",
                    "created_by_user_id",
                    "updated_by_user_id",
                    "created_at",
                    "updated_at"
                ]

                needs_rebuild = any(
                    not self._column_exists(cursor, 'drug_interactions', col)
                    for col in required_v26_columns
                )

                if needs_rebuild:
                    cursor.execute("DROP TABLE IF EXISTS drug_interactions_v26_backup")
                    cursor.execute("ALTER TABLE drug_interactions RENAME TO drug_interactions_v26_backup")

                    cursor.execute("""
                        CREATE TABLE drug_interactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ingredient_1 TEXT NOT NULL,
                            ingredient_2 TEXT NOT NULL,
                            severity TEXT NOT NULL CHECK(severity IN ('minor', 'moderate', 'major', 'contraindicated')),
                            clinical_effect TEXT NOT NULL,
                            recommendation TEXT,
                            management_plan TEXT,
                            source_reference TEXT,
                            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                            created_by_user_id INTEGER NOT NULL,
                            updated_by_user_id INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                            FOREIGN KEY(updated_by_user_id) REFERENCES users(id),
                            CHECK(length(trim(ingredient_1)) > 0),
                            CHECK(length(trim(ingredient_2)) > 0),
                            CHECK(LOWER(TRIM(ingredient_1)) <> LOWER(TRIM(ingredient_2)))
                        )
                    """)

                    cursor.execute("PRAGMA table_info(drug_interactions_v26_backup)")
                    backup_columns = [row[1] for row in cursor.fetchall()]

                    cursor.execute("SELECT * FROM drug_interactions_v26_backup ORDER BY id ASC")
                    backup_rows = cursor.fetchall()

                    active_pairs_seen = set()
                    allowed_severities = {'minor', 'moderate', 'major', 'contraindicated'}

                    for row in backup_rows:
                        row_map = dict(zip(backup_columns, row))

                        try:
                            ing_1, ing_2 = self._canonicalize_interaction_pair(
                                row_map.get("ingredient_1"),
                                row_map.get("ingredient_2")
                            )
                        except Exception as ex:
                            logger.warning(
                                f"تم تخطي سجل تداخل دوائي قديم غير صالح أثناء ترقية V26 "
                                f"(id={row_map.get('id')}): {ex}"
                            )
                            continue

                        severity = str(row_map.get("severity") or "moderate").strip().lower()
                        if severity not in allowed_severities:
                            logger.warning(
                                f"شدة تداخل غير صالحة في السجل القديم id={row_map.get('id')}. "
                                "تم استبدالها بالقيمة الافتراضية moderate."
                            )
                            severity = "moderate"

                        clinical_effect = str(
                            row_map.get("clinical_effect")
                            or row_map.get("description")
                            or ""
                        ).strip()
                        if not clinical_effect:
                            clinical_effect = "Legacy interaction record"

                        recommendation = row_map.get("recommendation")
                        management_plan = row_map.get("management_plan")
                        source_reference = row_map.get("source_reference")
                        created_by_user_id = row_map.get("created_by_user_id") or 1
                        updated_by_user_id = row_map.get("updated_by_user_id")
                        created_at = row_map.get("created_at")
                        updated_at = row_map.get("updated_at")
                        original_id = row_map.get("id")

                        pair_key = (ing_1, ing_2)
                        is_active = 1 if pair_key not in active_pairs_seen else 0
                        if is_active == 1:
                            active_pairs_seen.add(pair_key)
                        else:
                            logger.warning(
                                f"تم العثور على تكرار قديم لزوج التداخل ({ing_1}, {ing_2}) "
                                f"أثناء ترقية V26. سيتم الاحتفاظ بالسجل id={original_id} "
                                "كسجل مؤرشف غير فعال."
                            )

                        cursor.execute("""
                            INSERT INTO drug_interactions (
                                id,
                                ingredient_1,
                                ingredient_2,
                                severity,
                                clinical_effect,
                                recommendation,
                                management_plan,
                                source_reference,
                                is_active,
                                created_by_user_id,
                                updated_by_user_id,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                ?,
                                COALESCE(?, CURRENT_TIMESTAMP),
                                COALESCE(?, COALESCE(?, CURRENT_TIMESTAMP))
                            )
                        """, (
                            original_id,
                            ing_1,
                            ing_2,
                            severity,
                            clinical_effect,
                            recommendation,
                            management_plan,
                            source_reference,
                            is_active,
                            created_by_user_id,
                            updated_by_user_id,
                            created_at,
                            updated_at,
                            created_at
                        ))

            cursor.execute("INSERT INTO schema_version (version) VALUES (26)")

        # ==========================================
        # V27
        # ==========================================
        cursor.execute("SELECT version FROM schema_version WHERE version = 27")
        if not cursor.fetchone():
            logger.info("🔄 جاري تنفيذ الترقية V27: إضافة بنية التأمين الصحي الداخلية وتوسيع المعاملات للتحصيلات التأمينية...")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insurance_providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    code TEXT,
                    contact_person TEXT,
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    notes TEXT,
                    default_coverage_percent REAL NOT NULL DEFAULT 80.0 CHECK(default_coverage_percent >= 0 AND default_coverage_percent <= 100),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CHECK(length(trim(name)) > 0)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_insurance_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    provider_id INTEGER NOT NULL,
                    policy_number TEXT NOT NULL,
                    member_number TEXT,
                    default_coverage_percent REAL NOT NULL DEFAULT 80.0 CHECK(default_coverage_percent >= 0 AND default_coverage_percent <= 100),
                    default_patient_share_percent REAL NOT NULL DEFAULT 20.0 CHECK(default_patient_share_percent >= 0 AND default_patient_share_percent <= 100),
                    coverage_limit_amount REAL CHECK(coverage_limit_amount IS NULL OR coverage_limit_amount >= 0),
                    valid_from DATE,
                    valid_to DATE,
                    status TEXT NOT NULL CHECK(status IN ('active', 'expired', 'suspended', 'cancelled')) DEFAULT 'active',
                    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
                    notes TEXT,
                    created_by_user_id INTEGER NOT NULL,
                    updated_by_user_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(customer_id) REFERENCES customers(id),
                    FOREIGN KEY(provider_id) REFERENCES insurance_providers(id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                    FOREIGN KEY(updated_by_user_id) REFERENCES users(id),
                    CHECK(length(trim(policy_number)) > 0),
                    CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
                    CHECK(default_coverage_percent + default_patient_share_percent <= 100)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insurance_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_number TEXT NOT NULL UNIQUE,
                    provider_id INTEGER NOT NULL,
                    policy_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    prescription_id INTEGER,
                    sale_id INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'submitted', 'approved', 'partially_approved', 'rejected', 'collected', 'cancelled')) DEFAULT 'draft',
                    service_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    claim_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    gross_amount REAL NOT NULL DEFAULT 0.0 CHECK(gross_amount >= 0),
                    insurer_amount REAL NOT NULL DEFAULT 0.0 CHECK(insurer_amount >= 0),
                    patient_amount REAL NOT NULL DEFAULT 0.0 CHECK(patient_amount >= 0),
                    approved_amount REAL NOT NULL DEFAULT 0.0 CHECK(approved_amount >= 0),
                    collected_amount REAL NOT NULL DEFAULT 0.0 CHECK(collected_amount >= 0),
                    external_claim_number TEXT,
                    submission_notes TEXT,
                    decision_notes TEXT,
                    rejection_reason TEXT,
                    created_by_user_id INTEGER NOT NULL,
                    updated_by_user_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(provider_id) REFERENCES insurance_providers(id),
                    FOREIGN KEY(policy_id) REFERENCES customer_insurance_policies(id),
                    FOREIGN KEY(customer_id) REFERENCES customers(id),
                    FOREIGN KEY(prescription_id) REFERENCES prescriptions(id),
                    FOREIGN KEY(sale_id) REFERENCES sales(id),
                    FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                    FOREIGN KEY(updated_by_user_id) REFERENCES users(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insurance_claim_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id INTEGER NOT NULL,
                    sale_item_id INTEGER,
                    prescription_item_id INTEGER,
                    medicine_id INTEGER NOT NULL,
                    batch_id INTEGER,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    unit_price REAL NOT NULL DEFAULT 0.0 CHECK(unit_price >= 0),
                    gross_amount REAL NOT NULL DEFAULT 0.0 CHECK(gross_amount >= 0),
                    covered_amount REAL NOT NULL DEFAULT 0.0 CHECK(covered_amount >= 0),
                    patient_amount REAL NOT NULL DEFAULT 0.0 CHECK(patient_amount >= 0),
                    approval_status TEXT NOT NULL CHECK(approval_status IN ('pending', 'approved', 'partial', 'rejected')) DEFAULT 'pending',
                    rejection_reason TEXT,
                    notes TEXT,
                    FOREIGN KEY(claim_id) REFERENCES insurance_claims(id) ON DELETE CASCADE,
                    FOREIGN KEY(sale_item_id) REFERENCES sale_items(id),
                    FOREIGN KEY(prescription_item_id) REFERENCES prescription_items(id),
                    FOREIGN KEY(medicine_id) REFERENCES medicines(id),
                    FOREIGN KEY(batch_id) REFERENCES batches(id),
                    UNIQUE(claim_id, sale_item_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insurance_collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id INTEGER NOT NULL,
                    collection_reference TEXT,
                    collection_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    amount REAL NOT NULL CHECK(amount > 0),
                    payment_method TEXT NOT NULL CHECK(payment_method IN ('cash', 'bank_transfer', 'check', 'other')) DEFAULT 'bank_transfer',
                    user_id INTEGER NOT NULL,
                    shift_id INTEGER,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(claim_id) REFERENCES insurance_claims(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(shift_id) REFERENCES shifts(id)
                )
            """)

            if self._column_exists(cursor, 'transactions', 'id'):
                cursor.execute("DROP TABLE IF EXISTS transactions_v27_backup")
                cursor.execute("ALTER TABLE transactions RENAME TO transactions_v27_backup")
                cursor.execute("""
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        transaction_type TEXT NOT NULL CHECK(transaction_type IN ('in', 'out')),
                        reference_type TEXT NOT NULL CHECK(reference_type IN (
                            'sale', 'purchase', 'expense', 'return', 'disposal',
                            'return_void', 'expense_void', 'shift_opening',
                            'shift_closing_adjustment', 'cash_drop', 'cash_over_short',
                            'insurance_collection'
                        )),
                        reference_id INTEGER,
                        amount REAL NOT NULL CHECK(amount >= 0),
                        user_id INTEGER NOT NULL,
                        shift_id INTEGER,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(shift_id) REFERENCES shifts(id)
                    )
                """)
                try:
                    cursor.execute("""
                        INSERT INTO transactions (id, transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes, created_at)
                        SELECT id, transaction_type, reference_type, reference_id, amount, user_id, shift_id, notes, created_at
                        FROM transactions_v27_backup
                    """)
                except Exception as e:
                    logger.warning(f"Could not migrate transactions during V27 upgrade: {e}")

            cursor.execute("INSERT INTO schema_version (version) VALUES (27)")

    # ==========================================
    # الفهارس والـ Triggers
    # ==========================================
    def _create_triggers_and_indexes(self, conn):
        cursor = conn.cursor()

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
            "CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name)",
            "CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name)",
            "CREATE INDEX IF NOT EXISTS idx_suppliers_company_name ON suppliers(company_name)",
            "CREATE INDEX IF NOT EXISTS idx_suppliers_active_name ON suppliers(is_active, name)",
            "CREATE INDEX IF NOT EXISTS idx_medicines_barcode ON medicines(barcode)",
            "CREATE INDEX IF NOT EXISTS idx_batches_med_id_expiry ON batches(medicine_id, expiry_date)",
            "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_ref ON transactions(reference_type, reference_id)",
            "CREATE INDEX IF NOT EXISTS idx_returns_sale_id ON returns(sale_id)",
            "CREATE INDEX IF NOT EXISTS idx_return_items_return_id ON return_items(return_id)",
            "CREATE INDEX IF NOT EXISTS idx_return_items_sale_item_id ON return_items(sale_item_id)",
            "CREATE INDEX IF NOT EXISTS idx_return_items_batch_id ON return_items(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_category_id ON expenses(category_id)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)",
            "CREATE INDEX IF NOT EXISTS idx_disposals_date ON disposals(disposal_date)",
            "CREATE INDEX IF NOT EXISTS idx_disposal_items_disp_id ON disposal_items(disposal_id)",
            "CREATE INDEX IF NOT EXISTS idx_doctors_name ON doctors(name)",
            "CREATE INDEX IF NOT EXISTS idx_prescriptions_number ON prescriptions(prescription_number)",
            "CREATE INDEX IF NOT EXISTS idx_ctrl_log_sale_id ON controlled_dispensing_log(sale_id)",
            "CREATE INDEX IF NOT EXISTS idx_shifts_user_status ON shifts(user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_sales_shift ON sales(shift_id)",
            "CREATE INDEX IF NOT EXISTS idx_returns_shift ON returns(shift_id)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_shift ON expenses(shift_id)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_payee_type ON expenses(payee_type)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_status_shift ON expenses(status, shift_id)",
            "CREATE INDEX IF NOT EXISTS idx_ctrl_ret_log_status ON controlled_return_log(status)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_shift_created_at ON transactions(shift_id, created_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_closures_date ON daily_closures(business_date)",
            "CREATE INDEX IF NOT EXISTS idx_dcs_closure_id ON daily_closure_shifts(daily_closure_id)",
            "CREATE INDEX IF NOT EXISTS idx_dcs_shift_id ON daily_closure_shifts(shift_id)",

            # Unique Partial Indexes للعملاء/المرضى
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_phone_not_null ON customers(TRIM(phone)) WHERE phone IS NOT NULL AND TRIM(phone) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_email_not_null ON customers(LOWER(TRIM(email))) WHERE email IS NOT NULL AND TRIM(email) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_national_id_not_null ON customers(TRIM(national_id)) WHERE national_id IS NOT NULL AND TRIM(national_id) <> ''",

            # Unique Partial Indexes للموردين/الشركات
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_identity_active ON suppliers(LOWER(TRIM(name)), LOWER(TRIM(COALESCE(company_name, '')))) WHERE is_active = 1 AND name IS NOT NULL AND TRIM(name) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_email_active ON suppliers(LOWER(TRIM(email))) WHERE is_active = 1 AND email IS NOT NULL AND TRIM(email) <> ''",

            # فهارس التداخلات الدوائية
            "CREATE INDEX IF NOT EXISTS idx_drug_interactions_ing1_norm ON drug_interactions(LOWER(TRIM(ingredient_1)))",
            "CREATE INDEX IF NOT EXISTS idx_drug_interactions_ing2_norm ON drug_interactions(LOWER(TRIM(ingredient_2)))",
            "CREATE INDEX IF NOT EXISTS idx_drug_interactions_active_severity ON drug_interactions(is_active, severity)",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_drug_interactions_pair_active
            ON drug_interactions(
                CASE
                    WHEN LOWER(TRIM(ingredient_1)) <= LOWER(TRIM(ingredient_2))
                        THEN LOWER(TRIM(ingredient_1))
                    ELSE LOWER(TRIM(ingredient_2))
                END,
                CASE
                    WHEN LOWER(TRIM(ingredient_1)) <= LOWER(TRIM(ingredient_2))
                        THEN LOWER(TRIM(ingredient_2))
                    ELSE LOWER(TRIM(ingredient_1))
                END
            )
            WHERE is_active = 1
            """,

            # V27: فهارس التأمين
            "CREATE INDEX IF NOT EXISTS idx_insurance_providers_name ON insurance_providers(name)",
            "CREATE INDEX IF NOT EXISTS idx_insurance_providers_active_name ON insurance_providers(is_active, name)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_insurance_providers_name_active ON insurance_providers(LOWER(TRIM(name))) WHERE is_active = 1 AND name IS NOT NULL AND TRIM(name) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_insurance_providers_code_not_null ON insurance_providers(LOWER(TRIM(code))) WHERE code IS NOT NULL AND TRIM(code) <> ''",

            "CREATE INDEX IF NOT EXISTS idx_ins_policies_customer_status ON customer_insurance_policies(customer_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ins_policies_provider_status ON customer_insurance_policies(provider_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ins_policies_validity ON customer_insurance_policies(valid_from, valid_to)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ins_policy_number_provider ON customer_insurance_policies(provider_id, TRIM(policy_number)) WHERE policy_number IS NOT NULL AND TRIM(policy_number) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ins_member_number_provider ON customer_insurance_policies(provider_id, TRIM(member_number)) WHERE member_number IS NOT NULL AND TRIM(member_number) <> ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ins_default_policy_per_customer ON customer_insurance_policies(customer_id) WHERE is_default = 1 AND status = 'active'",

            "CREATE INDEX IF NOT EXISTS idx_ins_claims_status ON insurance_claims(status)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_provider_status ON insurance_claims(provider_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_customer_status ON insurance_claims(customer_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_policy ON insurance_claims(policy_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_sale ON insurance_claims(sale_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_prescription ON insurance_claims(prescription_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claims_service_date ON insurance_claims(service_date)",

            "CREATE INDEX IF NOT EXISTS idx_ins_claim_items_claim_id ON insurance_claim_items(claim_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claim_items_medicine_id ON insurance_claim_items(medicine_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claim_items_sale_item_id ON insurance_claim_items(sale_item_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claim_items_prescription_item_id ON insurance_claim_items(prescription_item_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_claim_items_approval_status ON insurance_claim_items(approval_status)",

            "CREATE INDEX IF NOT EXISTS idx_ins_collections_claim_id ON insurance_collections(claim_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_collections_shift_id ON insurance_collections(shift_id)",
            "CREATE INDEX IF NOT EXISTS idx_ins_collections_date ON insurance_collections(collection_date)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ins_collection_reference_not_null ON insurance_collections(TRIM(collection_reference)) WHERE collection_reference IS NOT NULL AND TRIM(collection_reference) <> ''"
        ]

        for idx in indexes:
            cursor.execute(idx)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_shifts_one_open_per_user ON shifts(user_id) WHERE status = 'open'"
        )

        triggers = [
            """
            CREATE TRIGGER IF NOT EXISTS trg_users_updated_at
            AFTER UPDATE ON users
            BEGIN
                UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_suppliers_updated_at
            AFTER UPDATE ON suppliers
            BEGIN
                UPDATE suppliers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_customers_updated_at
            AFTER UPDATE ON customers
            BEGIN
                UPDATE customers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_drug_interactions_updated_at
            AFTER UPDATE ON drug_interactions
            BEGIN
                UPDATE drug_interactions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_insurance_providers_updated_at
            AFTER UPDATE ON insurance_providers
            BEGIN
                UPDATE insurance_providers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_customer_insurance_policies_updated_at
            AFTER UPDATE ON customer_insurance_policies
            BEGIN
                UPDATE customer_insurance_policies SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_insurance_claims_updated_at
            AFTER UPDATE ON insurance_claims
            BEGIN
                UPDATE insurance_claims SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_insurance_collections_after_insert
            AFTER INSERT ON insurance_collections
            BEGIN
                UPDATE insurance_claims
                SET collected_amount = (
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM insurance_collections
                    WHERE claim_id = NEW.claim_id
                )
                WHERE id = NEW.claim_id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_insurance_collections_after_update
            AFTER UPDATE ON insurance_collections
            BEGIN
                UPDATE insurance_claims
                SET collected_amount = (
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM insurance_collections
                    WHERE claim_id = NEW.claim_id
                )
                WHERE id = NEW.claim_id;

                UPDATE insurance_claims
                SET collected_amount = (
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM insurance_collections
                    WHERE claim_id = OLD.claim_id
                )
                WHERE id = OLD.claim_id AND OLD.claim_id <> NEW.claim_id;
            END;
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_insurance_collections_after_delete
            AFTER DELETE ON insurance_collections
            BEGIN
                UPDATE insurance_claims
                SET collected_amount = (
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM insurance_collections
                    WHERE claim_id = OLD.claim_id
                )
                WHERE id = OLD.claim_id;
            END;
            """
        ]

        for trg in triggers:
            cursor.execute(trg)

    # ==========================================
    # زرع المدير الافتراضي
    # ==========================================
    def _seed_admin(self, conn):
        """
        تحديث أمني ومعماري:
        1. تم إلغاء الكلمة الافتراضية الثابتة نهائياً (Fail-Safe Bootstrap).
        2. الاستيراد يتم من core.security.password_utils مباشرة لمنع التشابك.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")

        if not cursor.fetchone():
            default_admin_password = os.getenv("PHARMASYS_ADMIN_PASSWORD")

            if not default_admin_password:
                error_msg = (
                    "CRITICAL SECURITY HALT: لا يمكن إقلاع النظام بقاعدة بيانات فارغة "
                    "دون تحديد متغير البيئة PHARMASYS_ADMIN_PASSWORD. "
                    "يُمنع استخدام كلمات مرور افتراضية لحماية النظام."
                )
                logger.critical(error_msg)
                raise RuntimeError(error_msg)

            from core.security.password_utils import PasswordUtils

            is_strong, msg = PasswordUtils.validate_password_strength(default_admin_password)
            if not is_strong:
                error_msg = f"CRITICAL SECURITY HALT: كلمة مرور المدير في متغير البيئة ضعيفة. {msg}"
                logger.critical(error_msg)
                raise RuntimeError(error_msg)

            admin_pass_hash = PasswordUtils.hash_password(default_admin_password)

            cursor.execute("""
                INSERT INTO users (username, password_hash, role, is_active, must_change_password)
                VALUES (?, ?, ?, ?, ?)
            """, ('admin', admin_pass_hash, 'admin', 1, 1))
            logger.info("✅ تم زرع حساب المدير الافتراضي بنجاح (Fail-Safe Bootstrap).")


if __name__ == "__main__":
    db = DatabaseManager()