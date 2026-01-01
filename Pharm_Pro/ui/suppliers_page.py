from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox, QLabel, QSizePolicy)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from models.suppliers_dao import SuppliersDAO


# --- نافذة إضافة مورد ---
class AddSupplierDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة مورد جديد")
        self.resize(500, 400)  # حجم كبير للنافذة المنبثقة
        self.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")

        self.dao = SuppliersDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(20)

        # الحقول بتصميم كبير
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم المندوب / المورد")
        self.name_input.setFixedHeight(40)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف")
        self.phone_input.setFixedHeight(40)

        self.company_input = QLineEdit()
        self.company_input.setPlaceholderText("اسم الشركة")
        self.company_input.setFixedHeight(40)

        self.balance_input = QDoubleSpinBox()
        self.balance_input.setMaximum(1000000)  # مليون
        self.balance_input.setFixedHeight(40)

        form_layout.addRow("الاسم:", self.name_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("الشركة:", self.company_input)
        form_layout.addRow("الرصيد الافتتاحي:", self.balance_input)

        layout.addLayout(form_layout)

        # الأزرار
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        # تنسيق الأزرار
        for btn in self.buttons.buttons():
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(40)
            btn.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.buttons.accepted.connect(self.save_supplier)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_supplier(self):
        name = self.name_input.text()
        phone = self.phone_input.text()
        company = self.company_input.text()
        balance = self.balance_input.value()

        if not name:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم المورد على الأقل")
            return

        success, msg = self.dao.add_supplier(name, phone, company, balance)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "خطأ", msg)


# --- الصفحة الرئيسية للموردين ---
class SuppliersPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = SuppliersDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # العنوان
        title = QLabel("إدارة الموردين والشركات")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; margin-bottom: 10px;")
        layout.addWidget(title)

        # الشريط العلوي (بحث + أزرار)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 بحث باسم المورد أو الشركة...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet("font-size: 18px; padding: 0 10px; border-radius: 5px; border: 1px solid #ccc;")
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input)

        self.btn_add = QPushButton("➕ إضافة مورد")
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
        self.table.setHorizontalHeaderLabels(["ID", "الاسم", "الهاتف", "الشركة", "الرصيد"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        # تكبير خط الجدول
        self.table.setStyleSheet(
            "QTableWidget { font-size: 16px; } QHeaderView::section { font-size: 16px; font-weight: bold; }")

        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        suppliers = self.dao.get_all_suppliers()
        self.fill_table(suppliers)

    def search_data(self):
        text = self.search_input.text()
        if text:
            suppliers = self.dao.search_supplier(text)
        else:
            suppliers = self.dao.get_all_suppliers()
        self.fill_table(suppliers)

    def fill_table(self, data):
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)
            for col_idx, col_data in enumerate(row_data):
                item = QTableWidgetItem(str(col_data))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        dialog = AddSupplierDialog(self)
        if dialog.exec_():
            self.load_data()

    def delete_selected(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مورد لحذفه")
            return

        supplier_id = self.table.item(selected_row, 0).text()
        name = self.table.item(selected_row, 1).text()

        confirm = QMessageBox.question(self, "تأكيد الحذف", f"هل أنت متأكد من حذف المورد {name}؟",
                                       QMessageBox.Yes | QMessageBox.No)

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_supplier(supplier_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم", msg)
            else:
                QMessageBox.critical(self, "خطأ", msg)