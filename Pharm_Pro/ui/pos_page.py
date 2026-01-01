import os

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QLabel, QMessageBox, QFrame, QComboBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from models.sales_dao import SalesDAO
from models.customers_dao import CustomersDAO  # ✅ استدعاء كلاس العملاء


class POSPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = SalesDAO()
        self.customers_dao = CustomersDAO()  # ✅ تهيئة كائن العملاء
        self.cart = []  # قائمة لتخزين الأدوية المضافة للفاتورة الحالية
        self.init_ui()
        self.load_customers()  # ✅ تحميل قائمة العملاء عند التشغيل

    def init_ui(self):
        layout = QHBoxLayout()  # تقسيم الشاشة لعمودين (يمين ويسار)

        # --- القسم الأيمن: الفاتورة والبحث ---
        right_panel = QVBoxLayout()

        # 1. حقل البحث (الباركود)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ادخل اسم الدواء أو امسح الباركود واضغط Enter...")
        # تحديث الخط إلى Times New Roman
        self.search_input.setStyleSheet(
            "padding: 15px; font-size: 16px; border: 2px solid #3498DB; border-radius: 10px; font-family: 'Times New Roman';")
        self.search_input.returnPressed.connect(self.add_to_cart)  # عند ضغط Enter
        right_panel.addWidget(self.search_input)

        # 2. جدول الفاتورة (السلة)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "اسم الدواء", "سعر الوحدة", "الكمية", "الإجمالي"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        # تنسيق الجدول والخط
        self.table.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        right_panel.addWidget(self.table)

        # 3. أزرار التحكم بالسلة
        actions_layout = QHBoxLayout()
        self.btn_remove = QPushButton("❌ حذف صنف")
        self.btn_remove.clicked.connect(self.remove_item)
        self.btn_remove.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 10px; font-family: 'Times New Roman'; font-size: 14px;")

        self.btn_clear = QPushButton("🗑️ تفريغ السلة")
        self.btn_clear.clicked.connect(self.clear_cart)
        self.btn_clear.setStyleSheet("padding: 10px; font-family: 'Times New Roman'; font-size: 14px;")

        actions_layout.addWidget(self.btn_remove)
        actions_layout.addWidget(self.btn_clear)
        right_panel.addLayout(actions_layout)

        layout.addLayout(right_panel, stretch=2)  # يأخذ مساحة أكبر

        # --- القسم الأيسر: بيانات الفاتورة والحساب والدفع ---
        left_panel = QFrame()
        left_panel.setStyleSheet("background-color: #2C3E50; border-radius: 15px; color: white;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)  # مسافات بين العناصر
        left_layout.setContentsMargins(20, 20, 20, 20)

        # 1. اختيار العميل (جديد)
        lbl_cust = QLabel("👤 العميل:")
        lbl_cust.setFont(QFont("Times New Roman", 14, QFont.Bold))
        left_layout.addWidget(lbl_cust)

        self.customer_combo = QComboBox()
        self.customer_combo.setStyleSheet("""
            QComboBox { background-color: white; color: black; padding: 10px; border-radius: 5px; font-family: 'Times New Roman'; font-size: 14px; }
            QComboBox::drop-down { border: 0px; }
        """)
        left_layout.addWidget(self.customer_combo)

        # 2. اسم الطبيب (جديد)
        lbl_doc = QLabel("🩺 الطبيب المعالج:")
        lbl_doc.setFont(QFont("Times New Roman", 14, QFont.Bold))
        left_layout.addWidget(lbl_doc)

        self.doctor_input = QLineEdit()
        self.doctor_input.setPlaceholderText("اسم الطبيب (اختياري)")
        self.doctor_input.setStyleSheet(
            "background-color: white; color: black; padding: 10px; border-radius: 5px; font-family: 'Times New Roman'; font-size: 14px;")
        left_layout.addWidget(self.doctor_input)

        # فاصل مرن
        left_layout.addStretch()

        # 3. الإجمالي
        title = QLabel("إجمالي الفاتورة")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Times New Roman", 20, QFont.Bold))
        left_layout.addWidget(title)

        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignCenter)
        self.total_label.setStyleSheet(
            "font-size: 44px; color: #2ECC71; font-weight: bold; font-family: 'Times New Roman';")
        left_layout.addWidget(self.total_label)

        left_layout.addStretch()

        # 4. زر الدفع
        self.btn_checkout = QPushButton("💰 إتمام البيع")
        self.btn_checkout.setCursor(Qt.PointingHandCursor)
        self.btn_checkout.clicked.connect(self.checkout)
        self.btn_checkout.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                font-size: 22px;
                padding: 15px;
                border-radius: 10px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
            QPushButton:hover { background-color: #219150; }
        """)
        left_layout.addWidget(self.btn_checkout)

        layout.addWidget(left_panel, stretch=1)

        self.setLayout(layout)

    def load_customers(self):
        """تحميل العملاء في القائمة المنسدلة"""
        self.customer_combo.clear()
        self.customer_combo.addItem("عميل نقدي (Walk-in)", None)

        # جلب العملاء من قاعدة البيانات
        customers = self.customers_dao.get_all_customers()
        for cust in customers:
            # cust = (id, name, phone, email, notes)
            display_text = f"{cust[1]} - {cust[2]}"  # الاسم - الهاتف
            self.customer_combo.addItem(display_text, cust[0])  # تخزين ID كبيانات مخفية

    def add_to_cart(self):
        text = self.search_input.text().strip()
        if not text:
            return

        medicine = self.dao.get_medicine_by_barcode_or_name(text)

        if medicine:
            med_id, name, price, stock, barcode = medicine

            # التحقق هل الدواء موجود مسبقاً في السلة؟
            for item in self.cart:
                if item['id'] == med_id:
                    if item['qty'] < stock:
                        item['qty'] += 1
                        self.update_table()
                        self.search_input.clear()
                    else:
                        QMessageBox.warning(self, "تنبيه", "الكمية المطلوبة غير متوفرة في المخزون!")
                    return

            # إذا لم يكن موجوداً، أضفه كعنصر جديد
            self.cart.append({
                'id': med_id,
                'name': name,
                'price': price,
                'qty': 1,
                'total': price
            })
            self.update_table()
            self.search_input.clear()
        else:
            QMessageBox.warning(self, "خطأ", "دواء غير موجود أو الكمية نفدت!")

    def update_table(self):
        """تحديث عرض الجدول وحساب المجموع"""
        self.table.setRowCount(0)
        total_bill = 0

        for row, item in enumerate(self.cart):
            self.table.insertRow(row)
            item['total'] = item['qty'] * item['price']
            total_bill += item['total']

            self.table.setItem(row, 0, QTableWidgetItem(str(item['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(item['name']))
            self.table.setItem(row, 2, QTableWidgetItem(str(item['price'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(item['qty'])))
            self.table.setItem(row, 4, QTableWidgetItem(str(item['total'])))

        self.total_label.setText(f"{total_bill:,.2f}")

    def remove_item(self):
        row = self.table.currentRow()
        if row >= 0:
            del self.cart[row]
            self.update_table()

    def clear_cart(self):
        self.cart = []
        self.update_table()
        # إعادة تعيين الحقول
        self.customer_combo.setCurrentIndex(0)
        self.doctor_input.clear()

    def checkout(self):  # أو process_sale
        if not self.cart:
            QMessageBox.warning(self, "تنبيه", "السلة فارغة!")
            return

        total_amount = float(self.total_label.text().replace(',', ''))

        # جلب البيانات
        customer_idx = self.customer_combo.currentIndex()
        customer_id = self.customer_combo.itemData(customer_idx)
        doctor_name = self.doctor_input.text()

        # تنفيذ البيع
        # ملاحظة: النتيجة الآن هي (success, result) حيث result إما رقم الفاتورة أو رسالة خطأ
        success, result = self.dao.process_sale(1, self.cart, total_amount, customer_id, doctor_name)

        if success:
            sale_id = result  # في حالة النجاح، المتغير الثاني هو رقم الفاتورة

            # 1. إظهار رسالة نجاح
            QMessageBox.information(self, "نجاح", f"تم حفظ الفاتورة رقم {sale_id} بنجاح")

            # 2. طباعة الفاتورة تلقائياً
            try:
                # تجهيز البيانات للطباعة
                from utils.pdf_generator import create_invoice_pdf
                # نحتاج تمرير التاريخ واسم الكاشير (يمكنك تحسينها لاحقاً)
                import datetime
                current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                pdf_path = create_invoice_pdf(self.cart, total_amount, sale_id, "Admin", current_date)

                if pdf_path:
                    # فتح الملف
                    if os.name == 'nt':
                        os.startfile(pdf_path)
                    else:
                        os.system(f"xdg-open '{pdf_path}'")
            except Exception as e:
                print(f"Printing Error: {e}")

            # 3. تنظيف السلة
            self.clear_cart()
        else:
            msg = result  # في حالة الفشل، المتغير الثاني هو رسالة الخطأ
            QMessageBox.critical(self, "فشل", msg)