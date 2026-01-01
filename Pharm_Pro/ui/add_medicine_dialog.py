from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QDoubleSpinBox, QSpinBox, QDateEdit, QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import QDate, Qt
from models.medicine_dao import MedicineDAO


class AddMedicineDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة دواء جديد")
        self.resize(550, 550)  # تكبير النافذة
        # تطبيق الخط الموحد
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit { 
                height: 40px; font-size: 16px; padding: 5px; border-radius: 5px; border: 1px solid #BDC3C7; 
            }
            QLabel { font-weight: bold; font-size: 16px; }
            QPushButton { height: 40px; font-size: 16px; font-weight: bold; }
        """)

        self.dao = MedicineDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        # الحقول
        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("امسح الباركود...")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("الاسم التجاري للدواء")

        # --- الحقل الجديد ---
        self.active_ing_input = QLineEdit()
        self.active_ing_input.setPlaceholderText("المادة الفعالة (مثلاً: Paracetamol)")

        self.buy_price_input = QDoubleSpinBox()
        self.buy_price_input.setMaximum(100000)

        self.sell_price_input = QDoubleSpinBox()
        self.sell_price_input.setMaximum(100000)

        self.qty_input = QSpinBox()
        self.qty_input.setMaximum(10000)

        self.expiry_input = QDateEdit()
        self.expiry_input.setDate(QDate.currentDate().addDays(365))
        self.expiry_input.setCalendarPopup(True)

        form_layout.addRow("الباركود:", self.barcode_input)
        form_layout.addRow("اسم الدواء:", self.name_input)
        form_layout.addRow("المادة الفعالة:", self.active_ing_input)  # إضافة للواجهة
        form_layout.addRow("سعر الشراء:", self.buy_price_input)
        form_layout.addRow("سعر البيع:", self.sell_price_input)
        form_layout.addRow("الكمية:", self.qty_input)
        form_layout.addRow("تاريخ الانتهاء:", self.expiry_input)

        layout.addLayout(form_layout)

        # الأزرار
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ الدواء")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.save_medicine)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_medicine(self):
        barcode = self.barcode_input.text()
        name = self.name_input.text()
        active_ing = self.active_ing_input.text()  # قراءة الحقل الجديد
        buy_price = self.buy_price_input.value()
        sell_price = self.sell_price_input.value()
        qty = self.qty_input.value()
        expiry = self.expiry_input.date().toString("yyyy-MM-dd")

        if not name or not barcode:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال الاسم والباركود")
            return

        success, message = self.dao.add_medicine(barcode, name, active_ing, buy_price, sell_price, qty, expiry)

        if success:
            QMessageBox.information(self, "نجاح", message)
            self.accept()
        else:
            QMessageBox.critical(self, "خطأ", message)