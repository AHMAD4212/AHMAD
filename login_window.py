"""
وظيفة الملف: واجهة تسجيل الدخول (View).
الطبقة: Presentation Layer

ملاحظات تصميمية:
- [واجهة محسنة]&#58; تحسين بصري كامل لواجهة الدخول لتناسب تطبيق احترافي.
- [إظهار/إخفاء كلمة المرور]&#58; تمت إضافة زر بصري لحقل كلمة المرور في شاشة الدخول
  وكذلك في نافذة تغيير كلمة المرور الإجباري.
- [تكامل أمني]&#58; تعتمد الواجهة على AuthService للمصادقة وPasswordUtils لفحص قوة كلمة المرور.
- [انتقال آمن]&#58; بعد نجاح الدخول يتم إخفاء النافذة ثم الانتقال للواجهة الرئيسية دون حذف قسري.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QGraphicsDropShadowEffect,
    QDialog, QApplication, QToolButton
)
from PyQt5.QtCore import Qt, QTimer, QByteArray, QSize
from PyQt5.QtGui import QColor, QCursor, QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer

from services.auth_service import AuthService
from core.security.password_utils import PasswordUtils


OPEN_EYE_SVG = """
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M2 12C3.9 8.6 7.4 6.2 12 6.2C16.6 6.2 20.1 8.6 22 12C20.1 15.4 16.6 17.8 12 17.8C7.4 17.8 3.9 15.4 2 12Z"
        stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="12" cy="12" r="3.1" stroke="{color}" stroke-width="1.8"/>
</svg>
"""

CLOSED_EYE_SVG = """
<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M3 13C5.5 10.4 8.3 9.1 12 9.1C15.7 9.1 18.5 10.4 21 13"
        stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M6 15.2L5 17.2" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M9.4 14.3L9 17" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M14.6 14.3L15 17" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M18 15.2L19 17.2" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>
