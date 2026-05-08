"""
وظيفة الملف: واجهة إدارة العملاء والمرضى.
الطبقة: Presentation Layer

ملاحظة معمارية وأمنية:
- [UI RBAC]&#58; الإضافة والتعديل متاحان للمستخدم النشط لتسهيل العمل التشغيلي،
  بينما الحذف الإداري محجوب عن غير المدراء.
- [Extended Patient Profile]&#58; دعم الحقول الموسعة:
  الاسم، الهاتف، البريد، رقم الهوية، تاريخ الميلاد، الجنس، العنوان،
  الملاحظات الطبية، الملاحظات العامة، وحالة النشاط.
- [Dumb Client]&#58; الواجهة لا تطبق منطق التفرّد أو الحذف المرجعي بنفسها،
  بل تمرر البيانات إلى CustomersDAO وتعتمد على رفض النواة ورسائلها.
- [Clinical Usability]&#58; تم فصل (الملاحظات الطبية) عن (الملاحظات العامة)
  وعرضها بشكل واضح داخل الجدول والنوافذ.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QDialog, QFormLayout, QTextEdit, QDialogButtonBox,
    QLabel, QAbstractItemView, QComboBox, QDateEdit, QCheckBox,
    QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor
from models.customers_dao import CustomersDAO


# ==========================================
# Helpers
# ==========================================

def build_required_label(text):
    label = QLabel(f"{text} <span style='color:#E74C3C;'>*</span>:")
    label.setTextFormat(Qt.RichText)
    return label


def normalize_table_text(value):
    if value is None:
        return ""
    return str(value)


def gender_to_display(value):
    mapping = {
        "male": "ذكر",
        "female": "أنثى",
        "other": "أخرى"
    }
    return mapping.get((value or "").strip().lower(), "")


def display_to_gender(value):
    mapping = {
        "ذكر": "male",
        "أنثى": "female",
        "أخرى": "other"
    }
    return mapping.get(value, None)


# ==========================================
# Base Dialog
# ==========================================

class BaseCustomerDialog(QDialog):
    def __init__(self, requester_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.dao = CustomersDAO()
        self._null_date = QDate(1900, 1, 1)

        self.setMinimumSize(620, 640)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("""
            QDialog {
                font-family: 'Times New Roman';
                font-size: 16px;
                background-color: #F5F6FA;
            }
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2C3E50;
            }
            QLineEdit, QTextEdit, QComboBox, QDateEdit {
                border: 1px solid #BDC3C7;
                border-radius: 6px;
                font-size: 16px;
                padding: 6px;
                background-color: white;
            }
            QLineEdit {
                min-height: 36px;
            }
            QComboBox, QDateEdit {
                min-height: 38px;
            }
            QTextEdit {
                min-height: 90px;
            }
            QCheckBox {
                font-size: 15px;
                font-weight: bold;
                color: #2C3E50;
            }
        """)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(12)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            color: #7F8C8D;
            font-size: 14px;
            font-weight: normal;
            padding: 4px 0;
        """)
        content_layout.addWidget(self.info_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignTop)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("الاسم الكامل / الثلاثي (إلزامي)")

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف الفريد")

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("البريد الإلكتروني الفريد")

        self.national_id_input = QLineEdit()
        self.national_id_input.setPlaceholderText("رقم الهوية / الإقامة / الرقم الوطني")

        self.date_of_birth_input = QDateEdit()
        self.date_of_birth_input.setCalendarPopup(True)
        self.date_of_birth_input.setDisplayFormat("yyyy-MM-dd")
        self.date_of_birth_input.setMinimumDate(self._null_date)
        self.date_of_birth_input.setMaximumDate(QDate.currentDate())
        self.date_of_birth_input.setSpecialValueText("غير محدد")
        self.date_of_birth_input.setDate(self._null_date)

        self.gender_combo = QComboBox()
        self.gender_combo.addItem("غير محدد", None)
        self.gender_combo.addItem("ذكر", "male")
        self.gender_combo.addItem("أنثى", "female")
        self.gender_combo.addItem("أخرى", "other")

        self.address_input = QTextEdit()
        self.address_input.setPlaceholderText("العنوان التفصيلي أو المنطقة...")

        self.medical_notes_input = QTextEdit()
        self.medical_notes_input.setPlaceholderText(
            "ملاحظات طبية: حساسية، أمراض مزمنة، موانع، حمل، رضاعة..."
        )

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("ملاحظات عامة إدارية أو تشغيلية...")

        self.is_active_check = QCheckBox("السجل نشط")
        self.is_active_check.setChecked(True)

        form_layout.addRow(build_required_label("الاسم"), self.name_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("الإيميل:", self.email_input)
        form_layout.addRow("رقم الهوية:", self.national_id_input)
        form_layout.addRow("تاريخ الميلاد:", self.date_of_birth_input)
        form_layout.addRow("الجنس:", self.gender_combo)
        form_layout.addRow("العنوان:", self.address_input)
        form_layout.addRow("ملاحظات طبية:", self.medical_notes_input)
        form_layout.addRow("ملاحظات عامة:", self.notes_input)
        form_layout.addRow("الحالة:", self.is_active_check)

        content_layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        content_layout.addWidget(self.buttons)

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _collect_form_data(self):
        dob = None
        if self.date_of_birth_input.date() != self._null_date:
            dob = self.date_of_birth_input.date().toString("yyyy-MM-dd")

        return {
            "name": self.name_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "email": self.email_input.text().strip(),
            "national_id": self.national_id_input.text().strip(),
            "date_of_birth": dob,
            "gender": self.gender_combo.currentData(),
            "address": self.address_input.toPlainText().strip(),
            "medical_notes": self.medical_notes_input.toPlainText().strip(),
            "notes": self.notes_input.toPlainText().strip(),
            "is_active": 1 if self.is_active_check.isChecked() else 0
        }

    def _set_form_data(self, data):
        self.name_input.setText(data.get("name") or "")
        self.phone_input.setText(data.get("phone") or "")
        self.email_input.setText(data.get("email") or "")
        self.national_id_input.setText(data.get("national_id") or "")

        dob = data.get("date_of_birth")
        if dob:
            parsed = QDate.fromString(dob, "yyyy-MM-dd")
            self.date_of_birth_input.setDate(parsed if parsed.isValid() else self._null_date)
        else:
            self.date_of_birth_input.setDate(self._null_date)

        gender = data.get("gender")
        idx = self.gender_combo.findData(gender)
        self.gender_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.address_input.setPlainText(data.get("address") or "")
        self.medical_notes_input.setPlainText(data.get("medical_notes") or "")
        self.notes_input.setPlainText(data.get("notes") or "")
        self.is_active_check.setChecked(bool(data.get("is_active", 1)))

    def _validate_before_submit(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "تنبيه", "الاسم حقل إلزامي.")
            self.name_input.setFocus()
            return False
        return True


# ==========================================
# Add Dialog
# ==========================================

class AddCustomerDialog(BaseCustomerDialog):
    def __init__(self, requester_id, parent=None):
        super().__init__(requester_id, parent)
        self.setWindowTitle("إضافة عميل / مريض جديد")
        self.info_label.setText(
            "يمكنك تسجيل بيانات المريض بشكل موسع. "
            "النواة سترفض أي هاتف أو بريد أو رقم هوية مكرر إذا كان مستخدماً مسبقاً."
        )
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; min-height: 40px;"
        )
        self.buttons.accepted.connect(self.save_customer)
        self.buttons.rejected.connect(self.reject)

    def save_customer(self):
        if not self._validate_before_submit():
            return

        payload = self._collect_form_data()

        success, msg = self.dao.add_customer(
            requester_id=self.requester_id,
            name=payload["name"],
            phone=payload["phone"],
            email=payload["email"],
            notes=payload["notes"],
            national_id=payload["national_id"],
            date_of_birth=payload["date_of_birth"],
            gender=payload["gender"],
            address=payload["address"],
            medical_notes=payload["medical_notes"],
            is_active=payload["is_active"]
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


# ==========================================
# Edit Dialog
# ==========================================

class EditCustomerDialog(BaseCustomerDialog):
    def __init__(self, requester_id, customer_id, parent=None):
        self.customer_id = customer_id
        super().__init__(requester_id, parent)
        self.setWindowTitle("تعديل بيانات العميل / المريض")
        self.info_label.setText(
            "يمكنك تعديل البيانات الأساسية والسريرية. "
            "أي تعارض في الهاتف أو البريد أو الهوية سيتم رفضه من النواة."
        )
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ التعديلات")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #F39C12; color: white; font-weight: bold; min-height: 40px;"
        )
        self.buttons.accepted.connect(self.update_customer)
        self.buttons.rejected.connect(self.reject)

        self.load_current_data()

    def load_current_data(self):
        row = self.dao.get_customer_by_id(self.customer_id)
        if not row:
            QMessageBox.critical(self, "خطأ", "تعذر تحميل بيانات العميل / المريض.")
            self.reject()
            return

        data = {
            "name": row[1],
            "phone": row[2],
            "email": row[3],
            "national_id": row[4],
            "date_of_birth": row[5],
            "gender": row[6],
            "address": row[7],
            "medical_notes": row[8],
            "is_active": row[9],
            "notes": row[10]
        }
        self._set_form_data(data)

    def update_customer(self):
        if not self._validate_before_submit():
            return

        payload = self._collect_form_data()

        success, msg = self.dao.update_customer(
            requester_id=self.requester_id,
            customer_id=self.customer_id,
            name=payload["name"],
            phone=payload["phone"],
            email=payload["email"],
            notes=payload["notes"],
            national_id=payload["national_id"],
            date_of_birth=payload["date_of_birth"],
            gender=payload["gender"],
            address=payload["address"],
            medical_notes=payload["medical_notes"],
            is_active=payload["is_active"]
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


# ==========================================
# Main Page
# ==========================================

class CustomersPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()
        self.session = session_data if session_data is not None else {}
        self.requester_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = CustomersDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("سجل العملاء والمرضى")
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #2C3E50;
            margin-bottom: 10px;
            font-family: 'Times New Roman';
        """)
        layout.addWidget(title)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث بالاسم أو الهاتف أو البريد أو رقم الهوية...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet("""
            font-size: 18px;
            padding: 0 10px;
            border-radius: 5px;
            border: 1px solid #ccc;
            font-family: 'Times New Roman';
        """)
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input, stretch=3)

        self.btn_add = QPushButton("إضافة عميل / مريض")
        self.btn_add.setFixedHeight(50)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet("""
            background-color: #27AE60;
            color: white;
            padding: 0 20px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 5px;
            font-family: 'Times New Roman';
        """)

        self.btn_edit = QPushButton("تعديل البيانات")
        self.btn_edit.setFixedHeight(50)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self.open_edit_dialog)
        self.btn_edit.setStyleSheet("""
            background-color: #F39C12;
            color: white;
            padding: 0 20px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 5px;
            font-family: 'Times New Roman';
        """)

        self.btn_refresh = QPushButton("تحديث")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet("""
            font-size: 18px;
            padding: 0 15px;
            font-family: 'Times New Roman';
        """)

        self.btn_delete = QPushButton("حذف (إداري)")
        self.btn_delete.setFixedHeight(50)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet("""
            background-color: #E74C3C;
            color: white;
            padding: 0 20px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 5px;
            font-family: 'Times New Roman';
        """)

        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_edit)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_delete)

        if self.user_role != 'admin':
            self.btn_delete.hide()

        layout.addLayout(top_bar)

        self.info_bar = QLabel(
            "الحقول الفريدة المتوقعة في النواة: الهاتف، البريد الإلكتروني، رقم الهوية. "
            "يمكن تكرار الاسم، لكن سيظهر تنبيه عند الاشتباه."
        )
        self.info_bar.setWordWrap(True)
        self.info_bar.setStyleSheet("""
            color: #566573;
            font-size: 14px;
            font-family: 'Times New Roman';
            background-color: #F8F9F9;
            border: 1px solid #E5E7E9;
            border-radius: 6px;
            padding: 8px;
        """)
        layout.addWidget(self.info_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "الاسم",
            "الهاتف",
            "الإيميل",
            "رقم الهوية",
            "تاريخ الميلاد",
            "الجنس",
            "العنوان",
            "ملاحظات طبية",
            "الحالة",
            "ملاحظات عامة"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet("""
            QTableWidget {
                font-size: 15px;
                font-family: 'Times New Roman';
            }
            QHeaderView::section {
                font-size: 15px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
        """)

        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        customers = self.dao.get_all_customers(active_only=False)
        self.fill_table(customers)

    def search_data(self):
        text = self.search_input.text().strip()
        if text:
            customers = self.dao.search_customer(text, active_only=False)
        else:
            customers = self.dao.get_all_customers(active_only=False)
        self.fill_table(customers)

    def fill_table(self, data):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            customer_id = row_data[0]
            name = row_data[1]
            phone = row_data[2]
            email = row_data[3]
            national_id = row_data[4]
            date_of_birth = row_data[5]
            gender = gender_to_display(row_data[6])
            address = row_data[7]
            medical_notes = row_data[8]
            is_active = row_data[9]
            notes = row_data[10]

            display_row = [
                customer_id,
                name,
                phone,
                email,
                national_id,
                date_of_birth,
                gender,
                address,
                medical_notes,
                "نشط" if int(is_active) == 1 else "غير نشط",
                notes
            ]

            for col_idx, col_data in enumerate(display_row):
                item = QTableWidgetItem(normalize_table_text(col_data))
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 9:
                    if int(is_active) == 1:
                        item.setForeground(QColor("#27AE60"))
                    else:
                        item.setForeground(QColor("#C0392B"))

                if int(is_active) != 1:
                    item.setBackground(QColor("#F4F6F6"))

                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        if not self.requester_id:
            QMessageBox.critical(self, "خطأ أمني", "تعذر تحديد المستخدم الحالي.")
            return

        dialog = AddCustomerDialog(self.requester_id, self)
        if dialog.exec_():
            self.load_data()

    def open_edit_dialog(self):
        if not self.requester_id:
            QMessageBox.critical(self, "خطأ أمني", "تعذر تحديد المستخدم الحالي.")
            return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد عميل / مريض لتعديل بياناته.")
            return

        customer_id = int(self.table.item(selected_row, 0).text())
        dialog = EditCustomerDialog(self.requester_id, customer_id, self)
        if dialog.exec_():
            self.load_data()

    def delete_selected(self):
        if not self.requester_id:
            QMessageBox.critical(self, "خطأ أمني", "تعذر تحديد المستخدم الحالي.")
            return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد عميل / مريض لحذفه.")
            return

        customer_id = int(self.table.item(selected_row, 0).text())
        name = self.table.item(selected_row, 1).text()

        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف الإداري",
            f"هل أنت متأكد من حذف العميل / المريض ({name}) نهائياً؟\n"
            f"سيتم رفض العملية إذا كان هناك ارتباط مالي أو سريري أو رقابي.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_customer(self.requester_id, customer_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم الحذف", msg)
            else:
                QMessageBox.critical(self, "رفض العملية", msg)