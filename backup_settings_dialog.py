"""
وظيفة الملف: واجهة إعدادات النسخ الاحتياطي التلقائي واليدوي.
الطبقة: Presentation Layer
- [تحديث تكاملي]: تم توجيه الواجهة لتستخدم BackupService بدلاً من BackupManager القديم.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QPushButton, QCheckBox, QSpinBox, QTimeEdit,
                             QDialogButtonBox, QMessageBox, QFileDialog, QHBoxLayout, QLabel)
from PyQt5.QtCore import QTime
import os

from services.backup_service import BackupService


class BackupSettingsDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id  # حفظ هوية الجلسة
        self.setWindowTitle("إعدادات النسخ الاحتياطي التلقائي")
        self.resize(500, 300)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }
            QLineEdit, QSpinBox, QTimeEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; font-size: 16px; }
            QLabel { font-weight: bold; color: #2C3E50; }
        """)

        self.backup_service = BackupService()

        self.setup_ui()
        self.load_current_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel(
            "🛡️ النسخ الاحتياطي التلقائي يحمي بيانات الصيدلية من الضياع.\nتأكد من اختيار مسار آمن (يفضل قرص خارجي أو فلاش ميموري).")
        info_label.setStyleSheet("color: #27AE60; margin-bottom: 15px;")
        layout.addWidget(info_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.enable_checkbox = QCheckBox("تفعيل النسخ الاحتياطي التلقائي يومياً")
        self.enable_checkbox.setStyleSheet("font-weight: bold; color: #E67E22;")

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.btn_browse = QPushButton(" 📁 استعراض")
        self.btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.btn_browse)

        self.time_input = QTimeEdit()
        self.time_input.setDisplayFormat("HH:mm")

        self.retention_input = QSpinBox()
        self.retention_input.setRange(1, 365)
        self.retention_input.setSuffix(" أيام")

        form_layout.addRow(self.enable_checkbox)
        form_layout.addRow("مسار الحفظ:", path_layout)
        form_layout.addRow("وقت التنفيذ (يومياً):", self.time_input)
        form_layout.addRow("الاحتفاظ بآخر:", self.retention_input)

        layout.addLayout(form_layout)

        self.btn_manual_backup = QPushButton(" 💾 أخذ نسخة احتياطية الآن (يدوي)")
        self.btn_manual_backup.setStyleSheet(
            "background-color: #3498DB; color: white; font-weight: bold; padding: 10px; border-radius: 5px; margin-top: 10px;")
        self.btn_manual_backup.clicked.connect(self.run_manual_backup)
        layout.addWidget(self.btn_manual_backup)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ الإعدادات")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet("background-color: #2C3E50; color: white;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.save_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد النسخ الاحتياطي")
        if folder:
            self.path_input.setText(os.path.normpath(folder))

    def load_current_settings(self):
        settings = self.backup_service.load_settings()
        self.enable_checkbox.setChecked(settings.get("auto_backup_enabled", False))
        self.path_input.setText(settings.get("backup_path", ""))

        time_str = settings.get("backup_time", "23:00")
        hour, minute = map(int, time_str.split(":"))
        self.time_input.setTime(QTime(hour, minute))

        self.retention_input.setValue(settings.get("retention_days", 7))

    def save_settings(self):
        path = self.path_input.text().strip()
        if self.enable_checkbox.isChecked() and not path:
            QMessageBox.warning(self, "تنبيه", "يجب تحديد مسار حفظ النسخة الاحتياطية لتفعيل الميزة.")
            return

        settings = {
            "auto_backup_enabled": self.enable_checkbox.isChecked(),
            "backup_path": path,
            "backup_time": self.time_input.time().toString("HH:mm"),
            "retention_days": self.retention_input.value()
        }
        self.backup_service.save_settings(settings)
        QMessageBox.information(self, "نجاح",
                                "تم حفظ إعدادات النسخ الاحتياطي.\n(إذا تم تعديل وقت النسخ، سيبدأ سريان التعديل فوراً).")
        self.accept()

    def run_manual_backup(self):
        self.btn_manual_backup.setEnabled(False)
        self.btn_manual_backup.setText("⏳ جاري النسخ...")

        # التنفيذ كمدير نظام (نظراً لأن الشاشة لا تظهر إلا للمدير)
        success, msg = self.backup_service.create_backup(user_id=self.user_id, is_auto=False)

        self.btn_manual_backup.setEnabled(True)
        self.btn_manual_backup.setText(" 💾 أخذ نسخة احتياطية الآن (يدوي)")

        if success:
            QMessageBox.information(self, "نجاح", msg)
        else:
            QMessageBox.critical(self, "فشل", msg)