</svg>
"""

def _svg_to_icon(svg_markup: str, size: int = 24) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_markup.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)

def _set_eye_button_state(button, is_visible: bool, icon_size: int = 24):
    color = "#154360" if is_visible else "#2C3E50"
    svg = OPEN_EYE_SVG.format(color=color) if is_visible else CLOSED_EYE_SVG.format(color=color)
    button.setIcon(_svg_to_icon(svg, icon_size))
    button.setToolTip("إخفاء كلمة المرور" if is_visible else "إظهار كلمة المرور")

def build_password_row(line_edit: QLineEdit, button_size: int = 56, icon_size: int = 24) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    toggle_btn = QToolButton()
    toggle_btn.setCheckable(True)
    toggle_btn.setCursor(Qt.PointingHandCursor)
    toggle_btn.setFixedSize(button_size, button_size)
    toggle_btn.setIconSize(QSize(icon_size, icon_size))
    toggle_btn.setStyleSheet("""
        QToolButton {
            background-color: #F4F8FB;
            border: 1px solid #D6EAF8;
            border-radius: 14px;
            padding: 6px;
        }
        QToolButton:hover {
            background-color: #EAF4FB;
            border: 1px solid #AED6F1;
        }
        QToolButton:checked {
            background-color: #D6EAF8;
            border: 1px solid #5DADE2;
        }
        QToolButton:pressed {
            padding-top: 7px;
        }
    """)

    _set_eye_button_state(toggle_btn, False, icon_size)

    def on_toggled(checked):
        line_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        _set_eye_button_state(toggle_btn, checked, icon_size)

    toggle_btn.toggled.connect(on_toggled)

    layout.addWidget(line_edit)
    layout.addWidget(toggle_btn)
    return container


class ChangePasswordDialog(QDialog):
    """
    نافذة حوار لإجبار المستخدم على تغيير كلمة المرور الافتراضية
    بشكل أكثر وضوحاً واحترافية.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تأمين الحساب - تغيير كلمة المرور")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumSize(500, 340)

        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(560, screen.width() - 120), min(380, screen.height() - 120))

        self.setStyleSheet("background-color: white; font-family: 'Times New Roman';")

        self.new_password = ""
        self.init_ui()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("يجب تغيير كلمة المرور الافتراضية")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #C0392B;
        """)

        subtitle = QLabel(
            "لأسباب أمنية، لا يمكن دخول النظام قبل تعيين كلمة مرور جديدة قوية."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("""
            font-size: 13px;
            color: #566573;
        """)

        rules = QLabel(
            "• 8 أحرف على الأقل\n"
            "• تحتوي على رقم واحد على الأقل\n"
            "• تحتوي على حرف إنجليزي كبير (A-Z)\n"
            "• تحتوي على حرف إنجليزي صغير (a-z)\n"
            "• لا يمكن استخدام كلمة المرور الحالية مرة أخرى"
        )
        rules.setStyleSheet("""
            font-size: 13px;
            color: #2C3E50;
            background-color: #F8F9F9;
            border: 1px solid #E5E7E9;
            border-radius: 10px;
            padding: 12px;
        """)

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(rules)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("كلمة المرور الجديدة")
        self._apply_input_style(self.pass_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("تأكيد كلمة المرور")
        self._apply_input_style(self.confirm_input)

        pass_row = build_password_row(self.pass_input, button_size=52, icon_size=22)
        confirm_row = build_password_row(self.confirm_input, button_size=52, icon_size=22)

        root.addWidget(pass_row)
        root.addWidget(confirm_row)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("font-size: 12px; color: #7F8C8D;")
        root.addWidget(self.info_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_cancel = QPushButton("إلغاء")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #ECF0F1;
                color: #2C3E50;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 12px 18px;
            }
            QPushButton:hover {
                background-color: #D5DBDB;
            }
        """)

        self.btn_save = QPushButton("حفظ ومتابعة")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.validate_and_accept)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 12px 18px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)

        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save)

        root.addLayout(btn_row)

        self.pass_input.returnPressed.connect(self.confirm_input.setFocus)
        self.confirm_input.returnPressed.connect(self.validate_and_accept)
        self.pass_input.setFocus()

    def _apply_input_style(self, widget):
        widget.setEchoMode(QLineEdit.Password)
        widget.setMinimumHeight(50)
        widget.setStyleSheet("""
            QLineEdit {
                background-color: #F8F9F9;
                border: 2px solid #E5E7E9;
                border-radius: 12px;
                padding: 0 14px;
                font-size: 15px;
                color: #2C3E50;
            }
            QLineEdit:focus {
                background-color: white;
                border: 2px solid #3498DB;
            }
        """)


    def validate_and_accept(self):
        pwd = self.pass_input.text().strip()
        confirm = self.confirm_input.text().strip()

        is_strong, msg = PasswordUtils.validate_password_strength(pwd)
        if not is_strong:
            QMessageBox.warning(self, "كلمة مرور ضعيفة", msg)
            return

        if pwd != confirm:
            QMessageBox.warning(self, "خطأ", "كلمتا المرور غير متطابقتين.")
            return

        self.new_password = pwd
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_parent()

    def _center_on_parent(self):
        if self.parent() and self.parent().isVisible():
            parent_geo = self.parent().frameGeometry()
            dialog_geo = self.frameGeometry()
            dialog_geo.moveCenter(parent_geo.center())
            self.move(dialog_geo.topLeft())
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            dialog_geo = self.frameGeometry()
            dialog_geo.moveCenter(screen.center())
            self.move(dialog_geo.topLeft())



