from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QGridLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from models.dashboard_dao import DashboardDAO


class HomePage(QWidget):
    def __init__(self):
        super().__init__()
        self.dao = DashboardDAO()
        self.init_ui()
        self.load_stats()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(25)  # زيادة المسافة بين العناصر

        # 1. عنوان ترحيبي (خط كبير Times New Roman)
        welcome_label = QLabel("(Dashboard)")
        welcome_label.setStyleSheet(
            "font-size: 32px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        layout.addWidget(welcome_label)

        # 2. شبكة البطاقات (Cards Grid)
        cards_layout = QGridLayout()
        cards_layout.setSpacing(25)  # مسافات أوسع بين البطاقات

        # --- الصف الأول: المؤشرات العامة ---
        # بطاقة 1: إجمالي الأدوية
        self.card_meds = self.create_card("📦 إجمالي الأدوية", "0", "#3498DB")  # أزرق
        cards_layout.addWidget(self.card_meds, 0, 0)

        # بطاقة 2: مبيعات اليوم
        self.card_sales = self.create_card("💰 مبيعات اليوم", "0.00", "#27AE60")  # أخضر
        cards_layout.addWidget(self.card_sales, 0, 1)

        # --- الصف الثاني: التنبيهات (الأهم) ---
        # بطاقة 3: نواقص المخزون (تحذير)
        self.card_alerts = self.create_card("⚠️ نواقص المخزون", "0", "#E74C3C")  # أحمر
        cards_layout.addWidget(self.card_alerts, 1, 0)

        # بطاقة 4: صلاحية وشيكة (الميزة الجديدة - برتقالي)
        self.card_expiry = self.create_card("⏳ صلاحية وشيكة (3 شهور)", "0", "#F39C12")
        cards_layout.addWidget(self.card_expiry, 1, 1)

        # --- الصف الثالث: المعلومات الإدارية ---
        # بطاقة 5: طاقم العمل (الميزة القديمة - جعلناها تمتد على عمودين لتوازن الشكل)
        self.card_users = self.create_card("👥 طاقم العمل والمستخدمين", "0", "#8E44AD")  # بنفسجي
        cards_layout.addWidget(self.card_users, 2, 0, 1, 2)  # (Row 2, Col 0, RowSpan 1, ColSpan 2)

        layout.addLayout(cards_layout)

        # مسافة مرنة
        layout.addStretch()

        # زر تحديث (كبير وواضح)
        self.btn_refresh = QPushButton("🔄 تحديث الإحصائيات")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_stats)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #7F8C8D; 
                color: white; 
                padding: 15px 30px; 
                border-radius: 8px; 
                font-weight: bold;
                font-size: 18px;
                font-family: 'Times New Roman';
            }
            QPushButton:hover { background-color: #95A5A6; }
        """)
        layout.addWidget(self.btn_refresh, alignment=Qt.AlignLeft)

        self.setLayout(layout)

    def create_card(self, title, value, color):
        """دالة مساعدة لإنشاء تصميم البطاقة الموحد"""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border-radius: 15px;
                border-left: 12px solid {color}; /* سمك الخط الجانبي أكبر */
            }}
        """)
        card.setFixedHeight(170)  # زيادة ارتفاع البطاقة

        # تخطيط داخلي للبطاقة
        card_layout = QVBoxLayout(card)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #7F8C8D; font-size: 20px; font-weight: bold; font-family: 'Times New Roman';")

        lbl_value = QLabel(value)
        lbl_value.setObjectName("value_label")
        # تكبير خط الأرقام ليظهر بوضوح
        lbl_value.setStyleSheet(f"color: {color}; font-size: 48px; font-weight: bold; font-family: 'Times New Roman';")
        lbl_value.setAlignment(Qt.AlignCenter)

        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_value)

        return card

    def load_stats(self):
        """جلب البيانات وتحديث البطاقات"""
        stats = self.dao.get_statistics()

        # تحديث النصوص داخل البطاقات
        self.card_meds.findChild(QLabel, "value_label").setText(str(stats['total_medicines']))
        self.card_alerts.findChild(QLabel, "value_label").setText(str(stats['low_stock']))
        self.card_sales.findChild(QLabel, "value_label").setText(f"{stats['today_sales']:.2f}")

        # تحديث الميزات الجديدة والقديمة
        self.card_users.findChild(QLabel, "value_label").setText(str(stats['users_count']))
        self.card_expiry.findChild(QLabel, "value_label").setText(str(stats['expiring_soon']))