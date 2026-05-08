"""
وظيفة الملف: كائن الوصول لبيانات لوحة التحكم (Dashboard DAO).
الطبقة: Data Access Layer / Data Aggregator
ملاحظة معمارية:
- يطبق هذا الملف نمط (Consumer)، حيث لا يقوم بإعادة كتابة أي استعلامات مالية أو مخزنية.
- يستدعي الدوال المركزية من (ReportsDAO) ويستخلص منها المؤشرات (KPIs) المجمعة.
- تم الفصل المحاسبي بصرامة بين (المصروفات التشغيلية) و (خسائر الإتلاف) كبندين مستقلين يخصمان من الربح الإجمالي.
"""
from database.db_manager import DatabaseManager
from models.reports_dao import ReportsDAO
from datetime import datetime
import logging
logger = logging.getLogger(__name__)

class DashboardDAO:
    def __init__(self):
        self.db = DatabaseManager()
        self.reports_dao = ReportsDAO()  # حقن التبعية (Dependency Injection) لمحرك التقارير

    def get_dashboard_kpis(self):
        """
        تجميع مؤشرات الأداء الرئيسية (KPIs) لعرضها في لوحة التحكم.
        يعتمد كلياً على ReportsDAO للمعلومات المالية والمخزنية.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 1. استدعاء الحقائق المحاسبية ليومنا الحالي من ReportsDAO
        sales_summary = self.reports_dao.get_sales_and_returns_summary(start_date=today_str, end_date=today_str) or {}
        cash_flow = self.reports_dao.get_cash_flow_summary(start_date=today_str, end_date=today_str) or {}

        # استدعاء دالة صافي الربح الشاملة (تجلب هامش الربح، المصروفات، خسائر الإتلاف، وصافي الربح دفعة واحدة)
        net_profit_summary = self.reports_dao.get_net_profit_summary(start_date=today_str, end_date=today_str) or {}

        # 2. استدعاء الحقائق المخزنية الحالية
        inventory_report = self.reports_dao.get_inventory_operational_report() or {}

        # 3. بناء قاموس المؤشرات (KPIs Dictionary)
        kpis = {
            # المؤشرات المالية للبيع (لليوم الحالي)
            "today_gross_sales": sales_summary.get("gross_sales", 0.0),
            "today_total_returns": sales_summary.get("total_returns", 0.0),
            "today_net_sales": sales_summary.get("net_sales", 0.0),

            # مؤشرات التدفق النقدي (لليوم الحالي)
            "today_cash_in": cash_flow.get("total_in", 0.0),
            "today_cash_out": cash_flow.get("total_out", 0.0),

            # مؤشرات الربحية، المصروفات، والهدر (الفصل المحاسبي الصارم)
            "today_gross_profit": net_profit_summary.get("gross_profit", 0.0),
            "today_expenses": net_profit_summary.get("operating_expenses", 0.0),
            "today_disposal_losses": net_profit_summary.get("disposal_losses", 0.0), # <-- البند المستقل الجديد
            "today_net_profit": net_profit_summary.get("net_profit", 0.0),

            # المؤشرات المخزنية (لحظية)
            "low_stock_count": len(inventory_report.get("low_stock", [])),
            "expiring_soon_count": len(inventory_report.get("expiring_soon", [])),
            "expired_count": len(inventory_report.get("expired", [])),

            # الكيانات العامة
            "total_medicines": 0,
            "users_count": 0
        }

        # 4. جلب الإحصائيات البسيطة غير المعقدة (أعداد الكيانات فقط) عبر استعلام مباشر
        conn = self.db.connect()
        if conn:
            try:
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(id) FROM medicines")
                res = cursor.fetchone()
                kpis["total_medicines"] = res[0] if res else 0

                cursor.execute("SELECT COUNT(id) FROM users WHERE is_active = 1")
                res = cursor.fetchone()
                kpis["users_count"] = res[0] if res else 0

            except Exception as e:
                logger.error(f"Error fetching generic counts for dashboard: {e}")
            finally:
                conn.close()

        return kpis