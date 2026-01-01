from database.db_manager import DatabaseManager
from datetime import datetime

class DashboardDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def get_statistics(self):
        """جلب إحصائيات عامة للنظام (شاملة القديم والجديد)"""
        stats = {
            "total_medicines": 0,
            "low_stock": 0,
            "today_sales": 0.0,
            "users_count": 0,    # الميزة الموجودة سابقاً (سنبقيها)
            "expiring_soon": 0   # الميزة الجديدة (تنبيه الصلاحية)
        }

        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            try:
                # 1. عدد الأدوية الكلي
                cursor.execute("SELECT COUNT(*) FROM medicines")
                stats["total_medicines"] = cursor.fetchone()[0]

                # 2. الأدوية التي وصلت للحد الأدنى (النواقص)
                cursor.execute("SELECT COUNT(*) FROM medicines WHERE quantity <= min_stock_alert")
                stats["low_stock"] = cursor.fetchone()[0]

                # 3. مبيعات اليوم
                today = datetime.now().strftime("%Y-%m-%d")
                cursor.execute("SELECT SUM(total_amount) FROM sales WHERE date(sale_date) = ?", (today,))
                result = cursor.fetchone()[0]
                stats["today_sales"] = result if result else 0.0

                # 4. عدد المستخدمين (كما في كودك الأصلي)
                cursor.execute("SELECT COUNT(*) FROM users")
                stats["users_count"] = cursor.fetchone()[0]

                # 5. الميزة الجديدة: صلاحية قريبة (خلال 90 يوم من اليوم)
                cursor.execute("""
                    SELECT COUNT(*) FROM medicines 
                    WHERE expiry_date BETWEEN ? AND date(?, '+90 days')
                """, (today, today))
                stats["expiring_soon"] = cursor.fetchone()[0]

            except Exception as e:
                print(f"Error fetching stats: {e}")
            finally:
                conn.close()

        return stats