from database.db_manager import DatabaseManager


class ReportsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # --- 1. قسم المبيعات ---
    def get_all_sales(self):
        """جلب كل الفواتير مع اسم البائع واسم العميل"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            # نستخدم LEFT JOIN مع العملاء لأن العميل قد يكون NULL (نقدي)
            query = """
                SELECT s.id, u.username, c.name, s.total_amount, s.sale_date 
                FROM sales s 
                JOIN users u ON s.user_id = u.id 
                LEFT JOIN customers c ON s.customer_id = c.id
                ORDER BY s.sale_date DESC
            """
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def get_sale_details(self, sale_id):
        """جلب تفاصيل الأدوية داخل فاتورة بيع"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """
                SELECT m.name, si.quantity, si.price_at_sale, si.total_item_price
                FROM sale_items si
                JOIN medicines m ON si.medicine_id = m.id
                WHERE si.sale_id = ?
            """
            cursor.execute(query, (sale_id,))
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    # --- 2. قسم المشتريات ---
    def get_all_purchases(self):
        """جلب سجل فواتير الشراء"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """
                SELECT p.id, s.name, p.invoice_number, p.total_amount, p.invoice_date
                FROM purchase_invoices p
                JOIN suppliers s ON p.supplier_id = s.id
                ORDER BY p.invoice_date DESC
            """
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    def get_purchase_details(self, purchase_id):
        """جلب تفاصيل فاتورة الشراء"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            query = """
                SELECT m.name, pi.quantity, pi.unit_cost, pi.total_cost
                FROM purchase_items pi
                JOIN medicines m ON pi.medicine_id = m.id
                WHERE pi.purchase_id = ?
            """
            cursor.execute(query, (purchase_id,))
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    # --- 3. قسم النواقص (Low Stock) ---
    def get_low_stock_items(self):
        """جلب الأدوية التي قلت كميتها عن الحد المسموح"""
        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            # نجلب اسم المورد أيضاً لتسهيل الطلب
            query = """
                SELECT m.barcode, m.name, m.quantity, s.name 
                FROM medicines m
                LEFT JOIN suppliers s ON m.supplier_id = s.id
                WHERE m.quantity <= m.min_stock_alert
            """
            cursor.execute(query)
            data = cursor.fetchall()
            conn.close()
            return data
        return []

    # --- 4. الملخص المالي ---
    def get_financial_summary(self):
        """حساب إجمالي المبيعات والمشتريات والربح"""
        conn = self.db.connect()
        summary = {"sales": 0.0, "purchases": 0.0, "profit": 0.0}

        if conn:
            cursor = conn.cursor()
            try:
                # إجمالي المبيعات
                cursor.execute("SELECT SUM(total_amount) FROM sales")
                res_sales = cursor.fetchone()[0]
                summary["sales"] = res_sales if res_sales else 0.0

                # إجمالي المشتريات
                cursor.execute("SELECT SUM(total_amount) FROM purchase_invoices")
                res_purchases = cursor.fetchone()[0]
                summary["purchases"] = res_purchases if res_purchases else 0.0

                # صافي الدخل (حسب طلبك: مبيعات - مشتريات)
                summary["profit"] = summary["sales"] - summary["purchases"]

            except Exception as e:
                print(f"Error calculating summary: {e}")
            finally:
                conn.close()
        return summary