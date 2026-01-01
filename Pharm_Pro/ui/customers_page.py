from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QDialog, QFormLayout, QTextEdit, QDialogButtonBox, QLabel)
from PyQt5.QtCore import Qt
from models.customers_dao import CustomersDAO


# --- نافذة إضافة عميل ---
class AddCustomerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة عميل جديد")
        self.resize(500, 450)
        self.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")

        self.dao = CustomersDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(20)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم العميل الثلاثي")
        self.name_input.setFixedHeight(40)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف")
        self.phone_input.setFixedHeight(40)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("البريد الإلكتروني (اختياري)")
        self.email_input.setFixedHeight(40)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("ملاحظات طبية أو عامة...")
        self.notes_input.setFixedHeight(80)

        form_layout.addRow("الاسم:", self.name_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("الإيميل:", self.email_input)
        form_layout.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        for btn in self.buttons.buttons():
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(40)
            btn.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.buttons.accepted.connect(self.save_customer)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_customer(self):
        name = self.name_input.text()
        phone = self.phone_input.text()
        email = self.email_input.text()
        notes = self.notes_input.toPlainText()

        if not name:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم العميل")
            return

        success, msg = self.dao.add_customer(name, phone, email, notes)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "خطأ", msg)


# --- الصفحة الرئيسية للعملاء ---
class CustomersPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = CustomersDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("سجل العملاء والمرضى")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; margin-bottom: 10px;")
        layout.addWidget(title)

        # الشريط العلوي
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 بحث باسم العميل أو الهاتف...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet("font-size: 18px; padding: 0 10px; border-radius: 5px; border: 1px solid #ccc;")
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input)

        self.btn_add = QPushButton("➕ إضافة عميل")
        self.btn_add.setFixedHeight(50)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; font-size: 18px; border-radius: 5px;")

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet("font-size: 18px; padding: 0 15px;")

        self.btn_delete = QPushButton("🗑️ حذف")
        self.btn_delete.setFixedHeight(50)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 0 20px; font-size: 18px; border-radius: 5px;")

        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_delete)

        layout.addLayout(top_bar)

        # الجدول
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "الاسم", "الهاتف", "الإيميل", "ملاحظات"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 16px; } QHeaderView::section { font-size: 16px; font-weight: bold; }")

        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        customers = self.dao.get_all_customers()
        self.fill_table(customers)

    def search_data(self):
        text = self.search_input.text()
        if text:
            customers = self.dao.search_customer(text)
        else:
            customers = self.dao.get_all_customers()
        self.fill_table(customers)

    def fill_table(self, data):
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)
            for col_idx, col_data in enumerate(row_data):
                item = QTableWidgetItem(str(col_data))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        dialog = AddCustomerDialog(self)
        if dialog.exec_():
            self.load_data()

    def delete_selected(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد عميل لحذفه")
            return

        customer_id = self.table.item(selected_row, 0).text()
        name = self.table.item(selected_row, 1).text()

        confirm = QMessageBox.question(self, "تأكيد الحذف", f"هل أنت متأكد من حذف العميل {name}؟",
                                       QMessageBox.Yes | QMessageBox.No)

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_customer(customer_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم", msg)
            else:
                QMessageBox.critical(self, "خطأ", msg)