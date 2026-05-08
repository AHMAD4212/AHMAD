"""
وظيفة الملف: واجهة التقارير المالية والتشغيلية (Reports Page).
الطبقة: Presentation Layer

ملاحظة معمارية:
- تعتمد على ReportsDAO لعرض التقارير العامة.
- تعتمد على SalesDAO + pdf_generator فقط في مسار إعادة توليد/فتح/طباعة فواتير المبيعات.
- لا تحتوي أي عمليات حسابية مالية محلية (Dumb Client).
- تعرض الدورة المحاسبية الكاملة (مبيعات -> تكلفة -> هامش -> مصروفات -> إتلاف -> صافي ربح).
- تحتوي على تبويبات للملخص المالي، فواتير المبيعات، المخزون التشغيلي، والتدفق النقدي.
- [Requirement 19] تدعم إعادة توليد PDF لفواتير البيع السابقة وفتحها أو طباعتها.
- [Refresh Fix] يتم إعادة تحميل جميع البيانات تلقائياً عند كل دخول إلى الصفحة.
- [Global Filter Fix] زر الفلترة يعيد تحميل جميع أجزاء الصفحة ذات الصلة بدل تحديث جزء واحد فقط.
- [Open Then Ask Print] عند فتح فاتورة قديمة من التقارير يتم عرضها أولاً ثم سؤال المستخدم إن كان يريد طباعتها.
"""

import os
import sys
import subprocess
import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QTabWidget, QFrame, QDateEdit, QGridLayout, QSplitter,
    QMessageBox, QAbstractItemView
)
from PyQt5.QtCore import Qt, QDate

from models.reports_dao import ReportsDAO
from models.sales_dao import SalesDAO
from utils.pdf_generator import create_invoice_pdf

logger = logging.getLogger(__name__)


class ReportsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.reports_dao = ReportsDAO()
        self.sales_dao = SalesDAO()

        self.init_ui()
        self.load_all_data()

    # ==========================================
    # دورة حياة الصفحة
    # ==========================================
    def showEvent(self, event):
        super().showEvent(event)
        self.load_all_data()

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("التقارير المالية والتشغيلية")
        title.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                font-family: 'Times New Roman';
                font-size: 16px;
                font-weight: bold;
                padding: 10px 20px;
                background-color: #ECF0F1;
                border: 1px solid #BDC3C7;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background-color: #34495E;
                color: white;
            }
            QTabWidget::pane {
                border: 1px solid #BDC3C7;
                background-color: white;
            }
        """)

        self.setup_financial_summary_tab()
        self.setup_sales_invoices_tab()
        self.setup_operational_inventory_tab()
        self.setup_cash_flow_tab()

        layout.addWidget(self.tabs)
        self.setLayout(layout)

    # ==========================================
    # التبويب الأول: الملخص المالي
    # ==========================================
    def setup_financial_summary_tab(self):
        tab = QWidget()
        main_h_layout = QHBoxLayout(tab)
        main_h_layout.setContentsMargins(20, 20, 20, 20)

        left_layout = QVBoxLayout()

        filter_layout = QHBoxLayout()

        self.dt_start = QDateEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDate(QDate.currentDate().addDays(-30))
        self.dt_start.setStyleSheet("font-size: 16px; padding: 5px; font-family: 'Times New Roman';")

        self.dt_end = QDateEdit()
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDate(QDate.currentDate())
        self.dt_end.setStyleSheet("font-size: 16px; padding: 5px; font-family: 'Times New Roman';")

        self.btn_filter = QPushButton(" تطبيق الفلتر")
        self.btn_filter.setCursor(Qt.PointingHandCursor)
        self.btn_filter.setStyleSheet(
            "background-color: #2980B9; color: white; font-weight: bold; font-size: 16px; padding: 5px 20px;"
        )
        self.btn_filter.clicked.connect(self.apply_global_filter)

        filter_layout.addWidget(QLabel("من تاريخ:"))
        filter_layout.addWidget(self.dt_start)
        filter_layout.addWidget(QLabel("إلى تاريخ:"))
        filter_layout.addWidget(self.dt_end)
        filter_layout.addWidget(self.btn_filter)
        filter_layout.addStretch()

        left_layout.addLayout(filter_layout)

        self.summary_grid = QGridLayout()
        self.summary_grid.setSpacing(15)

        self.lbl_gross_sales = self.create_value_label()
        self.lbl_returns = self.create_value_label()
        self.lbl_net_sales = self.create_value_label()
        self.lbl_cogs = self.create_value_label()
        self.lbl_gross_profit = self.create_value_label()
        self.lbl_expenses = self.create_value_label()
        self.lbl_disposal_losses = self.create_value_label()
        self.lbl_net_profit = self.create_value_label()

        self.add_summary_card(self.summary_grid, "إجمالي المبيعات", self.lbl_gross_sales, 0, 0, "#3498DB")
        self.add_summary_card(self.summary_grid, "إجمالي المرتجعات", self.lbl_returns, 0, 1, "#E74C3C")
        self.add_summary_card(self.summary_grid, "صافي المبيعات", self.lbl_net_sales, 0, 2, "#27AE60")

        self.add_summary_card(self.summary_grid, "تكلفة البضاعة (COGS)", self.lbl_cogs, 1, 0, "#F39C12")
        self.add_summary_card(self.summary_grid, "هامش الربح الإجمالي", self.lbl_gross_profit, 1, 1, "#8E44AD")
        self.add_summary_card(self.summary_grid, "المصروفات التشغيلية", self.lbl_expenses, 1, 2, "#D35400")

        self.add_summary_card(self.summary_grid, "خسائر الإتلاف / هدر", self.lbl_disposal_losses, 2, 0, "#A93226")
        self.add_summary_card(
            self.summary_grid,
            "صافي الربح الفعلي (Net Profit)",
            self.lbl_net_profit,
            2,
            1,
            "#1A5276",
            col_span=2
        )

        left_layout.addLayout(self.summary_grid)
        left_layout.addStretch()

        right_layout = QVBoxLayout()

        right_title = QLabel("تفصيل المصروفات حسب التصنيف")
        right_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #34495E; font-family: 'Times New Roman';"
        )

        self.tbl_expenses_breakdown = self.create_table(["التصنيف", "المبلغ"])
        self.tbl_expenses_breakdown.setFixedWidth(300)

        right_layout.addWidget(right_title)
        right_layout.addWidget(self.tbl_expenses_breakdown)

        main_h_layout.addLayout(left_layout, stretch=3)
        main_h_layout.addLayout(right_layout, stretch=1)

        self.tabs.addTab(tab, "الملخص المالي")

    # ==========================================
    # التبويب الثاني: فواتير المبيعات وتفاصيلها
    # ==========================================
    def setup_sales_invoices_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        tools_layout = QHBoxLayout()

        self.btn_refresh_invoices = QPushButton(" 🔄 تحديث السجل")
        self.btn_refresh_invoices.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_invoices.setStyleSheet(
            "background-color: #2980B9; color: white; font-weight: bold; font-size: 15px; padding: 6px 16px;"
        )
        self.btn_refresh_invoices.clicked.connect(self.load_sales_invoices)

        self.btn_open_invoice_pdf = QPushButton(" 📄 فتح / إعادة توليد PDF")
        self.btn_open_invoice_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_open_invoice_pdf.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; font-size: 15px; padding: 6px 16px;"
        )
        self.btn_open_invoice_pdf.clicked.connect(self.open_selected_invoice_pdf)

        self.btn_print_invoice = QPushButton(" 🖨️ طباعة الفاتورة المحددة")
        self.btn_print_invoice.setCursor(Qt.PointingHandCursor)
        self.btn_print_invoice.setStyleSheet(
            "background-color: #8E44AD; color: white; font-weight: bold; font-size: 15px; padding: 6px 16px;"
        )
        self.btn_print_invoice.clicked.connect(self.print_selected_invoice_pdf)

        tools_layout.addWidget(self.btn_refresh_invoices)
        tools_layout.addWidget(self.btn_open_invoice_pdf)
        tools_layout.addWidget(self.btn_print_invoice)
        tools_layout.addStretch()

        layout.addLayout(tools_layout)

        splitter = QSplitter(Qt.Vertical)

        self.tbl_invoices = self.create_table(["رقم الفاتورة", "البائع", "العميل", "الإجمالي", "التاريخ"])
        self.tbl_invoices.itemSelectionChanged.connect(self.on_invoice_selected)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)

        lbl_details = QLabel("تفاصيل الأصناف للفاتورة المحددة:")
        lbl_details.setStyleSheet("font-size: 16px; font-weight: bold; font-family: 'Times New Roman';")
        details_layout.addWidget(lbl_details)

        self.tbl_invoice_details = self.create_table(["اسم الدواء", "التشغيلة", "الكمية", "سعر البيع", "الإجمالي"])
        details_layout.addWidget(self.tbl_invoice_details)

        splitter.addWidget(self.tbl_invoices)
        splitter.addWidget(details_widget)
        splitter.setSizes([300, 200])

        layout.addWidget(splitter)
        self.tabs.addTab(tab, "فواتير المبيعات")

    # ==========================================
    # التبويب الثالث: المخزون التشغيلي
    # ==========================================
    def setup_operational_inventory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        inv_tabs = QTabWidget()

        self.tbl_low_stock = self.create_table(["المعرف", "الباركود", "اسم الدواء", "المتاح للبيع", "الحد الأدنى"])
        inv_tabs.addTab(self.tbl_low_stock, "نواقص المخزون (Low Stock)")

        self.tbl_expiring = self.create_table(["الباركود", "اسم الدواء", "التشغيلة", "الكمية", "تاريخ الانتهاء"])
        inv_tabs.addTab(self.tbl_expiring, "قريبة الانتهاء (Expiring Soon)")

        self.tbl_expired = self.create_table(["الباركود", "اسم الدواء", "التشغيلة", "الكمية", "تاريخ الانتهاء"])
        inv_tabs.addTab(self.tbl_expired, "منتهية الصلاحية (Expired)")

        layout.addWidget(inv_tabs)
        self.tabs.addTab(tab, "المخزون التشغيلي")

    # ==========================================
    # التبويب الرابع: التدفق النقدي
    # ==========================================
    def setup_cash_flow_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header_layout = QHBoxLayout()

        self.lbl_cash_in = QLabel("الداخل: 0.00")
        self.lbl_cash_in.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #27AE60; font-family: 'Times New Roman';"
        )

        self.lbl_cash_out = QLabel("الخارج: 0.00")
        self.lbl_cash_out.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #E74C3C; font-family: 'Times New Roman';"
        )

        self.lbl_net_cash = QLabel("الرصيد الصافي: 0.00")
        self.lbl_net_cash.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )

        header_layout.addWidget(self.lbl_cash_in)
        header_layout.addWidget(self.lbl_cash_out)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_net_cash)

        layout.addLayout(header_layout)

        self.tbl_cash_flow = self.create_table(["نوع الحركة (المرجع)", "الجهة", "إجمالي المبلغ"])
        layout.addWidget(self.tbl_cash_flow)

        self.tabs.addTab(tab, "التدفق النقدي (Cash Flow)")

    # ==========================================
    # دوال مساعدة عامة
    # ==========================================
    def create_table(self, headers):
        tbl = QTableWidget()
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        tbl.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        return tbl

    def create_value_label(self):
        lbl = QLabel("0.00")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbl.setStyleSheet(
            "font-size: 28px; font-weight: bold; font-family: 'Times New Roman'; margin-top: 10px;"
        )
        return lbl

    def add_summary_card(self, grid, title, value_label, row, col, color, col_span=1):
        frame = QFrame()
        frame.setStyleSheet(
            f"background-color: white; border-radius: 8px; border-right: 8px solid {color}; padding: 15px;"
        )
        vbox = QVBoxLayout(frame)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            "color: #7F8C8D; font-size: 18px; font-weight: bold; font-family: 'Times New Roman';"
        )

        vbox.addWidget(lbl_title)
        vbox.addWidget(value_label)
        grid.addWidget(frame, row, col, 1, col_span)

    def _get_selected_sale_id(self):
        selected_row = self.tbl_invoices.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد فاتورة من جدول فواتير المبيعات أولاً.")
            return None

        sale_id_item = self.tbl_invoices.item(selected_row, 0)
        if not sale_id_item:
            QMessageBox.warning(self, "تنبيه", "تعذر قراءة رقم الفاتورة المحددة.")
            return None

        try:
            return int(sale_id_item.text())
        except (TypeError, ValueError):
            QMessageBox.warning(self, "تنبيه", "رقم الفاتورة المحددة غير صالح.")
            return None

    def _build_pdf_for_sale(self, sale_id):
        receipt_result = self.sales_dao.get_sale_receipt_data(sale_id)

        if not isinstance(receipt_result, tuple) or len(receipt_result) != 2:
            logger.error(
                "Unexpected return contract from get_sale_receipt_data for sale_id=%s: %r",
                sale_id,
                receipt_result
            )
            QMessageBox.critical(
                self,
                "فشل التوليد",
                f"صيغة بيانات الفاتورة رقم {sale_id} غير صحيحة."
            )
            return None

        success, payload = receipt_result

        if not success:
            error_message = payload if isinstance(payload, str) else f"تعذر جلب بيانات الفاتورة رقم {sale_id} من قاعدة البيانات."
            logger.error("Receipt data fetch failed for sale_id=%s: %s", sale_id, error_message)
            QMessageBox.critical(
                self,
                "فشل التوليد",
                error_message
            )
            return None

        if not isinstance(payload, dict):
            logger.error("Receipt payload is not dict for sale_id=%s: %r", sale_id, payload)
            QMessageBox.critical(
                self,
                "فشل التوليد",
                f"بيانات الفاتورة رقم {sale_id} المستلمة من النواة غير صالحة."
            )
            return None

        pdf_path = create_invoice_pdf(payload)
        if not pdf_path:
            QMessageBox.critical(
                self,
                "فشل التوليد",
                f"تعذر إنشاء ملف PDF للفاتورة رقم {sale_id}."
            )
            return None

        return pdf_path

    def _open_file(self, file_path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(file_path)
                return True

            if sys.platform == "darwin":
                subprocess.Popen(["open", file_path])
                return True

            subprocess.Popen(["xdg-open", file_path])
            return True

        except Exception as e:
            logger.exception("فشل فتح الملف:")
            QMessageBox.warning(self, "تعذر الفتح", f"تعذر فتح الملف:\n{file_path}\n\nالسبب:\n{str(e)}")
            return False

    def _print_file(self, file_path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(file_path, "print")
                return True

            try:
                subprocess.run(["lpr", file_path], check=True)
                return True
            except Exception:
                if sys.platform == "darwin":
                    subprocess.run(["open", "-a", "Preview", file_path], check=True)
                    return True

            return False

        except Exception as e:
            logger.exception("فشل طباعة الملف:")
            QMessageBox.warning(self, "تعذر الطباعة", f"تعذر طباعة الملف:\n{file_path}\n\nالسبب:\n{str(e)}")
            return False

    def _open_then_ask_print(self, sale_id, pdf_path):
        opened = self._open_file(pdf_path)
        if not opened:
            QMessageBox.warning(
                self,
                "تعذر الفتح",
                f"تم إنشاء/تحديث ملف PDF للفاتورة رقم {sale_id} لكن تعذر فتحه تلقائياً.\n\nالمسار:\n{pdf_path}"
            )
            return

        reply = QMessageBox.question(
            self,
            "طباعة الفاتورة",
            f"تم عرض الفاتورة رقم {sale_id} بنجاح.\n\nهل تريد طباعتها الآن؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            printed = self._print_file(pdf_path)
            if printed:
                QMessageBox.information(
                    self,
                    "تم إرسال الفاتورة للطباعة",
                    f"تم إرسال الفاتورة رقم {sale_id} إلى نظام الطباعة بنجاح."
                )
            else:
                QMessageBox.warning(
                    self,
                    "تعذر الطباعة المباشرة",
                    f"تم عرض الفاتورة رقم {sale_id} لكن تعذر إرسالها للطباعة مباشرة.\nيمكنك طباعتها يدوياً من عارض الـ PDF.\n\nالمسار:\n{pdf_path}"
                )

    def _get_date_range(self):
        start = self.dt_start.date().toString("yyyy-MM-dd")
        end = self.dt_end.date().toString("yyyy-MM-dd")
        return start, end

    def apply_global_filter(self):
        self.load_all_data()

    # ==========================================
    # تحميل البيانات
    # ==========================================
    def load_all_data(self):
        self.load_financial_summary()
        self.load_sales_invoices()
        self.load_inventory_report()
        self.load_cash_flow()

    def load_financial_summary(self):
        start, end = self._get_date_range()

        sales_data = self.reports_dao.get_sales_and_returns_summary(start, end)
        profit_data = self.reports_dao.get_gross_profit_summary(start, end)
        net_profit_data = self.reports_dao.get_net_profit_summary(start, end)
        expenses_data = self.reports_dao.get_operating_expenses_summary(start, end)

        self.lbl_gross_sales.setText(f"{sales_data.get('gross_sales', 0):,.2f}")
        self.lbl_returns.setText(f"{sales_data.get('total_returns', 0):,.2f}")
        self.lbl_net_sales.setText(f"{sales_data.get('net_sales', 0):,.2f}")

        self.lbl_cogs.setText(f"{profit_data.get('net_cogs', 0):,.2f}")
        self.lbl_gross_profit.setText(f"{net_profit_data.get('gross_profit', 0):,.2f}")
        self.lbl_expenses.setText(f"{net_profit_data.get('operating_expenses', 0):,.2f}")
        self.lbl_disposal_losses.setText(f"{net_profit_data.get('disposal_losses', 0):,.2f}")
        self.lbl_net_profit.setText(f"{net_profit_data.get('net_profit', 0):,.2f}")

        self.tbl_expenses_breakdown.setRowCount(0)
        by_category = expenses_data.get("by_category", {})

        for row_idx, (cat_name, amount) in enumerate(by_category.items()):
            self.tbl_expenses_breakdown.insertRow(row_idx)

            item_cat = QTableWidgetItem(str(cat_name))
            item_amt = QTableWidgetItem(f"{amount:,.2f}")

            item_cat.setTextAlignment(Qt.AlignCenter)
            item_amt.setTextAlignment(Qt.AlignCenter)

            self.tbl_expenses_breakdown.setItem(row_idx, 0, item_cat)
            self.tbl_expenses_breakdown.setItem(row_idx, 1, item_amt)

    def load_sales_invoices(self):
        invoices = self.reports_dao.get_all_sales_list()
        self.tbl_invoices.setRowCount(0)
        self.tbl_invoice_details.setRowCount(0)

        for row_idx, inv in enumerate(invoices):
            self.tbl_invoices.insertRow(row_idx)
            for col_idx, val in enumerate(inv):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                self.tbl_invoices.setItem(row_idx, col_idx, item)

    def on_invoice_selected(self):
        selected = self.tbl_invoices.currentRow()
        if selected < 0:
            self.tbl_invoice_details.setRowCount(0)
            return

        sale_id_item = self.tbl_invoices.item(selected, 0)
        if not sale_id_item:
            self.tbl_invoice_details.setRowCount(0)
            return

        try:
            sale_id = int(sale_id_item.text())
        except (TypeError, ValueError):
            self.tbl_invoice_details.setRowCount(0)
            return

        details = self.reports_dao.get_sale_details_list(sale_id)

        self.tbl_invoice_details.setRowCount(0)
        for row_idx, det in enumerate(details):
            self.tbl_invoice_details.insertRow(row_idx)
            for col_idx, val in enumerate(det):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                self.tbl_invoice_details.setItem(row_idx, col_idx, item)

    def load_inventory_report(self):
        inv_data = self.reports_dao.get_inventory_operational_report()

        def populate(table, data):
            table.setRowCount(0)
            for row_idx, row_data in enumerate(data):
                table.insertRow(row_idx)
                for col_idx, val in enumerate(row_data):
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row_idx, col_idx, item)

        populate(self.tbl_low_stock, inv_data.get("low_stock", []))
        populate(self.tbl_expiring, inv_data.get("expiring_soon", []))
        populate(self.tbl_expired, inv_data.get("expired", []))

    def load_cash_flow(self):
        start, end = self._get_date_range()
        cf_data = self.reports_dao.get_cash_flow_summary(start, end)

        self.lbl_cash_in.setText(f"إجمالي الداخل: {cf_data.get('total_in', 0):,.2f}")
        self.lbl_cash_out.setText(f"إجمالي الخارج: {cf_data.get('total_out', 0):,.2f}")
        self.lbl_net_cash.setText(f"رصيد الصندوق (Net): {cf_data.get('net_balance', 0):,.2f}")

        reference_map = {
            "in_sale": ("إيراد", "مبيعات نقدية"),
            "out_purchase": ("مدفوعات", "فواتير مشتريات"),
            "out_return": ("استرداد", "مرتجعات عملاء"),
            "out_expense": ("مصروفات", "مصروفات تشغيلية/نثرية"),
            "out_disposal": ("تسوية جردية", "خسائر إتلاف أدوية")
        }

        self.tbl_cash_flow.setRowCount(0)
        breakdown = cf_data.get("breakdown", {})

        row_idx = 0
        for key, amount in breakdown.items():
            if amount <= 0:
                continue

            self.tbl_cash_flow.insertRow(row_idx)
            direction, ref_name = reference_map.get(key, ("غير محدد", key))

            item_dir = QTableWidgetItem(direction)
            item_ref = QTableWidgetItem(ref_name)
            item_amt = QTableWidgetItem(f"{amount:,.2f}")

            for item in (item_dir, item_ref, item_amt):
                item.setTextAlignment(Qt.AlignCenter)

            self.tbl_cash_flow.setItem(row_idx, 0, item_dir)
            self.tbl_cash_flow.setItem(row_idx, 1, item_ref)
            self.tbl_cash_flow.setItem(row_idx, 2, item_amt)

            row_idx += 1

    # ==========================================
    # Requirement 19: PDF / Open / Print
    # ==========================================
    def open_selected_invoice_pdf(self):
        sale_id = self._get_selected_sale_id()
        if not sale_id:
            return

        pdf_path = self._build_pdf_for_sale(sale_id)
        if not pdf_path:
            return

        self._open_then_ask_print(sale_id, pdf_path)

    def print_selected_invoice_pdf(self):
        sale_id = self._get_selected_sale_id()
        if not sale_id:
            return

        pdf_path = self._build_pdf_for_sale(sale_id)
        if not pdf_path:
            return

        printed = self._print_file(pdf_path)
        if printed:
            QMessageBox.information(
                self,
                "تم إرسال الفاتورة للطباعة",
                f"تم إنشاء/تحديث ملف PDF وإرساله للطباعة بنجاح.\n\nالمسار:\n{pdf_path}"
            )
        else:
            QMessageBox.warning(
                self,
                "تعذر الطباعة المباشرة",
                f"تم إنشاء ملف PDF لكن تعذر إرساله للطباعة مباشرة.\nيمكنك فتحه وطباعةه يدوياً.\n\nالمسار:\n{pdf_path}"
            )