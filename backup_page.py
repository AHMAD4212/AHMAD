"""
وظيفة الملف: واجهة إدارة النسخ الاحتياطي (Backup & Restore).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Admin Only]: هذه الصفحة محجوبة تماماً عن غير المدراء نظراً لخطورتها الكارثية.
- [Controlled Restore]: عملية الاستعادة تجبر التطبيق على الإغلاق (Quit) فور نجاحها
  لمنع حدوث تعارض في اتصالات SQLite المفتوحة في الذاكرة.
- واجهة خالية من التعقيدات التشغيلية (فقط إنشاء يدوي، استعادة، وعرض السجل).
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
                             QMessageBox, QFrame, QApplication, QAbstractItemView)
from PyQt5.QtCore import Qt
from services.backup_service import BackupService


class BackupPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

        self.backup_service = BackupService()

        # UI RBAC: حماية بصرية صارمة
        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.init_ui()
            self.load_data()

    def init_access_denied_ui(self):
        layout = QVBoxLayout()
        warning_lbl = QLabel("⛔ صلاحيات غير كافية.\nهذه الصفحة مخصصة لمدير النظام فقط (إدارة النسخ الاحتياطي).")
        warning_lbl.setAlignment(Qt.AlignCenter)
        warning_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';")
        layout.addWidget(warning_lbl)
        self.setLayout(layout)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # --- العنوان والتحذير العام ---
        header_frame = QFrame()
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("إدارة النسخ الاحتياطي واستعادة النظام (Disaster Recovery)")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")

        info = QLabel(
            "ملاحظة: يتم أخذ نسخة احتياطية تلقائياً كل يوم عند أول تسجيل دخول. يمكنك هنا أخذ نسخ يدوية إضافية أو استعادة النظام.")
        info.setStyleSheet("font-size: 14px; color: #7F8C8D; font-family: 'Times New Roman';")

        header_layout.addWidget(title)
        header_layout.addWidget(info)
        layout.addWidget(header_frame)

        # --- شريط الأزرار ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.btn_refresh = QPushButton(" 🔄 تحديث القائمة")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet(
            "font-size: 16px; padding: 0 20px; font-family: 'Times New Roman'; border-radius: 5px;")

        self.btn_create_manual = QPushButton(" 💾 إنشاء نسخة احتياطية (يدوي)")
        self.btn_create_manual.setFixedHeight(50)
        self.btn_create_manual.setCursor(Qt.PointingHandCursor)
        self.btn_create_manual.clicked.connect(self.create_manual_backup)
        self.btn_create_manual.setStyleSheet(
            "background-color: #2980B9; color: white; padding: 0 20px; font-size: 16px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';")

        self.btn_restore = QPushButton(" ⚠️ استعادة النظام من نسخة")
        self.btn_restore.setFixedHeight(50)
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.clicked.connect(self.restore_selected_backup)
        self.btn_restore.setStyleSheet(
            "background-color: #C0392B; color: white; padding: 0 20px; font-size: 16px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';")

        top_bar.addWidget(self.btn_refresh)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_create_manual)
        top_bar.addWidget(self.btn_restore)

        layout.addLayout(top_bar)

        # --- جدول النسخ المتوفرة ---
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["اسم ملف النسخة (Filename)", "تاريخ وتوقت الإنشاء", "حجم الملف"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)

        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 16px; font-family: 'Times New Roman'; } QHeaderView::section { font-size: 16px; font-weight: bold; font-family: 'Times New Roman'; }")

        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        backups = self.backup_service.get_backup_history()
        self.table.setRowCount(0)
        for row_idx, backup in enumerate(backups):
            self.table.insertRow(row_idx)

            # ['filename', 'date', 'size_mb']
            items = [backup['filename'], backup['date'], backup['size_mb']]

            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def create_manual_backup(self):
        if not self.user_id: return

        success, msg = self.backup_service.create_backup(user_id=self.user_id, is_auto=False)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.load_data()
        else:
            QMessageBox.critical(self, "فشل النسخ الاحتياطي", msg)

    def restore_selected_backup(self):
        if not self.user_id: return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد نسخة احتياطية من الجدول لاستعادتها.")
            return

        filename = self.table.item(selected_row, 0).text()

        # رسالة تحذير صارمة
        warning_msg = (
            f"تحذير كارثي ⚠️\n\n"
            f"أنت على وشك استعادة النظام من النسخة:\n[{filename}]\n\n"
            f"- سيتم طمس قاعدة البيانات الحالية بالكامل واستبدالها بهذه النسخة.\n"
            f"- سيقوم النظام بأخذ (Safety Net) للقاعدة الحالية قبل الطمس تحوطاً.\n"
            f"- سيتم إغلاق التطبيق إجبارياً فور نجاح الاستعادة.\n\n"
            f"هل أنت متأكد تماماً من رغبتك في الاستمرار؟"
        )

        confirm = QMessageBox.question(self, "تأكيد الاستعادة (Restore)", warning_msg, QMessageBox.Yes | QMessageBox.No)

        if confirm == QMessageBox.Yes:
            success, msg = self.backup_service.restore_backup(self.user_id, filename)

            if success:
                QMessageBox.information(self, "نجاح الاستعادة", f"{msg}\n\nسيتم إغلاق التطبيق الآن.")
                # إغلاق التطبيق إجبارياً لمنع التفاعل مع قاعدة بيانات مستبدلة
                QApplication.instance().quit()
            else:
                QMessageBox.critical(self, "فشل الاستعادة", msg)