"""
وظيفة الملف: واجهة إدارة المستخدمين والصلاحيات.
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- تم ترقية الواجهة لتتوافق تماماً مع النواة الأمنية الجديدة (users_dao.py).
- تمرر الجلسة (requester_id) لكل العمليات لفرض الـ Deep RBAC.
- استُبدل الحذف النهائي بتعطيل/تفعيل الحساب (Soft Delete).
- تحتوي الواجهة على أدوات: (إضافة، تعطيل/تفعيل، تغيير الصلاحية، تصفير كلمة المرور، وتغيير كلمة المرور الشخصية).
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView, QLabel,
                             QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
                             QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from models.users_dao import UsersDAO


# ==========================================
# النوافذ المنبثقة (Dialogs)
# ==========================================

class AddUserDialog(QDialog):
    def __init__(self, requester_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.setWindowTitle("إضافة مستخدم جديد")
        self.setFixedSize(400, 300)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 14px; background-color: #F5F6FA; }
            QLineEdit, QComboBox { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50;}
        """)

        self.dao = UsersDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(20)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("اسم المستخدم (للدخول)")

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("كلمة المرور")
        self.pass_input.setEchoMode(QLineEdit.Password)

        self.role_input = QComboBox()
        self.role_input.addItems(["admin", "pharmacist", "cashier"])

        form_layout.addRow("اسم المستخدم:", self.user_input)
        form_layout.addRow("كلمة المرور:", self.pass_input)
        form_layout.addRow("الصلاحية (Role):", self.role_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ واعتماد")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.save_user)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_user(self):
        user = self.user_input.text()
        password = self.pass_input.text()
        role = self.role_input.currentText()

        if not user.strip() or not password:
            QMessageBox.warning(self, "تنبيه", "جميع الحقول مطلوبة بشكل إلزامي.")
            return

        success, msg = self.dao.add_user(self.requester_id, user, password, role)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class ChangeRoleDialog(QDialog):
    def __init__(self, requester_id, target_user_id, current_role, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.target_user_id = target_user_id

        self.setWindowTitle("تغيير صلاحية مستخدم")
        self.setFixedSize(350, 200)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 14px; background-color: #F5F6FA; }
            QComboBox { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50;}
        """)

        self.dao = UsersDAO()
        self.setup_ui(current_role)

    def setup_ui(self, current_role):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.role_input = QComboBox()
        self.role_input.addItems(["admin", "pharmacist", "cashier"])
        self.role_input.setCurrentText(current_role)

        form_layout.addRow("الصلاحية الجديدة:", self.role_input)
        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("اعتماد التغيير")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #F39C12; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.save_role)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def save_role(self):
        new_role = self.role_input.currentText()
        success, msg = self.dao.change_user_role(self.requester_id, self.target_user_id, new_role)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class ResetPasswordDialog(QDialog):
    def __init__(self, requester_id, target_user_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.target_user_id = target_user_id

        self.setWindowTitle("إعادة تعيين كلمة المرور")
        self.setFixedSize(350, 200)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 14px; background-color: #F5F6FA; }
            QLineEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50;}
        """)

        self.dao = UsersDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("كلمة المرور الجديدة")
        self.pass_input.setEchoMode(QLineEdit.Password)

        form_layout.addRow("كلمة المرور:", self.pass_input)
        layout.addLayout(form_layout)

        info_lbl = QLabel("* سيتم إجبار المستخدم على تغييرها فور دخوله.")
        info_lbl.setStyleSheet("color: #E74C3C; font-size: 12px;")
        layout.addWidget(info_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("إعادة تعيين")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.reset_pass)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def reset_pass(self):
        new_pass = self.pass_input.text()
        if not new_pass:
            QMessageBox.warning(self, "تنبيه", "كلمة المرور مطلوبة.")
            return

        success, msg = self.dao.reset_user_password(self.requester_id, self.target_user_id, new_pass)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class ChangeOwnPasswordDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id

        self.setWindowTitle("تغيير كلمة المرور الشخصية")
        self.setFixedSize(400, 250)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 14px; background-color: #F5F6FA; }
            QLineEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; color: #2C3E50;}
        """)

        self.dao = UsersDAO()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.old_pass_input = QLineEdit()
        self.old_pass_input.setPlaceholderText("كلمة المرور الحالية")
        self.old_pass_input.setEchoMode(QLineEdit.Password)

        self.new_pass_input = QLineEdit()
        self.new_pass_input.setPlaceholderText("كلمة المرور الجديدة")
        self.new_pass_input.setEchoMode(QLineEdit.Password)

        form_layout.addRow("الكلمة الحالية:", self.old_pass_input)
        form_layout.addRow("الكلمة الجديدة:", self.new_pass_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("تغيير")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #34495E; color: white; font-weight: bold;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.change_pass)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

    def change_pass(self):
        old_pass = self.old_pass_input.text()
        new_pass = self.new_pass_input.text()

        if not old_pass or not new_pass:
            QMessageBox.warning(self, "تنبيه", "جميع الحقول مطلوبة.")
            return

        success, msg = self.dao.change_own_password(self.user_id, old_pass, new_pass)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


# ==========================================
# الصفحة الرئيسية لإدارة المستخدمين
# ==========================================

class UsersPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()
        # في حال تم استدعاء الصفحة بدون تمرير جلسة (للتوافق القديم مؤقتاً)، يتم تمرير قاموس فارغ
        self.session = session_data if session_data is not None else {}
        self.requester_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = UsersDAO()

        # حماية UI من غير المدراء
        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.init_ui()
            self.load_data()

    def init_access_denied_ui(self):
        layout = QVBoxLayout()
        warning_lbl = QLabel("⛔ صلاحيات غير كافية.\nهذه الصفحة مخصصة لمدير النظام فقط.")
        warning_lbl.setAlignment(Qt.AlignCenter)
        warning_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';")
        layout.addWidget(warning_lbl)

        # نسمح فقط بتغيير كلمة المرور الشخصية للمستخدم العادي
        btn_change_pass = QPushButton("تغيير كلمة المرور الشخصية")
        btn_change_pass.setFixedWidth(250)
        btn_change_pass.clicked.connect(self.open_change_own_password_dialog)
        btn_change_pass.setStyleSheet(
            "background-color: #34495E; color: white; padding: 10px; font-size: 16px; border-radius: 5px;")
        layout.addWidget(btn_change_pass, alignment=Qt.AlignCenter)

        self.setLayout(layout)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("إدارة المستخدمين والصلاحيات")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        layout.addWidget(title)

        # شريط الأزرار العلوية
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton(" إضافة مستخدم")
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setFixedHeight(45)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; font-weight: bold; font-family: 'Times New Roman'; font-size: 16px; border-radius: 5px;")

        self.btn_change_role = QPushButton(" تغيير الصلاحية")
        self.btn_change_role.clicked.connect(self.open_change_role_dialog)
        self.btn_change_role.setFixedHeight(45)
        self.btn_change_role.setStyleSheet(
            "background-color: #F39C12; color: white; padding: 0 20px; font-weight: bold; font-size: 16px; border-radius: 5px;")

        self.btn_reset_pass = QPushButton(" تصفير كلمة المرور")
        self.btn_reset_pass.clicked.connect(self.open_reset_password_dialog)
        self.btn_reset_pass.setFixedHeight(45)
        self.btn_reset_pass.setStyleSheet(
            "background-color: #34495E; color: white; padding: 0 20px; font-weight: bold; font-size: 16px; border-radius: 5px;")

        self.btn_toggle_status = QPushButton(" تعطيل / تفعيل الحساب")
        self.btn_toggle_status.clicked.connect(self.toggle_user_status)
        self.btn_toggle_status.setFixedHeight(45)
        self.btn_toggle_status.setStyleSheet(
            "background-color: #C0392B; color: white; padding: 0 20px; font-weight: bold; font-size: 16px; border-radius: 5px;")

        self.btn_refresh = QPushButton(" تحديث")
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setFixedHeight(45)
        self.btn_refresh.setStyleSheet("font-size: 16px;")

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_change_role)
        btn_layout.addWidget(self.btn_reset_pass)
        btn_layout.addWidget(self.btn_toggle_status)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_refresh)
        layout.addLayout(btn_layout)

        # زر تغيير كلمة المرور الشخصية (للمدير أيضاً)
        btn_change_own = QPushButton("تغيير كلمة المرور الشخصية (حسابي)")
        btn_change_own.clicked.connect(self.open_change_own_password_dialog)
        btn_change_own.setStyleSheet("color: #2980B9; border: none; font-size: 14px; text-decoration: underline;")
        layout.addWidget(btn_change_own, alignment=Qt.AlignLeft)

        # الجدول
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "اسم المستخدم", "الدور (Role)", "حالة الحساب", "تاريخ الإنشاء"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet(
            "QTableWidget { font-family: 'Times New Roman'; font-size: 16px; } QHeaderView::section { font-family: 'Times New Roman'; font-size: 16px; font-weight: bold; }")
        layout.addWidget(self.table)

        self.setLayout(layout)

    def load_data(self):
        users = self.dao.get_all_users(self.requester_id)
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(users):
            self.table.insertRow(row_idx)
            # row_data = (id, username, role, is_active, created_at)

            items = [str(row_data[0]), row_data[1], row_data[2], "نشط" if row_data[3] else "معطل", str(row_data[4])]

            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)

                # تلوين حالة الحساب
                if col_idx == 3:
                    if row_data[3] == 0:
                        item.setForeground(QColor("#C0392B"))  # أحمر للمعطل
                    else:
                        item.setForeground(QColor("#27AE60"))  # أخضر للنشط

                self.table.setItem(row_idx, col_idx, item)

    def get_selected_user(self):
        """دالة مساعدة لجلب بيانات المستخدم المحدد من الجدول"""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مستخدم من الجدول أولاً.")
            return None, None, None, None

        user_id = int(self.table.item(selected_row, 0).text())
        username = self.table.item(selected_row, 1).text()
        role = self.table.item(selected_row, 2).text()
        status = self.table.item(selected_row, 3).text()
        return user_id, username, role, status

    def open_add_dialog(self):
        dialog = AddUserDialog(self.requester_id, self)
        if dialog.exec_():
            self.load_data()

    def open_change_role_dialog(self):
        user_id, username, role, _ = self.get_selected_user()
        if not user_id: return

        dialog = ChangeRoleDialog(self.requester_id, user_id, role, self)
        if dialog.exec_():
            self.load_data()

    def open_reset_password_dialog(self):
        user_id, username, _, _ = self.get_selected_user()
        if not user_id: return

        reply = QMessageBox.question(self, "تأكيد", f"هل أنت متأكد من تصفير كلمة مرور ({username})؟",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            dialog = ResetPasswordDialog(self.requester_id, user_id, self)
            if dialog.exec_():
                self.load_data()

    def open_change_own_password_dialog(self):
        # الدالة متاحة للجميع وتستخدم self.requester_id كونه معرف الجلسة الحالي
        if not self.requester_id: return
        dialog = ChangeOwnPasswordDialog(self.requester_id, self)
        dialog.exec_()

    def toggle_user_status(self):
        user_id, username, _, status_text = self.get_selected_user()
        if not user_id: return

        make_active = (status_text == "معطل")
        action_name = "تفعيل" if make_active else "تعطيل"

        reply = QMessageBox.question(self, "تأكيد", f"هل أنت متأكد من {action_name} حساب ({username})؟",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            success, msg = self.dao.toggle_user_status(self.requester_id, user_id, make_active)
            if success:
                QMessageBox.information(self, "تم", msg)
                self.load_data()
            else:
                # الرسالة هنا ستكون قادمة من النواة (مثل محاولة تعطيل النفس أو المدير الأخير)
                QMessageBox.critical(self, "رفض العملية (حماية أمنية)", msg)