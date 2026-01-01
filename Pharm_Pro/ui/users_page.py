from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView, QLabel,
                             QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from models.users_dao import UsersDAO


# --- نافذة إضافة مستخدم جديد ---
class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة مستخدم جديد")
        self.setFixedSize(400, 300)  # تكبير الحجم قليلاً
        # تنسيق النافذة
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 14px; background-color: #F5F6FA; }
            QLineEdit, QComboBox { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; height: 35px; }
            QLabel { font-weight: bold; font-size: 16px; }
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
        self.role_input.addItems(["pharmacist", "admin"])
        # pharmacist = صيدلي (صلاحيات محدودة)
        # admin = مدير (كامل الصلاحيات)

        form_layout.addRow("اسم المستخدم:", self.user_input)
        form_layout.addRow("كلمة المرور:", self.pass_input)
        form_layout.addRow("الصلاحية (Role):", self.role_input)

        layout.addLayout(form_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        # تنسيق الأزرار
        for btn in self.buttons.buttons():
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("font-family: 'Times New Roman'; font-size: 14px; font-weight: bold; height: 35px;")

        self.buttons.accepted.connect(self.save_user)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_user(self):
        user = self.user_input.text()
        password = self.pass_input.text()
        role = self.role_input.currentText()

        if not user or not password:
            QMessageBox.warning(self, "تنبيه", "جميع الحقول مطلوبة")
            return

        success, msg = self.dao.add_user(user, password, role)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.warning(self, "خطأ", msg)


# --- الصفحة الرئيسية لإدارة المستخدمين ---
class UsersPage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = UsersDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # العنوان
        title = QLabel("إدارة المستخدمين والصلاحيات")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; margin-bottom: 10px; color: #2C3E50; font-family: 'Times New Roman';")
        layout.addWidget(title)

        # الأزرار العلوية
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("➕ إضافة مستخدم جديد")
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setFixedHeight(45)
        self.btn_add.setStyleSheet(
            "background-color: #2980B9; color: white; padding: 0 20px; font-weight: bold; font-family: 'Times New Roman'; font-size: 16px; border-radius: 5px;")

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setFixedHeight(45)
        self.btn_refresh.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")

        self.btn_delete = QPushButton("🗑️ حذف المستخدم المحدد")
        self.btn_delete.clicked.connect(self.delete_user)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setFixedHeight(45)
        self.btn_delete.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 0 20px; font-weight: bold; font-family: 'Times New Roman'; font-size: 16px; border-radius: 5px;")

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

        # الجدول
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "اسم المستخدم", "الصلاحية (Role)", "تاريخ الإنشاء"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        # تنسيق الجدول
        self.table.setStyleSheet(
            "QTableWidget { font-family: 'Times New Roman'; font-size: 16px; } QHeaderView::section { font-family: 'Times New Roman'; font-size: 16px; font-weight: bold; }")
        layout.addWidget(self.table)

        self.setLayout(layout)

    def load_data(self):
        users = self.dao.get_all_users()
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(users):
            self.table.insertRow(row_idx)
            # row_data = (id, username, role, created_at)
            for col_idx, col_data in enumerate(row_data):
                item = QTableWidgetItem(str(col_data))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        dialog = AddUserDialog(self)
        if dialog.exec_():
            self.load_data()

    def delete_user(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مستخدم لحذفه")
            return

        user_id = self.table.item(selected_row, 0).text()
        username = self.table.item(selected_row, 1).text()

        # حماية إضافية في الواجهة
        if username == 'admin':
            QMessageBox.critical(self, "خطأ", "لا يمكن حذف المدير الرئيسي!")
            return

        reply = QMessageBox.question(self, "تأكيد الحذف",
                                     f"هل أنت متأكد من حذف المستخدم {username}؟",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            success, msg = self.dao.delete_user(user_id)
            if success:
                QMessageBox.information(self, "تم", msg)
                self.load_data()
            else:
                QMessageBox.critical(self, "خطأ", msg)