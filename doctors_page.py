"""
وظيفة الملف: واجهة إدارة سجلات الأطباء.
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [UI RBAC]: أزرار الإضافة، التعديل، والتعطيل محجوبة تماماً عن غير المدراء.
- [Operational Access]: يُسمح لغير المدراء بالبحث وعرض الأطباء النشطين فقط لتسهيل عملهم.
- [Dumb Client]: الواجهة لا تتخذ قرارات، بل تمرر (requester_id) للنواة وتعرض رسائل القبول أو الرفض.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QDialog, QFormLayout, QTextEdit, QDialogButtonBox, QLabel, QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from models.doctors_dao import DoctorsDAO


# ==========================================
# النوافذ المنبثقة (Dialogs)
# ==========================================

class AddDoctorDialog(QDialog):
    def __init__(self, requester_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.setWindowTitle("إضافة طبيب جديد")
        self.resize(450, 400)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }
            QLineEdit, QTextEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; font-size: 16px;}
            QLineEdit { height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50; }
        """)

        self.dao = DoctorsDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم الطبيب الثلاثي (إلزامي)")

        self.specialty_input = QLineEdit()
        self.specialty_input.setPlaceholderText("التخصص الطبي")

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف للتواصل")

        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("رقم الرخصة الطبية (فريد)")

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("ملاحظات إضافية، أوقات الدوام، عنوان العيادة...")
        self.notes_input.setFixedHeight(80)

        form_layout.addRow("اسم الطبيب:", self.name_input)
        form_layout.addRow("التخصص:", self.specialty_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("رقم الرخصة:", self.license_input)
        form_layout.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ واعتماد")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.save_doctor)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_doctor(self):
        name = self.name_input.text()
        specialty = self.specialty_input.text()
        phone = self.phone_input.text()
        license_num = self.license_input.text()
        notes = self.notes_input.toPlainText()

        if not name.strip():
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم الطبيب بشكل إلزامي.")
            return

        success, msg = self.dao.add_doctor(self.requester_id, name, specialty, phone, license_num, notes)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class EditDoctorDialog(QDialog):
    def __init__(self, requester_id, doctor_id, current_data, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.doctor_id = doctor_id
        self.setWindowTitle("تعديل بيانات الطبيب")
        self.resize(450, 400)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }
            QLineEdit, QTextEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; font-size: 16px;}
            QLineEdit { height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50; }
        """)

        self.dao = DoctorsDAO()
        self.setup_ui(current_data)

    def setup_ui(self, data):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.name_input = QLineEdit(data.get('name', ''))
        self.specialty_input = QLineEdit(data.get('specialty', ''))
        self.phone_input = QLineEdit(data.get('phone', ''))
        self.license_input = QLineEdit(data.get('license', ''))

        self.notes_input = QTextEdit()
        self.notes_input.setText(data.get('notes', ''))
        self.notes_input.setFixedHeight(80)

        form_layout.addRow("اسم الطبيب:", self.name_input)
        form_layout.addRow("التخصص:", self.specialty_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("رقم الرخصة:", self.license_input)
        form_layout.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ التعديلات")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #F39C12; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.update_doctor)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def update_doctor(self):
        name = self.name_input.text()
        specialty = self.specialty_input.text()
        phone = self.phone_input.text()
        license_num = self.license_input.text()
        notes = self.notes_input.toPlainText()

        if not name.strip():
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم الطبيب بشكل إلزامي.")
            return

        success, msg = self.dao.update_doctor(self.requester_id, self.doctor_id, name, specialty, phone, license_num,
                                              notes)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


# ==========================================
# الصفحة الرئيسية للأطباء
# ==========================================

class DoctorsPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()
        self.session = session_data if session_data is not None else {}
        self.requester_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = DoctorsDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("دليل الأطباء المعالجين")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; margin-bottom: 10px; font-family: 'Times New Roman';")
        layout.addWidget(title)

        # الشريط العلوي
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(" بحث باسم الطبيب، رقم الرخصة، أو الهاتف...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet(
            "font-size: 18px; padding: 0 10px; border-radius: 5px; border: 1px solid #ccc; font-family: 'Times New Roman';")
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input)

        self.btn_add = QPushButton(" إضافة طبيب")
        self.btn_add.setFixedHeight(50)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; font-size: 18px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';")

        self.btn_edit = QPushButton(" تعديل البيانات")
        self.btn_edit.setFixedHeight(50)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self.open_edit_dialog)
        self.btn_edit.setStyleSheet(
            "background-color: #F39C12; color: white; padding: 0 20px; font-size: 18px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';")

        self.btn_refresh = QPushButton(" تحديث")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet("font-size: 18px; padding: 0 15px; font-family: 'Times New Roman';")

        self.btn_toggle_status = QPushButton(" تفعيل / تعطيل (Soft Delete)")
        self.btn_toggle_status.setFixedHeight(50)
        self.btn_toggle_status.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_status.clicked.connect(self.toggle_selected_doctor)
        self.btn_toggle_status.setStyleSheet(
            "background-color: #C0392B; color: white; padding: 0 20px; font-size: 18px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';")

        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_edit)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_toggle_status)

        # UI RBAC: حجب أدوات الإدارة عن غير المدراء
        if self.user_role != 'admin':
            self.btn_add.hide()
            self.btn_edit.hide()
            self.btn_toggle_status.hide()

        layout.addLayout(top_bar)

        # الجدول
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "اسم الطبيب", "التخصص", "الهاتف", "رقم الرخصة", "ملاحظات", "الحالة"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)

        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 16px; font-family: 'Times New Roman'; } QHeaderView::section { font-size: 16px; font-weight: bold; font-family: 'Times New Roman'; }")

        layout.addWidget(self.table)
        self.setLayout(layout)

    def _get_active_flag(self):
        # غير المدير يرى الأطباء النشطين فقط، المدير يرى الجميع لإدارتهم
        return False if self.user_role == 'admin' else True

    def load_data(self):
        doctors = self.dao.get_all_doctors(active_only=self._get_active_flag())
        self.fill_table(doctors)

    def search_data(self):
        text = self.search_input.text()
        if text:
            doctors = self.dao.search_doctor(text, active_only=self._get_active_flag())
        else:
            doctors = self.dao.get_all_doctors(active_only=self._get_active_flag())
        self.fill_table(doctors)

    def fill_table(self, data):
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)
            # row_data = (id, name, specialty, phone, license_number, notes, is_active)

            is_active = row_data[6]
            status_text = "نشط" if is_active else "معطل"

            items_text = [
                str(row_data[0]),
                row_data[1] or "",
                row_data[2] or "",
                row_data[3] or "",
                row_data[4] or "",
                row_data[5] or "",
                status_text
            ]

            for col_idx, val in enumerate(items_text):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)

                # تلوين حالة الحساب وتظليل السطر المعطل للمدير
                if is_active == 0:
                    item.setForeground(QColor("#C0392B"))
                    item.setBackground(QColor("#FDEDEC"))
                elif col_idx == 6:
                    item.setForeground(QColor("#27AE60"))

                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        if not self.requester_id: return
        dialog = AddDoctorDialog(self.requester_id, self)
        if dialog.exec_():
            self.load_data()

    def open_edit_dialog(self):
        if not self.requester_id: return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد طبيب من الجدول لتعديل بياناته.")
            return

        doctor_id = int(self.table.item(selected_row, 0).text())
        current_data = {
            'name': self.table.item(selected_row, 1).text(),
            'specialty': self.table.item(selected_row, 2).text(),
            'phone': self.table.item(selected_row, 3).text(),
            'license': self.table.item(selected_row, 4).text(),
            'notes': self.table.item(selected_row, 5).text(),
        }

        dialog = EditDoctorDialog(self.requester_id, doctor_id, current_data, self)
        if dialog.exec_():
            self.load_data()

    def toggle_selected_doctor(self):
        if not self.requester_id: return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد طبيب لتغيير حالته.")
            return

        doctor_id = int(self.table.item(selected_row, 0).text())
        name = self.table.item(selected_row, 1).text()
        status_text = self.table.item(selected_row, 6).text()

        make_active = (status_text == "معطل")
        action_name = "تفعيل" if make_active else "تعطيل (Soft Delete)"

        confirm = QMessageBox.question(self, "تأكيد الإجراء الإداري",
                                       f"هل أنت متأكد من {action_name} سجل الطبيب ({name})؟\n"
                                       "ملاحظة: التعطيل يمنع إسناد وصفات جديدة للطبيب، ولكنه يحافظ على فواتير المبيعات المرتبطة به تاريخياً.",
                                       QMessageBox.Yes | QMessageBox.No)

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.toggle_doctor_status(self.requester_id, doctor_id, make_active)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم", msg)
            else:
                QMessageBox.critical(self, "رفض العملية (حماية أمنية)", msg)