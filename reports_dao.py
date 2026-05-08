"""
وظيفة الملف: كائن الوصول لبيانات التقارير المالية والتشغيلية (Reports DAO).
الطبقة: Data Access Layer

ملاحظة معمارية ومحاسبية هامة:
- يتم الحفاظ على استقلالية "هامش الربح الإجمالي" (Gross Profit) عن "الربح الصافي" (Net Profit).
- يتم حساب تكلفة البضاعة المباعة (COGS) بدقة قدر الإمكان وفق الأعمدة المتاحة فعلياً في قاعدة البيانات.
- التدفق النقدي (Cash Flow) يُقرأ حصراً من جدول (transactions).
- المخزون والنواقص تُقرأ حصراً من جدول التشغيلات (batches).
- تم بناء الملف بصيغة Schema-Aware لتفادي إعادة الصفر بصمت عند اختلاف أسماء الأعمدة.
"""

from database.db_manager import DatabaseManager
import logging

logger = logging.getLogger(__name__)


class ReportsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # أدوات داخلية عامة (Schema-Aware Helpers)
    # ==========================================
    def _table_exists(self, cursor, table_name):
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,)
        )
        return cursor.fetchone() is not None

    def _get_table_columns(self, cursor, table_name):
        if not self._table_exists(cursor, table_name):
            return set()

        cursor.execute(f"PRAGMA table_info({table_name})")
        rows = cursor.fetchall()
        return {row[1] for row in rows}

    def _choose_column(self, cursor, table_name, candidates):
        columns = self._get_table_columns(cursor, table_name)
        for col in candidates:
            if col in columns:
                return col
        return None

    def _build_date_condition(
        self,
        cursor,
        table_name,
        alias,
        candidate_columns,
        start_date=None,
        end_date=None,
        joiner="WHERE"
    ):
        """
        يبني شرط تاريخ آمن بناءً على العمود الموجود فعلياً.
        """
        if not start_date or not end_date:
            return "", []

        date_col = self._choose_column(cursor, table_name, candidate_columns)
        if not date_col:
            logger.warning(
                "لم يتم العثور على عمود تاريخ مناسب في الجدول '%s'. سيتم تجاهل فلتر التاريخ.",
                table_name
            )
            return "", []

        prefix = f"{alias}." if alias else ""
        condition = f" {joiner} date({prefix}{date_col}) BETWEEN date(?) AND date(?) "
        return condition, [start_date, end_date]

    def _safe_scalar(self, cursor, query, params=None, default=0.0):
        try:
            cursor.execute(query, params or [])
            row = cursor.fetchone()
            if not row or row[0] is None:
                return default
            return row[0]
        except Exception:
            logger.exception("فشل تنفيذ استعلام scalar: %s", query)
            return default

    # ==========================================
    # المحور الأول: تقارير المبيعات والمرتجعات
    # ==========================================
    def get_sales_and_returns_summary(self, start_date=None, end_date=None):
        summary = {
            "gross_sales": 0.0,
            "total_returns": 0.0,
            "net_sales": 0.0
        }

        conn = self.db.connect()
        if not conn:
            return summary

        try:
            cursor = conn.cursor()

            # ---- المبيعات ----
            if self._table_exists(cursor, "sales"):
                sales_amount_col = self._choose_column(
                    cursor,
                    "sales",
                    ["total_amount", "net_total", "amount"]
                )

                if sales_amount_col:
                    sales_where, sales_params = self._build_date_condition(
                        cursor,
                        table_name="sales",
                        alias="s",
                        candidate_columns=["sale_date", "created_at", "date"],
                        start_date=start_date,
                        end_date=end_date,
                        joiner="WHERE"
                    )

                    sales_query = f"""
                        SELECT COALESCE(SUM(s.{sales_amount_col}), 0)
                        FROM sales s
                        {sales_where}
                    """
                    summary["gross_sales"] = float(
                        self._safe_scalar(cursor, sales_query, sales_params, 0.0)
                    )

            # ---- المرتجعات ----
            if self._table_exists(cursor, "returns"):
                returns_amount_col = self._choose_column(
                    cursor,
                    "returns",
                    ["total_amount", "refund_amount", "returned_amount", "amount"]
                )

                if returns_amount_col:
                    returns_where, returns_params = self._build_date_condition(
                        cursor,
                        table_name="returns",
                        alias="r",
                        candidate_columns=["return_date", "created_at", "date"],
                        start_date=start_date,
                        end_date=end_date,
                        joiner="WHERE"
                    )

                    returns_query = f"""
                        SELECT COALESCE(SUM(r.{returns_amount_col}), 0)
                        FROM returns r
                        {returns_where}
                    """
                    summary["total_returns"] = float(
                        self._safe_scalar(cursor, returns_query, returns_params, 0.0)
                    )

            summary["net_sales"] = summary["gross_sales"] - summary["total_returns"]

        except Exception:
            logger.exception("خطأ أثناء جلب ملخص المبيعات والمرتجعات.")
        finally:
            conn.close()

        return summary

    # ==========================================
    # المحور الثاني: تقارير التدفق النقدي (Cash Flow)
    # ==========================================
    def get_cash_flow_summary(self, start_date=None, end_date=None):
        cash_flow = {
            "total_in": 0.0,
            "total_out": 0.0,
            "net_balance": 0.0,
            "breakdown": {}
        }

        conn = self.db.connect()
        if not conn:
            return cash_flow

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "transactions"):
                logger.warning("جدول transactions غير موجود.")
                return cash_flow

            t_type_col = self._choose_column(cursor, "transactions", ["transaction_type", "type"])
            ref_type_col = self._choose_column(cursor, "transactions", ["reference_type", "ref_type", "source_type"])
            amount_col = self._choose_column(cursor, "transactions", ["amount", "total_amount", "value"])

            if not t_type_col or not ref_type_col or not amount_col:
                logger.warning("بعض الأعمدة الجوهرية غير موجودة في transactions.")
                return cash_flow

            date_where, params = self._build_date_condition(
                cursor,
                table_name="transactions",
                alias="t",
                candidate_columns=["created_at", "transaction_date", "date"],
                start_date=start_date,
                end_date=end_date,
                joiner="WHERE"
            )

            query = f"""
                SELECT t.{t_type_col}, t.{ref_type_col}, COALESCE(SUM(t.{amount_col}), 0)
                FROM transactions t
                {date_where}
                GROUP BY t.{t_type_col}, t.{ref_type_col}
            """
            cursor.execute(query, params)
            rows = cursor.fetchall()

            for t_type, r_type, amount in rows:
                amount = float(amount or 0.0)

                if t_type == "in":
                    cash_flow["total_in"] += amount
                elif t_type == "out":
                    cash_flow["total_out"] += amount

                key = f"{t_type}_{r_type}"
                cash_flow["breakdown"][key] = amount

            cash_flow["net_balance"] = cash_flow["total_in"] - cash_flow["total_out"]

        except Exception:
            logger.exception("خطأ أثناء جلب التدفق النقدي.")
        finally:
            conn.close()

        return cash_flow

    # ==========================================
    # المحور الثالث: هامش الربح الإجمالي (Gross Profit)
    # ==========================================
    def get_gross_profit_summary(self, start_date=None, end_date=None):
        profit_summary = {
            "net_sales": 0.0,
            "sales_cogs": 0.0,
            "returns_cogs": 0.0,
            "net_cogs": 0.0,
            "gross_profit": 0.0
        }

        conn = self.db.connect()
        if not conn:
            return profit_summary

        try:
            cursor = conn.cursor()

            sales_data = self.get_sales_and_returns_summary(start_date, end_date)
            profit_summary["net_sales"] = float(sales_data.get("net_sales", 0.0))

            # ---- Cost of sold goods ----
            if (
                self._table_exists(cursor, "sale_items")
                and self._table_exists(cursor, "sales")
            ):
                cogs_expr = None
                sale_items_cols = self._get_table_columns(cursor, "sale_items")

                if "buy_price_at_sale" in sale_items_cols:
                    cogs_expr = "si.quantity * COALESCE(si.buy_price_at_sale, 0)"
                elif "unit_cost_at_sale" in sale_items_cols:
                    cogs_expr = "si.quantity * COALESCE(si.unit_cost_at_sale, 0)"
                elif "buy_price" in sale_items_cols:
                    cogs_expr = "si.quantity * COALESCE(si.buy_price, 0)"
                elif self._table_exists(cursor, "batches"):
                    cogs_expr = "si.quantity * COALESCE(b.buy_price, 0)"

                if cogs_expr:
                    sales_where, sales_params = self._build_date_condition(
                        cursor,
                        table_name="sales",
                        alias="s",
                        candidate_columns=["sale_date", "created_at", "date"],
                        start_date=start_date,
                        end_date=end_date,
                        joiner="WHERE"
                    )

                    join_batch = "LEFT JOIN batches b ON si.batch_id = b.id" if self._table_exists(cursor, "batches") else ""
                    cogs_query = f"""
                        SELECT COALESCE(SUM({cogs_expr}), 0)
                        FROM sale_items si
                        JOIN sales s ON si.sale_id = s.id
                        {join_batch}
                        {sales_where}
                    """
                    profit_summary["sales_cogs"] = float(
                        self._safe_scalar(cursor, cogs_query, sales_params, 0.0)
                    )

            # ---- Cost of returned goods ----
            if (
                self._table_exists(cursor, "return_items")
                and self._table_exists(cursor, "returns")
            ):
                returns_expr = None
                return_items_cols = self._get_table_columns(cursor, "return_items")

                if "buy_price_at_return" in return_items_cols:
                    returns_expr = "ri.quantity * COALESCE(ri.buy_price_at_return, 0)"
                elif "unit_cost_at_return" in return_items_cols:
                    returns_expr = "ri.quantity * COALESCE(ri.unit_cost_at_return, 0)"
                elif "buy_price" in return_items_cols:
                    returns_expr = "ri.quantity * COALESCE(ri.buy_price, 0)"
                elif self._table_exists(cursor, "batches"):
                    returns_expr = "ri.quantity * COALESCE(b.buy_price, 0)"

                if returns_expr:
                    returns_where, returns_params = self._build_date_condition(
                        cursor,
                        table_name="returns",
                        alias="r",
                        candidate_columns=["return_date", "created_at", "date"],
                        start_date=start_date,
                        end_date=end_date,
                        joiner="WHERE"
                    )

                    join_batch = "LEFT JOIN batches b ON ri.batch_id = b.id" if self._table_exists(cursor, "batches") else ""
                    returns_cogs_query = f"""
                        SELECT COALESCE(SUM({returns_expr}), 0)
                        FROM return_items ri
                        JOIN returns r ON ri.return_id = r.id
                        {join_batch}
                        {returns_where}
                    """
                    profit_summary["returns_cogs"] = float(
                        self._safe_scalar(cursor, returns_cogs_query, returns_params, 0.0)
                    )

            profit_summary["net_cogs"] = profit_summary["sales_cogs"] - profit_summary["returns_cogs"]
            profit_summary["gross_profit"] = profit_summary["net_sales"] - profit_summary["net_cogs"]

        except Exception:
            logger.exception("خطأ أثناء حساب هامش الربح الإجمالي.")
        finally:
            conn.close()

        return profit_summary

    # ==========================================
    # المحور الرابع: تقارير المخزون التشغيلية (Inventory)
    # ==========================================
    def get_inventory_operational_report(self):
        inventory_report = {
            "low_stock": [],
            "expiring_soon": [],
            "expired": []
        }

        conn = self.db.connect()
        if not conn:
            return inventory_report

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "medicines") or not self._table_exists(cursor, "batches"):
                logger.warning("تعذر بناء تقرير المخزون لأن أحد الجدولين medicines/batches غير موجود.")
                return inventory_report

            min_stock_col = self._choose_column(
                cursor,
                "medicines",
                ["min_stock_alert", "min_stock", "reorder_level"]
            )
            if not min_stock_col:
                min_stock_col = "0"

            query_low = f"""
                SELECT
                    m.id,
                    m.barcode,
                    m.name,
                    COALESCE(SUM(b.quantity), 0) AS sellable_qty,
                    {('m.' + min_stock_col) if min_stock_col != '0' else '0'} AS min_stock_limit
                FROM medicines m
                LEFT JOIN batches b
                    ON m.id = b.medicine_id
                   AND b.status = 'active'
                   AND b.quantity > 0
                   AND b.expiry_date >= date('now')
                GROUP BY m.id
                HAVING sellable_qty <= min_stock_limit
                ORDER BY m.name ASC
            """
            cursor.execute(query_low)
            inventory_report["low_stock"] = cursor.fetchall()

            query_expiring = """
                SELECT m.barcode, m.name, b.batch_number, b.quantity, b.expiry_date
                FROM batches b
                JOIN medicines m ON b.medicine_id = m.id
                WHERE b.quantity > 0
                  AND b.expiry_date BETWEEN date('now') AND date('now', '+90 days')
                ORDER BY b.expiry_date ASC
            """
            cursor.execute(query_expiring)
            inventory_report["expiring_soon"] = cursor.fetchall()

            query_expired = """
                SELECT m.barcode, m.name, b.batch_number, b.quantity, b.expiry_date
                FROM batches b
                JOIN medicines m ON b.medicine_id = m.id
                WHERE b.quantity > 0
                  AND b.expiry_date < date('now')
                ORDER BY b.expiry_date ASC
            """
            cursor.execute(query_expired)
            inventory_report["expired"] = cursor.fetchall()

        except Exception:
            logger.exception("خطأ أثناء جلب تقرير المخزون التشغيلي.")
        finally:
            conn.close()

        return inventory_report

    # ==========================================
    # المحور الخامس: المصروفات التشغيلية، خسائر الإتلاف، وصافي الربح
    # ==========================================
    def get_operating_expenses_summary(self, start_date=None, end_date=None):
        summary = {
            "total_expenses": 0.0,
            "by_category": {}
        }

        conn = self.db.connect()
        if not conn:
            return summary

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "expenses"):
                return summary

            amount_col = self._choose_column(cursor, "expenses", ["amount", "total_amount", "value"])
            if not amount_col:
                logger.warning("لم يتم العثور على عمود مبلغ مناسب في جدول expenses.")
                return summary

            date_where, params = self._build_date_condition(
                cursor,
                table_name="expenses",
                alias="e",
                candidate_columns=["expense_date", "created_at", "date"],
                start_date=start_date,
                end_date=end_date,
                joiner="WHERE"
            )

            total_query = f"""
                SELECT COALESCE(SUM(e.{amount_col}), 0)
                FROM expenses e
                {date_where}
            """
            summary["total_expenses"] = float(
                self._safe_scalar(cursor, total_query, params, 0.0)
            )

            expense_cols = self._get_table_columns(cursor, "expenses")

            # الحالة 1: يوجد category_id وجدول expense_categories
            if "category_id" in expense_cols and self._table_exists(cursor, "expense_categories"):
                cat_name_col = self._choose_column(
                    cursor,
                    "expense_categories",
                    ["name", "category_name", "title"]
                )
                if cat_name_col:
                    cat_query = f"""
                        SELECT c.{cat_name_col}, COALESCE(SUM(e.{amount_col}), 0)
                        FROM expenses e
                        JOIN expense_categories c ON e.category_id = c.id
                        {date_where}
                        GROUP BY c.id, c.{cat_name_col}
                        ORDER BY c.{cat_name_col}
                    """
                    cursor.execute(cat_query, params)
                    for cat_name, cat_amount in cursor.fetchall():
                        summary["by_category"][cat_name] = float(cat_amount or 0.0)

            # الحالة 2: التصنيف نصي داخل expenses نفسه
            elif "category" in expense_cols or "category_name" in expense_cols:
                local_cat_col = "category" if "category" in expense_cols else "category_name"
                cat_query = f"""
                    SELECT COALESCE(e.{local_cat_col}, 'غير مصنف'), COALESCE(SUM(e.{amount_col}), 0)
                    FROM expenses e
                    {date_where}
                    GROUP BY e.{local_cat_col}
                    ORDER BY e.{local_cat_col}
                """
                cursor.execute(cat_query, params)
                for cat_name, cat_amount in cursor.fetchall():
                    summary["by_category"][cat_name] = float(cat_amount or 0.0)

            else:
                if summary["total_expenses"] > 0:
                    summary["by_category"]["غير مصنف"] = summary["total_expenses"]

        except Exception:
            logger.exception("خطأ أثناء جلب المصروفات التشغيلية.")
        finally:
            conn.close()

        return summary

    def get_disposals_loss_summary(self, start_date=None, end_date=None):
        summary = {"total_loss": 0.0}

        conn = self.db.connect()
        if not conn:
            return summary

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "disposals"):
                return summary

            loss_col = self._choose_column(
                cursor,
                "disposals",
                ["total_cost", "loss_amount", "total_loss", "amount", "cost"]
            )
            if not loss_col:
                logger.warning("لم يتم العثور على عمود خسارة مناسب في disposals.")
                return summary

            date_where, params = self._build_date_condition(
                cursor,
                table_name="disposals",
                alias="d",
                candidate_columns=["disposal_date", "created_at", "date"],
                start_date=start_date,
                end_date=end_date,
                joiner="WHERE"
            )

            query = f"""
                SELECT COALESCE(SUM(d.{loss_col}), 0)
                FROM disposals d
                {date_where}
            """
            summary["total_loss"] = float(
                self._safe_scalar(cursor, query, params, 0.0)
            )

        except Exception:
            logger.exception("خطأ أثناء جلب خسائر الإتلاف.")
        finally:
            conn.close()

        return summary

    def get_net_profit_summary(self, start_date=None, end_date=None):
        summary = {
            "gross_profit": 0.0,
            "operating_expenses": 0.0,
            "disposal_losses": 0.0,
            "net_profit": 0.0
        }

        try:
            profit_data = self.get_gross_profit_summary(start_date, end_date)
            expenses_data = self.get_operating_expenses_summary(start_date, end_date)
            disposals_data = self.get_disposals_loss_summary(start_date, end_date)

            summary["gross_profit"] = float(profit_data.get("gross_profit", 0.0))
            summary["operating_expenses"] = float(expenses_data.get("total_expenses", 0.0))
            summary["disposal_losses"] = float(disposals_data.get("total_loss", 0.0))

            summary["net_profit"] = (
                summary["gross_profit"]
                - summary["operating_expenses"]
                - summary["disposal_losses"]
            )

        except Exception:
            logger.exception("خطأ أثناء حساب صافي الربح.")

        return summary

    # ==========================================
    # دوال مساعدة لجلب قوائم الفواتير (للواجهات الرسومية)
    # ==========================================
    def get_all_sales_list(self):
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "sales"):
                return []

            sales_cols = self._get_table_columns(cursor, "sales")
            if "id" not in sales_cols:
                return []

            total_col = self._choose_column(cursor, "sales", ["total_amount", "net_total", "amount"])
            date_col = self._choose_column(cursor, "sales", ["sale_date", "created_at", "date"])

            if not total_col or not date_col:
                logger.warning("تعذر جلب قائمة المبيعات بسبب غياب total/date column.")
                return []

            user_join = "LEFT JOIN users u ON s.user_id = u.id" if self._table_exists(cursor, "users") and "user_id" in sales_cols else ""
            customer_join = "LEFT JOIN customers c ON s.customer_id = c.id" if self._table_exists(cursor, "customers") and "customer_id" in sales_cols else ""

            username_expr = "COALESCE(u.username, '-')" if user_join else "'-'"
            customer_expr = "COALESCE(c.name, 'نقدي')" if customer_join else "'نقدي'"

            query = f"""
                SELECT
                    s.id,
                    {username_expr},
                    {customer_expr},
                    s.{total_col},
                    s.{date_col}
                FROM sales s
                {user_join}
                {customer_join}
                ORDER BY s.{date_col} DESC
            """
            cursor.execute(query)
            return cursor.fetchall()

        except Exception:
            logger.exception("خطأ أثناء جلب قائمة فواتير المبيعات.")
            return []
        finally:
            conn.close()

    def get_sale_details_list(self, sale_id):
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()

            if not self._table_exists(cursor, "sale_items"):
                return []

            sale_item_cols = self._get_table_columns(cursor, "sale_items")
            qty_col = "quantity" if "quantity" in sale_item_cols else None
            price_col = self._choose_column(
                cursor,
                "sale_items",
                ["price_at_sale", "final_unit_price", "original_unit_price", "unit_price"]
            )
            total_col = self._choose_column(
                cursor,
                "sale_items",
                ["total_item_price", "line_total", "total"]
            )

            if not qty_col or not price_col or not total_col:
                logger.warning("تعذر جلب تفاصيل الفاتورة بسبب غياب أعمدة مهمة في sale_items.")
                return []

            join_medicines = "LEFT JOIN medicines m ON si.medicine_id = m.id" if self._table_exists(cursor, "medicines") else ""
            join_batches = "LEFT JOIN batches b ON si.batch_id = b.id" if self._table_exists(cursor, "batches") else ""

            name_expr = "COALESCE(m.name, '-')" if join_medicines else "'-'"
            batch_expr = "COALESCE(b.batch_number, '-')" if join_batches else "'-'"

            query = f"""
                SELECT
                    {name_expr},
                    {batch_expr},
                    si.{qty_col},
                    si.{price_col},
                    si.{total_col}
                FROM sale_items si
                {join_medicines}
                {join_batches}
                WHERE si.sale_id = ?
            """
            cursor.execute(query, (sale_id,))
            return cursor.fetchall()

        except Exception:
            logger.exception("خطأ أثناء جلب تفاصيل فاتورة البيع رقم %s.", sale_id)
            return []
        finally:
            conn.close()