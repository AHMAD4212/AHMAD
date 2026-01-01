from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QLabel, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox, QFrame)
from PyQt5.QtCore import Qt, QDate
from models.purchases_dao import PurchasesDAO
from models.suppliers_dao import SuppliersDAO
from models.medicine_dao import MedicineDAO


class PurchasesPage(QWidget):
    def __init__(self):
        super().__init__()
        self.purchase_dao = PurchasesDAO()
        self.supplier_dao = SuppliersDAO()
        self.medicine_dao = MedicineDAO()

        self.cart = []  # سلة الشراء
        self.init_ui()
        self.load_suppliers()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("تسجيل فاتورة شراء جديدة")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        layout.addWidget(title)

        # --- بيانات الفاتورة العلوية ---
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white; border-radius: 10px; padding: 10px;")
        form_layout = QHBoxLayout(form_frame)

        self.supplier_combo = QComboBox()
        self.supplier_combo.setPlaceholderText("اختر المورد")
        self.supplier_combo.setFixedHeight(40)

        self.inv_num_input = QLineEdit()
        self.inv_num_input.setPlaceholderText("رقم فاتورة المورد (اختياري)")
        self.inv_num_input.setFixedHeight(40)

        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setFixedHeight(40)

        form_layout.addWidget(QLabel("المورد:"))
        form_layout.addWidget(self.supplier_combo, stretch=2)
        form_layout.addWidget(QLabel("رقم الفاتورة:"))
        form_layout.addWidget(self.inv_num_input, stretch=1)
        form_layout.addWidget(QLabel("التاريخ:"))
        form_layout.addWidget(self.date_input, stretch=1)

        layout.addWidget(form_frame)

        # --- منطقة البحث والإضافة ---
        action_layout = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث عن دواء لإضافته (اسم أو باركود)...")
        self.search_input.setFixedHeight(40)
        self.search_input.returnPressed.connect(self.add_item_to_cart)  # عند ضغط Enter

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10000)
        self.qty_spin.setPrefix("الكمية: ")
        self.qty_spin.setFixedHeight(40)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setRange(0, 100000)
        self.cost_spin.setPrefix("سعر الشراء: ")
        self.cost_spin.setFixedHeight(40)

        btn_add = QPushButton("⬇ إضافة للفاتورة")
        btn_add.clicked.connect(self.add_item_to_cart)
        btn_add.setFixedHeight(40)
        btn_add.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold;")

        action_layout.addWidget(self.search_input, stretch=3)
        action_layout.addWidget(self.qty_spin, stretch=1)
        action_layout.addWidget(self.cost_spin, stretch=1)
        action_layout.addWidget(btn_add, stretch=1)

        layout.addLayout(action_layout)

        # --- جدول الأصناف ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "اسم الدواء", "الكمية", "سعر الشراء", "الإجمالي"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        layout.addWidget(self.table)

        # --- التذييل (المجموع وزر الحفظ) ---
        footer_layout = QHBoxLayout()

        self.total_label = QLabel("الإجمالي: 0.00")
        self.total_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #27AE60; font-family: 'Times New Roman';")

        btn_save = QPushButton("💾 حفظ الفاتورة وترحيل للمخزون")
        btn_save.clicked.connect(self.save_invoice)
        btn_save.setFixedHeight(50)
        btn_save.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; font-size: 18px; padding: 0 30px;")

        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch()
        footer_layout.addWidget(btn_save)

        layout.addLayout(footer_layout)
        self.setLayout(layout)

    def load_suppliers(self):
        suppliers = self.supplier_dao.get_all_suppliers()
        self.supplier_combo.clear()
        for sup in suppliers:
            # sup = (id, name, ...)
            self.supplier_combo.addItem(sup[1], sup[0])  # Text=Name, Data=ID

    def add_item_to_cart(self):
        text = self.search_input.text()
        if not text: return

        # البحث عن الدواء لجلب بياناته
        medicines = self.medicine_dao.search_medicine(text)
        if not medicines:
            QMessageBox.warning(self, "تنبيه", "الدواء غير موجود!")
            return

        # نأخذ أول نتيجة
        med = medicines[0]  # (id, barcode, name, active, buy, sell, qty, expiry)
        med_id = med[0]
        name = med[2]

        qty = self.qty_spin.value()
        cost = self.cost_spin.value()

        # إذا لم يحدد المستخدم سعراً، نستخدم السعر المسجل سابقاً
        if cost == 0:
            cost = med[4]

            # الإضافة للسلة
        self.cart.append({
            "id": med_id,
            "name": name,
            "qty": qty,
            "cost": cost,
            "total": qty * cost
        })

        self.update_table()
        self.search_input.clear()
        self.search_input.setFocus()

    def update_table(self):
        self.table.setRowCount(0)
        total_bill = 0
        for row, item in enumerate(self.cart):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(item['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(item['name']))
            self.table.setItem(row, 2, QTableWidgetItem(str(item['qty'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(item['cost'])))
            self.table.setItem(row, 4, QTableWidgetItem(str(item['total'])))
            total_bill += item['total']

        self.total_label.setText(f"الإجمالي: {total_bill:,.2f}")

    def save_invoice(self):
        if not self.cart:
            QMessageBox.warning(self, "تنبيه", "الفاتورة فارغة!")
            return

        supplier_idx = self.supplier_combo.currentIndex()
        if supplier_idx < 0:
            QMessageBox.warning(self, "تنبيه", "اختر المورد أولاً")
            return

        supplier_id = self.supplier_combo.itemData(supplier_idx)
        inv_num = self.inv_num_input.text()
        date = self.date_input.date().toString("yyyy-MM-dd")
        total = float(self.total_label.text().split(":")[1].replace(",", ""))

        success, msg = self.purchase_dao.add_purchase_invoice(supplier_id, inv_num, date, total, self.cart)

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.cart = []
            self.update_table()
            self.inv_num_input.clear()
        else:
            QMessageBox.critical(self, "خطأ", msg)