class LoginWindow(QWidget):
    """
    نافذة تسجيل الدخول الرئيسية.
    """
    def __init__(self, switch_to_main_callback):
        super().__init__()
        self.switch_to_main = switch_to_main_callback
        self.auth_service = AuthService()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("تسجيل الدخول - Pharma Pro")
        self.resize(1120, 720)
        self.center_window()
        self.setStyleSheet("""
            QWidget {
                font-family: 'Times New Roman';
            }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)

        # =====================================================
        # الحاوية العامة
        # =====================================================
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 24px;
            }
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 45))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # =====================================================
        # الجهة اليسرى - الهوية البصرية
        # =====================================================
        left_frame = QFrame()
        left_frame.setStyleSheet("""
            QFrame {
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1F618D,
                    stop:1 #273746
                );
                border-top-left-radius: 24px;
                border-bottom-left-radius: 24px;
            }
        """)

        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(18)

        brand_badge = QLabel("PHARMA SYS PRO")
        brand_badge.setAlignment(Qt.AlignCenter)
        brand_badge.setStyleSheet("""
            color: #D6EAF8;
            font-size: 16px;
            font-weight: bold;
            letter-spacing: 2px;
        """)

        logo_label = QLabel("⚕⚕")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("""
            color: white;
            font-size: 120px;
            background: transparent;
        """)

        brand_title = QLabel("Pharmacy Management System")
        brand_title.setAlignment(Qt.AlignCenter)
        brand_title.setWordWrap(True)
        brand_title.setStyleSheet("""
            color: white;
            font-size: 34px;
            font-weight: bold;
            background: transparent;
        """)

        brand_subtitle = QLabel(
            "منظومة تشغيل متكاملة لإدارة الصيدلية\n"
            "توحِّد المخزون والمبيعات والوصفات والرقابة اليومية\n"
            "ضمن بيئة دقيقة وآمنة ومهيأة للتوسع المؤسسي"
        )
        brand_subtitle.setAlignment(Qt.AlignCenter)
        brand_subtitle.setWordWrap(True)
        brand_subtitle.setStyleSheet("""
            color: #D4E6F1;
            font-size: 17px;
            background: transparent;
            line-height: 1.9;
            letter-spacing: 0.3px;
        """)

        left_layout.addStretch()
        left_layout.addWidget(brand_badge)
        left_layout.addWidget(logo_label)
        left_layout.addWidget(brand_title)
        left_layout.addWidget(brand_subtitle)
        left_layout.addStretch()

        container_layout.addWidget(left_frame, stretch=5)

        # =====================================================
        # الجهة اليمنى - نموذج الدخول
        # =====================================================
        right_frame = QFrame()
        right_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-top-right-radius: 24px;
                border-bottom-right-radius: 24px;
            }
        """)

        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(60, 55, 60, 55)
        right_layout.setSpacing(16)

        right_layout.addStretch()

        form_container = QFrame()
        form_container.setMaximumWidth(560)
        form_container.setMinimumWidth(460)
        form_container.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
        """)

        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(18)

        title = QLabel("تسجيل الدخول")
        title.setAlignment(Qt.AlignRight)
        title.setStyleSheet("""
            font-size: 40px;
            font-weight: bold;
            color: #1F2D3D;
        """)

        subtitle = QLabel("أدخل بيانات الاعتماد الخاصة بك للمتابعة إلى النظام")
        subtitle.setAlignment(Qt.AlignRight)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("""
            font-size: 18px;
            color: #7B8A8B;
        """)

        username_label = QLabel("اسم المستخدم")
        username_label.setAlignment(Qt.AlignRight)
        username_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #2C3E50;
        """)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("أدخل اسم المستخدم")
        self.apply_input_style(self.user_input)

        password_label = QLabel("كلمة المرور")
        password_label.setAlignment(Qt.AlignRight)
        password_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #2C3E50;
        """)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("أدخل كلمة المرور")
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.apply_input_style(self.pass_input)

        password_row = build_password_row(self.pass_input, button_size=56, icon_size=24)

        self.hint_label = QLabel("يمكنك الضغط على Enter بعد إدخال كلمة المرور.")
        self.hint_label.setAlignment(Qt.AlignRight)
        self.hint_label.setStyleSheet("""
            font-size: 14px;
            color: #909497;
        """)

        self.security_note = QLabel(
            "ملاحظة أمنية: يتم تسجيل محاولات الدخول الفاشلة وتطبيق قفل مؤقت عند التكرار."
        )
        self.security_note.setAlignment(Qt.AlignRight)
        self.security_note.setWordWrap(True)
        self.security_note.setStyleSheet("""
            font-size: 14px;
            color: #5D6D7E;
            background-color: #F8F9F9;
            border: 1px solid #EAFAF1;
            border-radius: 10px;
            padding: 12px;
        """)

        self.login_btn = QPushButton("تسجيل الدخول")
        self.login_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.login_btn.clicked.connect(self.handle_login)
        self.login_btn.setMinimumHeight(60)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #2E86C1;
                color: white;
                font-size: 20px;
                font-weight: bold;
                border: none;
                border-radius: 14px;
                padding: 14px;
            }
            QPushButton:hover {
                background-color: #2874A6;
            }
        """)

        form_layout.addWidget(title)
        form_layout.addWidget(subtitle)
        form_layout.addSpacing(8)
        form_layout.addWidget(username_label)
        form_layout.addWidget(self.user_input)
        form_layout.addWidget(password_label)
        form_layout.addWidget(password_row)
        form_layout.addWidget(self.hint_label)
        form_layout.addWidget(self.security_note)
        form_layout.addSpacing(6)
        form_layout.addWidget(self.login_btn)

        right_layout.addWidget(form_container, alignment=Qt.AlignCenter)
        right_layout.addStretch()

        container_layout.addWidget(right_frame, stretch=6)
        root.addWidget(self.container)

        self.user_input.returnPressed.connect(self.pass_input.setFocus)
        self.pass_input.returnPressed.connect(self.handle_login)
        self.user_input.setFocus()

    def apply_input_style(self, widget):
        widget.setMinimumHeight(60)
        widget.setStyleSheet("""
            QLineEdit {
                background-color: #F8F9F9;
                border: 2px solid #E5E7E9;
                border-radius: 14px;
                padding: 0 18px;
                font-size: 18px;
                color: #1F2D3D;
            }
            QLineEdit:focus {
                background-color: white;
                border: 2px solid #3498DB;
            }
        """)

    def center_window(self):
        """
        توسيط آمن للنافذة على الشاشة الأساسية.
        """
        screen = QApplication.primaryScreen().availableGeometry()
        size = self.frameGeometry()
        size.moveCenter(screen.center())
        self.move(size.topLeft())

    def _proceed_to_main(self, session_data):
        """
        انتقال آمن إلى الواجهة الرئيسية دون تدمير قسري لنافذة الدخول.
        """
        self.hide()
        QTimer.singleShot(0, lambda: self.switch_to_main(session_data))

    def handle_login(self):
        username = self.user_input.text().strip()
        password = self.pass_input.text()

        if not username or not password:
            QMessageBox.warning(self, "تنبيه", "الرجاء إدخال اسم المستخدم وكلمة المرور.")
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("جاري التحقق...")

        success, result = self.auth_service.authenticate(username, password)

        self.login_btn.setEnabled(True)
        self.login_btn.setText("تسجيل الدخول")

        if success:
            session_data = result

            if session_data.get("must_change_password"):
                dialog = ChangePasswordDialog(self)
                if dialog.exec_() == QDialog.Accepted:
                    new_pwd = dialog.new_password

                    upd_success, upd_msg = self.auth_service.force_change_password(
                        session_data["user_id"], new_pwd
                    )

                    if upd_success:
                        QMessageBox.information(self, "نجاح", upd_msg)
                        session_data["must_change_password"] = False
                        self._proceed_to_main(session_data)
                    else:
                        QMessageBox.critical(self, "خطأ", upd_msg)
                else:
                    QMessageBox.warning(
                        self,
                        "تنبيه أمني",
                        "لا يمكن الدخول إلى النظام دون تغيير كلمة المرور الافتراضية."
                    )
            else:
                self._proceed_to_main(session_data)

        else:
            QMessageBox.critical(self, "فشل تسجيل الدخول", result)
            self.pass_input.clear()
            self.pass_input.setFocus()