import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QStackedWidget, QFrame, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon

# --- استدعاء جميع الصفحات ---
from ui.login_window import LoginWindow
from database.db_manager import DatabaseManager
from ui.inventory_page import InventoryPage
from ui.pos_page import POSPage
from ui.reports_page import ReportsPage
from ui.users_page import UsersPage
from ui.home_page import HomePage
from ui.suppliers_page import SuppliersPage
from ui.customers_page import CustomersPage
from ui.purchases_page import PurchasesPage

# --- النافذة الرئيسية ---
class MainWindow(QMainWindow):
    def __init__(self, user_role):
        super().__init__()
        self.user_role = user_role  # تخزين دور المستخدم (admin أو pharmacist)
        self.setWindowTitle("نظام إدارة صيدلية")
        self.setGeometry(100, 100, 1280, 720)

        # التنسيق العام (CSS)
        self.setStyleSheet("""
            QMainWindow { background-color: #F5F6FA; }
        """)

        self.init_ui()

    def init_ui(self):
        # الحاوية الرئيسية
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # تقسيم الشاشة: قائمة جانبية (يسار) + محتوى (يمين)
        self.main_layout = QHBoxLayout(main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. بناء القائمة الجانبية
        self.create_sidebar()

        # 2. بناء منطقة المحتوى
        self.create_content_area()

    def create_sidebar(self):
        # إطار القائمة الجانبية
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(280)
        self.sidebar_frame.setStyleSheet("""
            QFrame {
                background-color: #2C3E50;
                color: white;
            }
            QPushButton {
                background-color: transparent;
                color: white;
                text-align: left;
                padding: 20px 25px;       
                font-size: 18px;          
                font-family: 'Times New Roman'; 
                border: none;
                border-left: 6px solid transparent;
            }
            QPushButton:hover {
                background-color: #34495E;
            }
            QPushButton:checked {
                background-color: #34495E;
                border-left: 6px solid #3498DB; 
            }
        """)

        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)

        # عنوان أو لوجو في الأعلى
        title_label = QLabel("Pharmacy Management")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 26px; font-weight: bold; padding: 40px 0; color: #ECF0F1; font-family: 'Times New Roman';")
        sidebar_layout.addWidget(title_label)

        # --- تعريف الأزرار ---
        self.btn_home = QPushButton("🏠  الرئيسية")
        self.btn_inventory = QPushButton("💊  المخزون والأدوية")
        self.btn_suppliers = QPushButton("🚛  الموردين والشركات")
        self.btn_purchases = QPushButton("📥  فواتير الشراء")
        self.btn_customers = QPushButton("👥  العملاء والمرضى")
        self.btn_pos = QPushButton("🛒  نقطة البيع")
        self.btn_reports = QPushButton("📊  التقارير المالية")
        self.btn_users = QPushButton("🔐  إدارة المستخدمين")
        self.btn_logout = QPushButton("🚪  تسجيل الخروج")

        # إضافة الأزرار للقائمة
        buttons = [
            self.btn_home,
            self.btn_inventory,
            self.btn_suppliers,
            self.btn_purchases,
            self.btn_customers,
            self.btn_pos,
            self.btn_reports,
            self.btn_users
        ]

        for btn in buttons:
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            sidebar_layout.addWidget(btn)

        # --- تطبيق الصلاحيات (إخفاء الأزرار لغير المدير) ---
        if self.user_role != 'admin':
            # إخفاء الأزرار الحساسة للصيدلي العادي
            self.btn_suppliers.hide()   # الموردين
            self.btn_purchases.hide()   # المشتريات
            self.btn_reports.hide()     # التقارير المالية
            self.btn_users.hide()       # إدارة المستخدمين

        # إضافة مسافة مرنة لدفع زر الخروج للأسفل
        sidebar_layout.addStretch()

        # زر الخروج
        self.btn_logout.setStyleSheet(
            "QPushButton { color: #E74C3C; font-weight: bold; font-family: 'Times New Roman'; font-size: 18px; padding: 20px 25px; } QPushButton:hover { background-color: #FDEDEC; }")
        sidebar_layout.addWidget(self.btn_logout)

        # --- ربط الأزرار بالصفحات ---
        self.btn_home.clicked.connect(lambda: self.switch_page(0, self.btn_home))
        self.btn_inventory.clicked.connect(lambda: self.switch_page(1, self.btn_inventory))
        self.btn_suppliers.clicked.connect(lambda: self.switch_page(2, self.btn_suppliers))
        self.btn_purchases.clicked.connect(lambda: self.switch_page(3, self.btn_purchases))
        self.btn_customers.clicked.connect(lambda: self.switch_page(4, self.btn_customers))
        self.btn_pos.clicked.connect(lambda: self.switch_page(5, self.btn_pos))
        self.btn_reports.clicked.connect(lambda: self.switch_page(6, self.btn_reports))
        self.btn_users.clicked.connect(lambda: self.switch_page(7, self.btn_users))

        # ربط زر الخروج
        self.btn_logout.clicked.connect(self.confirm_logout)

        self.main_layout.addWidget(self.sidebar_frame)
        self.nav_buttons = buttons

    def create_content_area(self):
        # منطقة المحتوى
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 1. الرأس (Header)
        header = QFrame()
        header.setFixedHeight(70)
        header.setStyleSheet("background-color: white; border-bottom: 1px solid #E0E0E0;")
        header_layout = QHBoxLayout(header)

        # اسم الصفحة الحالية
        self.page_title = QLabel("الرئيسية")
        self.page_title.setStyleSheet("font-size: 22px; color: #7F8C8D; font-weight: bold; margin-left: 20px;")

        # معلومات المستخدم
        user_info = QLabel(f"👤 المستخدم الحالي: {self.user_role}")
        user_info.setStyleSheet("color: #34495E; font-weight: bold; margin-right: 20px; font-size: 16px;")

        header_layout.addWidget(self.page_title)
        header_layout.addStretch()
        header_layout.addWidget(user_info)

        content_layout.addWidget(header)

        # 2. الصفحات (Stacked Widget)
        self.pages = QStackedWidget()

        # ملاحظة: نقوم بتمرير self.user_role لبعض الصفحات التي تحتاج لضبط صلاحيات داخلية لاحقاً
        self.pages.addWidget(HomePage())       # 0
        self.pages.addWidget(InventoryPage(self.user_role))  # 1
        self.pages.addWidget(SuppliersPage())  # 2
        self.pages.addWidget(PurchasesPage())  # 3
        self.pages.addWidget(CustomersPage())  # 4
        self.pages.addWidget(POSPage())        # 5
        self.pages.addWidget(ReportsPage())    # 6
        self.pages.addWidget(UsersPage())      # 7

        content_layout.addWidget(self.pages)
        self.main_layout.addWidget(content_widget)
        self.btn_home.click()

    def switch_page(self, index, button):
        """دالة للتبديل بين الصفحات"""
        self.pages.setCurrentIndex(index)
        self.page_title.setText(button.text().strip())
        for btn in self.nav_buttons:
            btn.setChecked(False)
        button.setChecked(True)

    def confirm_logout(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("تسجيل الخروج")
        msg.setText("هل أنت متأكد أنك تريد تسجيل الخروج؟")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setStyleSheet(
            "QLabel { font-family: 'Times New Roman'; font-size: 14px; } QPushButton { font-family: 'Times New Roman'; font-size: 12px; }")

        reply = msg.exec_()

        if reply == QMessageBox.Yes:
            self.close()


# --- الكلاس المتحكم (Controller) ---
class AppController:
    def __init__(self):
        self.login_window = None
        self.main_window = None

    def show_login(self):
        self.login_window = LoginWindow(self.show_main)
        self.login_window.show()

    def show_main(self, user_role):
        self.login_window.close()
        self.main_window = MainWindow(user_role)
        self.main_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Times New Roman", 12)
    app.setFont(font)
    app.setLayoutDirection(Qt.RightToLeft)

    controller = AppController()
    controller.show_login()

    sys.exit(app.exec_())