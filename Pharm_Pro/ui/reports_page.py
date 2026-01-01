from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QHeaderView, QMessageBox, QHBoxLayout, QLabel,
                             QTabWidget, QFrame)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from models.reports_dao import ReportsDAO
from utils.pdf_generator import create_invoice_pdf
import os
import csv


class ReportsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = ReportsDAO()
        self.init_ui()
        self.load_all_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # العنوان الرئيسي
        title = QLabel("التقارير المالية والإدارية")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman'; margin-bottom: 10px;")
        layout.addWidget(title)

        # نظام التبويب (Tabs)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #BDC3C7; }
            QTabBar::tab { font-family: 'Times New Roman'; font-size: 16px; padding: 10px 20px; }
            QTabBar::tab:selected { background-color: #3498DB; color: white; font-weight: bold; }
        """)

        # إنشاء الصفحات الثلاث
        self.tab_sales = QWidget()
        self.tab_purchases = QWidget()
        self.tab_shortages = QWidget()

        self.create_sales_tab()
        self.create_purchases_tab()
        self.create_shortages_tab()

        self.tabs.addTab(self.tab_sales, "💰 المبيعات والأرباح")
        self.tabs.addTab(self.tab_purchases, "📥 سجل المشتريات")
        self.tabs.addTab(self.tab_shortages, "⚠️ النواقص (طلبات الشراء)")

        layout.addWidget(self.tabs)
        self.setLayout(layout)

    # ------------------------------------------------------------------------
    # 1. تصميم تبويب المبيعات
    # ------------------------------------------------------------------------
    def create_sales_tab(self):
        layout = QVBoxLayout()

        # ملخص مالي علوي
        summary_layout = QHBoxLayout()
        self.lbl_total_sales = QLabel("إجمالي المبيعات: 0.00")
        self.lbl_total_purchases = QLabel("إجمالي المصروفات: 0.00")
        self.lbl_net_profit = QLabel("صافي الدخل: 0.00")

        for lbl in [self.lbl_total_sales, self.lbl_total_purchases, self.lbl_net_profit]:
            lbl.setStyleSheet(
                "font-size: 18px; font-weight: bold; font-family: 'Times New Roman'; padding: 10px; border: 1px solid #ccc; background-color: white; border-radius: 5px;")
            summary_layout.addWidget(lbl)

        layout.addLayout(summary_layout)

        # جدول المبيعات
        self.sales_table = QTableWidget()
        self.sales_table.setColumnCount(5)
        self.sales_table.setHorizontalHeaderLabels(["رقم الفاتورة", "البائع", "العميل", "الإجمالي", "التاريخ"])
        self.sales_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sales_table.setLayoutDirection(Qt.RightToLeft)
        self.sales_table.setStyleSheet("font-family: 'Times New Roman'; font-size: 14px;")
        layout.addWidget(self.sales_table)

        # الأزرار
        btn_layout = QHBoxLayout()
        btn_refresh = QPushButton("🔄 تحديث البيانات")
        btn_refresh.clicked.connect(self.load_all_data)
        btn_refresh.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        btn_print = QPushButton("🖨️ إعادة طباعة الفاتورة")
        btn_print.clicked.connect(self.reprint_sales_invoice)
        btn_print.setStyleSheet(
            "background-color: #8E44AD; color: white; font-weight: bold; font-size: 16px; font-family: 'Times New Roman'; padding: 8px;")

        btn_layout.addWidget(btn_refresh)
        btn_layout.addWidget(btn_print)
        layout.addLayout(btn_layout)

        self.tab_sales.setLayout(layout)

    # ------------------------------------------------------------------------
    # 2. تصميم تبويب المشتريات
    # ------------------------------------------------------------------------
    def create_purchases_tab(self):
        layout = QVBoxLayout()

        self.purchases_table = QTableWidget()
        self.purchases_table.setColumnCount(5)
        self.purchases_table.setHorizontalHeaderLabels(["ID", "المورد", "رقم الفاتورة", "المبلغ", "التاريخ"])
        self.purchases_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.purchases_table.setLayoutDirection(Qt.RightToLeft)
        self.purchases_table.setStyleSheet("font-family: 'Times New Roman'; font-size: 14px;")
        layout.addWidget(self.purchases_table)

        btn_show_details = QPushButton("📄 عرض تفاصيل الفاتورة")
        btn_show_details.clicked.connect(self.show_purchase_details)
        btn_show_details.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; font-size: 16px; font-family: 'Times New Roman'; padding: 8px;")

        layout.addWidget(btn_show_details)
        self.tab_purchases.setLayout(layout)

    # ------------------------------------------------------------------------
    # 3. تصميم تبويب النواقص
    # ------------------------------------------------------------------------
    def create_shortages_tab(self):
        layout = QVBoxLayout()

        lbl = QLabel("الأدوية التالية وصلت للحد الأدنى، يرجى طلبها من الموردين:")
        lbl.setStyleSheet("color: #E74C3C; font-weight: bold; font-size: 16px; font-family: 'Times New Roman';")
        layout.addWidget(lbl)

        self.shortage_table = QTableWidget()
        self.shortage_table.setColumnCount(4)
        self.shortage_table.setHorizontalHeaderLabels(["الباركود", "اسم الدواء", "الكمية الحالية", "المورد المقترح"])
        self.shortage_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.shortage_table.setLayoutDirection(Qt.RightToLeft)
        self.shortage_table.setStyleSheet("font-family: 'Times New Roman'; font-size: 14px;")
        layout.addWidget(self.shortage_table)

        btn_export = QPushButton("📄 استخراج طلب شراء (Purchase Order)")
        btn_export.clicked.connect(self.export_shortage_report)
        btn_export.setStyleSheet(
            "background-color: #F39C12; color: white; font-weight: bold; font-size: 16px; font-family: 'Times New Roman'; padding: 8px;")

        layout.addWidget(btn_export)
        self.tab_shortages.setLayout(layout)

    # ------------------------------------------------------------------------
    # الدوال المنطقية (Loading Data)
    # ------------------------------------------------------------------------
    def load_all_data(self):
        self.load_sales()
        self.load_purchases()
        self.load_shortages()
        self.update_financial_summary()

    def update_financial_summary(self):
        summary = self.dao.get_financial_summary()
        self.lbl_total_sales.setText(f"إجمالي المبيعات: {summary['sales']:,.2f}")
        self.lbl_total_purchases.setText(f"إجمالي المصروفات: {summary['purchases']:,.2f}")

        profit = summary['profit']
        color = "green" if profit >= 0 else "red"
        self.lbl_net_profit.setText(f"صافي الدخل: {profit:,.2f}")
        self.lbl_net_profit.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: bold; font-family: 'Times New Roman'; padding: 10px; border: 1px solid #ccc; background-color: white; border-radius: 5px;")

    def load_sales(self):
        sales = self.dao.get_all_sales()
        self.sales_table.setRowCount(0)
        for row, data in enumerate(sales):
            self.sales_table.insertRow(row)
            # data: id, username, cust_name, total, date
            cust_name = data[2] if data[2] else "نقدي"
            self.sales_table.setItem(row, 0, QTableWidgetItem(str(data[0])))
            self.sales_table.setItem(row, 1, QTableWidgetItem(str(data[1])))
            self.sales_table.setItem(row, 2, QTableWidgetItem(str(cust_name)))
            self.sales_table.setItem(row, 3, QTableWidgetItem(f"{data[3]:.2f}"))
            self.sales_table.setItem(row, 4, QTableWidgetItem(str(data[4])))

    def load_purchases(self):
        purchases = self.dao.get_all_purchases()
        self.purchases_table.setRowCount(0)
        for row, data in enumerate(purchases):
            self.purchases_table.insertRow(row)
            for col, val in enumerate(data):
                self.purchases_table.setItem(row, col, QTableWidgetItem(str(val)))

    def load_shortages(self):
        items = self.dao.get_low_stock_items()
        self.shortage_table.setRowCount(0)
        for row, data in enumerate(items):
            self.shortage_table.insertRow(row)
            # barcode, name, qty, supplier
            self.shortage_table.setItem(row, 0, QTableWidgetItem(str(data[0])))
            self.shortage_table.setItem(row, 1, QTableWidgetItem(str(data[1])))
            self.shortage_table.setItem(row, 2, QTableWidgetItem(str(data[2])))

            sup_name = data[3] if data[3] else "غير محدد"
            self.shortage_table.setItem(row, 3, QTableWidgetItem(sup_name))

    # ------------------------------------------------------------------------
    # الوظائف (Printing / Details)
    # ------------------------------------------------------------------------
    def reprint_sales_invoice(self):
        """إعادة طباعة فاتورة البيع المحددة"""
        selected = self.sales_table.currentRow()
        if selected < 0:
            QMessageBox.warning(self, "تنبيه", "حدد فاتورة لطباعتها")
            return

        # 1. جلب البيانات الأساسية من الجدول
        sale_id = self.sales_table.item(selected, 0).text()
        cashier = self.sales_table.item(selected, 1).text()

        # تنظيف المبلغ من أي نصوص إضافية وتحويله لرقم
        total_text = self.sales_table.item(selected, 3).text()
        try:
            # قد يكون النص يحتوي على "الإجمالي: " أو فواصل
            clean_total = total_text.replace("الإجمالي:", "").replace(",", "").strip()
            total = float(clean_total)
        except:
            total = 0.0

        date = self.sales_table.item(selected, 4).text()

        # 2. جلب تفاصيل الأدوية من قاعدة البيانات
        items = self.dao.get_sale_details(sale_id)

        if not items:
            QMessageBox.warning(self, "تنبيه", "لا توجد تفاصيل لهذه الفاتورة!")
            return

        try:
            # 3. استدعاء دالة التوليد
            pdf_path = create_invoice_pdf(items, total, sale_id, cashier, date)

            if pdf_path:
                QMessageBox.information(self, "تم", f"تم حفظ الفاتورة في:\n{pdf_path}")
                # محاولة فتح الملف تلقائياً
                if os.name == 'nt':  # Windows
                    os.startfile(pdf_path)
                else:
                    # Linux/Mac
                    os.system(f"xdg-open '{pdf_path}'")
            else:
                QMessageBox.critical(self, "خطأ", "فشل في إنشاء ملف PDF")

        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء الطباعة: {e}")

    def show_purchase_details(self):
        selected = self.purchases_table.currentRow()
        if selected < 0:
            QMessageBox.warning(self, "تنبيه", "حدد فاتورة شراء لعرض تفاصيلها")
            return

        pur_id = self.purchases_table.item(selected, 0).text()
        details = self.dao.get_purchase_details(pur_id)

        # عرض سريع في رسالة (يمكن تطويرها لنافذة منفصلة)
        text = "تفاصيل الفاتورة:\n\n"
        for item in details:
            text += f"- {item[0]}: {item[1]} قطعة بسعر {item[2]} (الإجمالي: {item[3]})\n"

        QMessageBox.information(self, "تفاصيل الشراء", text)

    def export_shortage_report(self):
        """تصدير قائمة النواقص إلى ملف نصي كطلب شراء"""
        try:
            filename = "purchase_order.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("=== طلب شراء مواد ناقصة (Purchase Order) ===\n")
                f.write(f"التاريخ: {os.path.basename(os.getcwd())}\n\n")  # أو استخدام datetime

                rows = self.shortage_table.rowCount()
                for i in range(rows):
                    name = self.shortage_table.item(i, 1).text()
                    qty = self.shortage_table.item(i, 2).text()
                    sup = self.shortage_table.item(i, 3).text()
                    f.write(f"- مطلوب: {name} | الكمية الحالية: {qty} | المورد: {sup}\n")

            QMessageBox.information(self, "تم", f"تم حفظ طلب الشراء في ملف:\n{filename}")
            os.startfile(filename) if os.name == 'nt' else None
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))