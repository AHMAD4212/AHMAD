import sys
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QMessageBox, QFrame, QGraphicsDropShadowEffect)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QCursor
from database.db_manager import DatabaseManager
import hashlib


class LoginWindow(QWidget):
    def __init__(self, switch_to_main_callback):
        super().__init__()
        self.switch_to_main = switch_to_main_callback
        self.db = DatabaseManager()

        # لقد أزلنا FramelessWindowHint لتعود نافذة نظام عادية قابلة للتكبير
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("تسجيل الدخول - Pharma Pro")
        self.resize(1000, 700)  # حجم بداية أكبر

        # توسيط النافذة
        self.center_window()

        # خلفية النافذة الأساسية وتعيين الخط العام
        self.setStyleSheet("background-color: #F0F2F5; font-family: 'Times New Roman';")

        # --- الحاوية الرئيسية ---
        # نستخدم Layout عادي ليملأ النافذة مهما كبر حجمها
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)  # حواف خارجية

        # الحاوية البيضاء الداخلية (Card)
        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 20px;
            }
        """)

        # ظل خفيف
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(0, 5)
        self.container.setGraphicsEffect(shadow)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # === 1. الجزء الأيسر (البراند) ===
        left_frame = QFrame()
        left_frame.setStyleSheet("""
            QFrame {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #2980B9, stop:1 #2C3E50);
                border-top-left-radius: 20px;
                border-bottom-left-radius: 20px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
            }
        """)
        left_layout = QVBoxLayout(left_frame)

        logo_label = QLabel("💊")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("font-size: 100px; background: transparent;")

        brand_title = QLabel("Pharmacy Mangment")
        brand_title.setAlignment(Qt.AlignCenter)
        brand_title.setStyleSheet(
            "font-size: 36px; font-weight: bold; color: white; background: transparent; font-family: 'Times New Roman';")

        brand_desc = QLabel("نظام إدارة الصيدليات الذكي\nالإصدار 1.0")
        brand_desc.setAlignment(Qt.AlignCenter)
        brand_desc.setStyleSheet(
            "font-size: 18px; color: #ECF0F1; background: transparent; font-family: 'Times New Roman';")

        left_layout.addStretch()
        left_layout.addWidget(logo_label)
        left_layout.addWidget(brand_title)
        left_layout.addWidget(brand_desc)
        left_layout.addStretch()

        container_layout.addWidget(left_frame, stretch=4)

        # === 2. الجزء الأيمن (نموذج الدخول) ===
        right_frame = QFrame()
        # نلغي الزوايا الدائرية من جهة اليسار للاتصال مع الجزء الأزرق
        right_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-top-right-radius: 20px;
                border-bottom-right-radius: 20px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
            }
        """)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(50, 50, 50, 50)
        right_layout.setSpacing(25)

        right_layout.addStretch()

        welcome_label = QLabel("تسجيل الدخول")
        welcome_label.setStyleSheet(
            "font-size: 32px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        welcome_sub = QLabel("يرجى إدخال بيانات حسابك للمتابعة")
        welcome_sub.setStyleSheet(
            "font-size: 16px; color: #95A5A6; margin-bottom: 20px; font-family: 'Times New Roman';")

        right_layout.addWidget(welcome_label)
        right_layout.addWidget(welcome_sub)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("اسم المستخدم")
        self.apply_input_style(self.user_input)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("كلمة المرور")
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.apply_input_style(self.pass_input)

        right_layout.addWidget(self.user_input)
        right_layout.addWidget(self.pass_input)

        self.login_btn = QPushButton("دخول للنظام")
        self.login_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.login_btn.clicked.connect(self.handle_login)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                font-size: 18px;
                font-weight: bold;
                padding: 15px;
                border-radius: 10px;
                font-family: 'Times New Roman';
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
            QPushButton:pressed {
                background-color: #1F618D;
            }
        """)
        right_layout.addWidget(self.login_btn)

        right_layout.addStretch()

        footer = QLabel("Pharma System © 2025")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #BDC3C7; font-size: 14px; font-family: 'Times New Roman';")
        right_layout.addWidget(footer)

        container_layout.addWidget(right_frame, stretch=6)

        main_layout.addWidget(self.container)

    def apply_input_style(self, widget):
        widget.setFixedHeight(55)  # زيادة ارتفاع الخانة
        widget.setStyleSheet("""
            QLineEdit {
                background-color: #F4F6F7;
                border: 2px solid #F4F6F7;
                border-radius: 10px;
                padding: 0 15px;
                font-size: 16px;
                color: #2C3E50;
                font-family: 'Times New Roman';
            }
            QLineEdit:focus {
                border: 2px solid #3498DB;
                background-color: white;
            }
        """)

    def center_window(self):
        frame_gm = self.frameGeometry()
        screen = self.window().screen()
        center_point = screen.availableGeometry().center()
        frame_gm.moveCenter(center_point)
        self.move(frame_gm.topLeft())

    # ملاحظة: تم حذف دوال mouseMoveEvent لأن النافذة أصبحت عادية ولها شريط عنوان خاص بها

    def handle_login(self):
        username = self.user_input.text()
        password = self.pass_input.text()

        if not username or not password:
            QMessageBox.warning(self, "تنبيه", "الرجاء إدخال اسم المستخدم وكلمة المرور")
            return

        hashed_input = hashlib.sha256(password.encode()).hexdigest()

        conn = self.db.connect()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_input))
            user = cursor.fetchone()
            conn.close()

            if user:
                user_role = user[3]
                print(f"Login Successful as {user_role}")
                self.switch_to_main(user_role)
            else:
                QMessageBox.critical(self, "خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة")