"""
وظيفة الملف: لوحة إدارة العروض والتخفيضات (Offers Management UI).
الطبقة: Presentation Layer

ملاحظات معمارية وتشغيلية:
- [Thin Client]&#58; الواجهة خالية من أي استعلام SQL وتعتمد بالكامل على OffersDAO.
- [Robust ID Fix]&#58; إعادة التحديد تعتمد على offer_id حصراً لتجنب فقدان التحديد بعد الحفظ/التحديث.
- [Dynamic UX]&#58; الحد الأعلى واللاحقة لحقل القيمة يتغيران ديناميكياً حسب نوع الخصم.
- [UI Surgical Rebuild]&#58; تم إصلاح تصميم الصفحة جراحياً مع التركيز على:
  1) تحسين قائمة العروض الحالية
  2) تكبير الخطوط والعناصر
  3) إزالة التكدس والتصغير غير المبرر
  4) الحفاظ على بنية الصفحة واستقرارها دون العبث بالنواة
- [Clarified Terminology]&#58;   - "عرض على أصناف محددة" = خصم يطبق على أدوية مختارة فقط
  - "خصم على إجمالي السلة" = خصم يطبق على إجمالي فاتورة البيع
- [Offer Scope Awareness]&#58;   - عرض على أصناف محددة = يطبق على أصناف مختارة فقط.
  - خصم على إجمالي السلة = يطبق على إجمالي الفاتورة/السلة.
- [Safe Delete UI]&#58;   تمت إضافة زر حذف العرض في الواجهة بشكل آمن.
  إذا لم تكن دالة الحذف موجودة بعد في OffersDAO فسيتم إظهار رسالة واضحة بدون كسر النظام.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QDateEdit, QMessageBox, QSplitter, QGroupBox,
    QDoubleSpinBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QFrame, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor
import logging

from models.offers_dao import OffersDAO

logger = logging.getLogger(__name__)


class OffersPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.offers_dao = OffersDAO()

        self.current_offer_id = None
        self.current_mode = 'view'
        self.current_offer_is_active = None

        # مخزن داخلي للأدوية المؤهلة للعروض
        self.all_offerable_medicines = []

        # كاش يحفظ التحديد حتى أثناء الفلترة
        self.selected_medicine_ids_cache = set()

        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.setup_ui()
            self.load_eligible_medicines()
            self.load_offers()

    # ==========================================
    # واجهة رفض الوصول
    # ==========================================
    def init_access_denied_ui(self):
        layout = QVBoxLayout(self)
        warning_lbl = QLabel(
            "⛔ صلاحيات غير كافية.\n"
            "هذه الصفحة مخصصة لمدير النظام فقط (إدارة العروض والتسعير)."
        )
        warning_lbl.setAlignment(Qt.AlignCenter)
        warning_lbl.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #C0392B;
            font-family: 'Times New Roman';
        """)
        layout.addStretch()
        layout.addWidget(warning_lbl)
        layout.addStretch()

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def setup_ui(self):
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("""
            QWidget {
                font-family: 'Times New Roman';
                font-size: 16px;
                color: #2C3E50;
            }
            QGroupBox {
                font-size: 17px;
                font-weight: bold;
                color: #2C3E50;
                border: 1px solid #D5DBDB;
                border-radius: 10px;
                margin-top: 14px;
                background-color: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top right;
                padding: 0 10px;
                color: #34495E;
            }
            QLineEdit, QDateEdit, QComboBox, QDoubleSpinBox, QListWidget {
                border: 1px solid #BDC3C7;
                border-radius: 6px;
                padding: 7px 10px;
                background-color: white;
                min-height: 38px;
            }
            QLineEdit:focus, QDateEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QListWidget:focus {
                border: 1px solid #3498DB;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D5DBDB;
                border-radius: 8px;
                gridline-color: #ECF0F1;
                alternate-background-color: #FAFAFA;
            }
            QHeaderView::section {
                background-color: #F8F9F9;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #D5DBDB;
                padding: 10px;
                font-size: 15px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        title = QLabel("إدارة العروض والتخفيضات")
        title.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
            color: #2C3E50;
        """)
        main_layout.addWidget(title)

        subtitle = QLabel(
            "إدارة العروض على الأصناف المحددة أو الخصومات المطبقة على إجمالي السلة، "
            "مع منع الأدوية الحساسة من الدخول في العروض حسب سياسة النواة."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("""
            font-size: 15px;
            color: #5D6D7E;
            padding-bottom: 2px;
        """)
        main_layout.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        # ------------------------------------------
        # القسم الأيمن: قائمة العروض
        # ------------------------------------------
        list_container = QFrame()
        list_container.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D5DBDB;
                border-radius: 10px;
            }
        """)
        list_container.setMinimumWidth(620)

        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(14, 14, 14, 14)
        list_layout.setSpacing(10)

        list_header = QHBoxLayout()
        list_title = QLabel("قائمة العروض الحالية")
        list_title.setStyleSheet("""
            font-size: 21px;
            font-weight: bold;
            color: #2C3E50;
        """)

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setMinimumHeight(42)
        self.btn_refresh.setMinimumWidth(130)
        self.btn_refresh.setStyleSheet(self._secondary_btn_style())
        self.btn_refresh.clicked.connect(self.load_offers)

        list_header.addWidget(list_title)
        list_header.addStretch()
        list_header.addWidget(self.btn_refresh)
        list_layout.addLayout(list_header)

        self.lbl_list_hint = QLabel("اختر عرضًا من الجدول لعرض تفاصيله أو تعديله أو حذفِه.")
        self.lbl_list_hint.setStyleSheet("""
            font-size: 14px;
            color: #7F8C8D;
        """)
        self.lbl_list_hint.setWordWrap(True)
        list_layout.addWidget(self.lbl_list_hint)

        self.offers_table = QTableWidget()
        self.offers_table.setColumnCount(8)
        self.offers_table.setHorizontalHeaderLabels([
            "ID", "اسم العرض", "النطاق", "نوع الخصم", "القيمة", "من", "إلى", "الحالة"
        ])
        self.offers_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.offers_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.offers_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.offers_table.setAlternatingRowColors(True)
        self.offers_table.setWordWrap(False)
        self.offers_table.verticalHeader().setVisible(False)
        self.offers_table.setMinimumHeight(360)
        self.offers_table.itemSelectionChanged.connect(self.on_offer_selected)
        self._configure_offers_table_header()
        list_layout.addWidget(self.offers_table, 1)

        self.lbl_offers_count = QLabel("عدد العروض: 0")
        self.lbl_offers_count.setStyleSheet("""
            font-size: 14px;
            color: #566573;
            font-weight: bold;
        """)
        list_layout.addWidget(self.lbl_offers_count)

        create_buttons_layout = QHBoxLayout()

        self.btn_new_item_offer = QPushButton("➕ عرض على أصناف محددة")
        self.btn_new_item_offer.setCursor(Qt.PointingHandCursor)
        self.btn_new_item_offer.setMinimumHeight(46)
        self.btn_new_item_offer.setStyleSheet(self._primary_blue_btn_style())
        self.btn_new_item_offer.clicked.connect(self.prepare_new_item_offer)

        self.btn_new_cart_offer = QPushButton("🛒 خصم على إجمالي السلة")
        self.btn_new_cart_offer.setCursor(Qt.PointingHandCursor)
        self.btn_new_cart_offer.setMinimumHeight(46)
        self.btn_new_cart_offer.setStyleSheet(self._primary_purple_btn_style())
        self.btn_new_cart_offer.clicked.connect(self.prepare_new_cart_offer)

        create_buttons_layout.addWidget(self.btn_new_item_offer)
        create_buttons_layout.addWidget(self.btn_new_cart_offer)
        list_layout.addLayout(create_buttons_layout)

        # ------------------------------------------
        # القسم الأيسر: تفاصيل العرض
        # ------------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setMinimumWidth(560)

        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(4, 0, 4, 0)
        form_layout.setSpacing(12)

        # بطاقة العنوان/الحالة
        status_card = QFrame()
        status_card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D5DBDB;
                border-radius: 10px;
            }
        """)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(8)

        self.lbl_form_title = QLabel("اختر عرضًا من القائمة لعرض تفاصيله")
        self.lbl_form_title.setStyleSheet("""
            font-size: 21px;
            font-weight: bold;
            color: #2C3E50;
        """)

        self.lbl_scope_explain = QLabel("النطاق: —")
        self.lbl_scope_explain.setStyleSheet("""
            font-size: 15px;
            font-weight: bold;
            color: #8E44AD;
        """)

        self.lbl_mode_hint = QLabel(
            "العرض على الأصناف المحددة يطبق على أدوية مختارة فقط، "
            "أما خصم إجمالي السلة فيطبق على إجمالي فاتورة البيع."
        )
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setStyleSheet("""
            font-size: 14px;
            color: #5D6D7E;
        """)

        self.lbl_status_hint = QLabel("الحالة الحالية: —")
        self.lbl_status_hint.setStyleSheet("""
            font-size: 14px;
            color: #566573;
            font-weight: bold;
        """)

        status_layout.addWidget(self.lbl_form_title)
        status_layout.addWidget(self.lbl_scope_explain)
        status_layout.addWidget(self.lbl_mode_hint)
        status_layout.addWidget(self.lbl_status_hint)
        form_layout.addWidget(status_card)

        # مجموعة بيانات العرض
        self.form_group = QGroupBox("بيانات العرض")
        fg_layout = QGridLayout(self.form_group)
        fg_layout.setContentsMargins(14, 24, 14, 14)
        fg_layout.setHorizontalSpacing(12)
        fg_layout.setVerticalSpacing(12)

        lbl_name = QLabel("اسم العرض:")
        lbl_discount_type = QLabel("نوع الخصم:")
        lbl_discount_value = QLabel("القيمة:")
        lbl_start = QLabel("تاريخ البدء:")
        lbl_end = QLabel("تاريخ الانتهاء:")

        for lbl in (lbl_name, lbl_discount_type, lbl_discount_value, lbl_start, lbl_end):
            lbl.setStyleSheet("font-weight: bold; font-size: 15px;")

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("مثال: خصم الربيع - عرض مسكنات - خصم السلة الأسبوعي")

        self.combo_discount_type = QComboBox()
        self.combo_discount_type.addItems(["نسبة مئوية (%)", "مبلغ ثابت (Fixed)"])
        self.combo_discount_type.currentIndexChanged.connect(self.on_discount_type_changed)

        self.spin_discount_value = QDoubleSpinBox()
        self.spin_discount_value.setDecimals(2)

        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)

        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)

        fg_layout.addWidget(lbl_name, 0, 0)
        fg_layout.addWidget(self.txt_name, 0, 1, 1, 3)

        fg_layout.addWidget(lbl_discount_type, 1, 0)
        fg_layout.addWidget(self.combo_discount_type, 1, 1)

        fg_layout.addWidget(lbl_discount_value, 1, 2)
        fg_layout.addWidget(self.spin_discount_value, 1, 3)

        fg_layout.addWidget(lbl_start, 2, 0)
        fg_layout.addWidget(self.date_start, 2, 1)

        fg_layout.addWidget(lbl_end, 2, 2)
        fg_layout.addWidget(self.date_end, 2, 3)

        fg_layout.setColumnStretch(1, 1)
        fg_layout.setColumnStretch(3, 1)

        form_layout.addWidget(self.form_group)

        # مجموعة الأصناف
        self.meds_group = QGroupBox("الأصناف المشمولة بالعرض")
        meds_layout = QVBoxLayout(self.meds_group)
        meds_layout.setContentsMargins(14, 24, 14, 14)
        meds_layout.setSpacing(10)

        meds_help = QLabel(
            "تظهر هنا فقط الأدوية المسموح بدخولها في العروض حسب قواعد النواة، "
            "بعد استبعاد الأصناف الحساسة أو المحظورة."
        )
        meds_help.setWordWrap(True)
        meds_help.setStyleSheet("""
            font-size: 14px;
            color: #5D6D7E;
        """)
        meds_layout.addWidget(meds_help)

        search_meds_layout = QHBoxLayout()
        self.txt_search_meds = QLineEdit()
        self.txt_search_meds.setPlaceholderText("ابحث داخل قائمة الأدوية المؤهلة...")
        self.txt_search_meds.textChanged.connect(self.filter_medicines_list)

        self.lbl_selected_meds_count = QLabel("المحدد: 0")
        self.lbl_selected_meds_count.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #566573;
        """)

        search_meds_layout.addWidget(self.txt_search_meds, 1)
        search_meds_layout.addWidget(self.lbl_selected_meds_count)
        meds_layout.addLayout(search_meds_layout)

        self.list_medicines = QListWidget()
        self.list_medicines.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_medicines.itemSelectionChanged.connect(self.update_selected_medicines_count)
        self.list_medicines.setMinimumHeight(240)
        meds_layout.addWidget(self.list_medicines)

        form_layout.addWidget(self.meds_group)

        # أزرار التحكم
        actions_card = QFrame()
        actions_card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D5DBDB;
                border-radius: 10px;
            }
        """)
        self.actions_layout = QHBoxLayout(actions_card)
        self.actions_layout.setContentsMargins(12, 12, 12, 12)
        self.actions_layout.setSpacing(10)

        self.btn_save = QPushButton("💾 حفظ العرض")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setMinimumHeight(44)
        self.btn_save.setMinimumWidth(145)
        self.btn_save.setStyleSheet(self._success_btn_style())
        self.btn_save.clicked.connect(self.save_offer)

        self.btn_cancel = QPushButton("إلغاء")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setMinimumHeight(44)
        self.btn_cancel.setMinimumWidth(110)
        self.btn_cancel.setStyleSheet(self._secondary_btn_style())
        self.btn_cancel.clicked.connect(self.reset_form)

        self.btn_edit = QPushButton("✏️ تعديل العرض")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.setMinimumHeight(44)
        self.btn_edit.setMinimumWidth(145)
        self.btn_edit.setStyleSheet(self._warning_btn_style())
        self.btn_edit.clicked.connect(self.enable_edit_mode)

        self.btn_delete = QPushButton("🗑️ حذف العرض")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setMinimumHeight(44)
        self.btn_delete.setMinimumWidth(140)
        self.btn_delete.setStyleSheet(self._danger_btn_style())
        self.btn_delete.clicked.connect(self.delete_offer)

        self.btn_toggle_status = QPushButton("⏸️ إيقاف / تفعيل")
        self.btn_toggle_status.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_status.setMinimumHeight(44)
        self.btn_toggle_status.setMinimumWidth(150)
        self.btn_toggle_status.setStyleSheet(self._dark_btn_style())
        self.btn_toggle_status.clicked.connect(self.toggle_status)

        self.actions_layout.addWidget(self.btn_save)
        self.actions_layout.addWidget(self.btn_cancel)
        self.actions_layout.addStretch()
        self.actions_layout.addWidget(self.btn_edit)
        self.actions_layout.addWidget(self.btn_delete)
        self.actions_layout.addWidget(self.btn_toggle_status)

        form_layout.addWidget(actions_card)
        form_layout.addStretch()

        scroll.setWidget(form_container)

        splitter.addWidget(list_container)
        splitter.addWidget(scroll)
        splitter.setSizes([700, 620])
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)

        main_layout.addWidget(splitter, 1)

        self.on_discount_type_changed()
        self.reset_form()

    def _configure_offers_table_header(self):
        header = self.offers_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # ID
        header.setSectionResizeMode(1, QHeaderView.Stretch)            # اسم العرض
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)   # النطاق
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)   # نوع الخصم
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # القيمة
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)   # من
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # إلى
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)   # الحالة

    # ==========================================
    # أنماط الأزرار
    # ==========================================
    def _primary_blue_btn_style(self):
        return """
            QPushButton {
                background-color: #2980B9;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #2471A3; }
            QPushButton:disabled { background-color: #D6EAF8; color: #7F8C8D; }
        """

    def _primary_purple_btn_style(self):
        return """
            QPushButton {
                background-color: #8E44AD;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #7D3C98; }
            QPushButton:disabled { background-color: #EBDEF0; color: #7F8C8D; }
        """

    def _success_btn_style(self):
        return """
            QPushButton {
                background-color: #27AE60;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #229954; }
            QPushButton:disabled { background-color: #D5F5E3; color: #7F8C8D; }
        """

    def _warning_btn_style(self):
        return """
            QPushButton {
                background-color: #F39C12;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #D68910; }
            QPushButton:disabled { background-color: #FCF3CF; color: #7F8C8D; }
        """

    def _danger_btn_style(self):
        return """
            QPushButton {
                background-color: #E74C3C;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #CB4335; }
            QPushButton:disabled { background-color: #F5B7B1; color: #7F8C8D; }
        """

    def _dark_btn_style(self):
        return """
            QPushButton {
                background-color: #34495E;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #2C3E50; }
            QPushButton:disabled { background-color: #D6DBDF; color: #7F8C8D; }
        """

    def _secondary_btn_style(self):
        return """
            QPushButton {
                background-color: #ECF0F1;
                color: #2C3E50;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 14px;
                border: 1px solid #D5DBDB;
                font-size: 15px;
            }
            QPushButton:hover { background-color: #D5DBDB; }
            QPushButton:disabled { background-color: #F4F6F7; color: #A6ACAF; }
        """

    # ==========================================
    # Helpers وصفية
    # ==========================================
    def _scope_to_display(self, scope_type):
        if scope_type == 'item':
            return "عرض على أصناف محددة"
        if scope_type == 'cart':
            return "خصم على إجمالي السلة"
        return "غير معروف"

    def _discount_type_to_display(self, discount_type):
        if discount_type == 'percent':
            return "نسبة مئوية"
        if discount_type == 'fixed':
            return "مبلغ ثابت"
        return "غير معروف"

    def _status_to_display(self, is_active):
        return "✅ نشط" if int(is_active) == 1 else "⛔ متوقف"

    def _status_color(self, is_active):
        return "#27AE60" if int(is_active) == 1 else "#C0392B"

    def _mode_scope_type(self):
        if self.current_mode in ['new_item', 'edit_item', 'view_item']:
            return 'item'
        if self.current_mode in ['new_cart', 'edit_cart', 'view_cart']:
            return 'cart'
        return None

    # ==========================================
    # تحديث بطاقة الحالة
    # ==========================================
    def refresh_status_card(self):
        scope_type = self._mode_scope_type()

        if self.current_mode == 'view' and not self.current_offer_id:
            self.lbl_scope_explain.setText("النطاق: —")
            self.lbl_status_hint.setText("الحالة الحالية: —")
            self.lbl_status_hint.setStyleSheet("""
                font-size: 14px;
                color: #566573;
                font-weight: bold;
            """)
            return

        if scope_type == 'item':
            self.lbl_scope_explain.setText("النطاق: عرض على أصناف محددة")
        elif scope_type == 'cart':
            self.lbl_scope_explain.setText("النطاق: خصم على إجمالي السلة")
        else:
            self.lbl_scope_explain.setText("النطاق: —")

        if self.current_offer_is_active is None:
            self.lbl_status_hint.setText("الحالة الحالية: —")
            self.lbl_status_hint.setStyleSheet("""
                font-size: 14px;
                color: #566573;
                font-weight: bold;
            """)
        else:
            status_text = self._status_to_display(self.current_offer_is_active)
            color = self._status_color(self.current_offer_is_active)
            self.lbl_status_hint.setText(f"الحالة الحالية: {status_text}")
            self.lbl_status_hint.setStyleSheet(f"""
                font-size: 14px;
                color: {color};
                font-weight: bold;
            """)

    # ==========================================
    # تحميل الأدوية المؤهلة
    # ==========================================
    def load_eligible_medicines(self):
        self.list_medicines.clear()
        self.all_offerable_medicines.clear()
        self.selected_medicine_ids_cache.clear()

        eligible_meds = self.offers_dao.get_offerable_medicines()
        for row in eligible_meds:
            med_id = row[0]
            med_name = row[1]
            med_barcode = row[2]

            display_text = f"{med_name} ({med_barcode})" if med_barcode else med_name
            self.all_offerable_medicines.append({
                "id": med_id,
                "name": med_name,
                "barcode": med_barcode,
                "display": display_text
            })

        self.populate_medicines_list()

    def populate_medicines_list(self, filter_text=""):
        self.list_medicines.blockSignals(True)
        self.list_medicines.clear()

        filter_text = (filter_text or "").strip().lower()

        for med in self.all_offerable_medicines:
            haystack = f"{med['name']} {med['barcode']} {med['display']}".lower()
            if filter_text and filter_text not in haystack:
                continue

            item = QListWidgetItem(med["display"])
            item.setData(Qt.UserRole, med["id"])
            self.list_medicines.addItem(item)

            if med["id"] in self.selected_medicine_ids_cache:
                item.setSelected(True)

        self.list_medicines.blockSignals(False)
        self.update_selected_medicines_count()

    def filter_medicines_list(self):
        self.populate_medicines_list(self.txt_search_meds.text())

    def update_selected_medicines_count(self):
        # إزالة المعرفات الظاهرة ثم إعادة إضافة المحدد منها فقط
        visible_ids = set()
        selected_visible_ids = set()

        for i in range(self.list_medicines.count()):
            item = self.list_medicines.item(i)
            med_id = item.data(Qt.UserRole)
            visible_ids.add(med_id)
            if item.isSelected():
                selected_visible_ids.add(med_id)

        self.selected_medicine_ids_cache -= visible_ids
        self.selected_medicine_ids_cache |= selected_visible_ids

        self.lbl_selected_meds_count.setText(f"المحدد: {len(self.selected_medicine_ids_cache)}")

    def get_selected_medicine_ids(self):
        return list(self.selected_medicine_ids_cache)

    # ==========================================
    # تحميل العروض
    # ==========================================
    def load_offers(self):
        selected_offer_id = self.current_offer_id

        self.offers_table.blockSignals(True)
        self.offers_table.setRowCount(0)

        offers = self.offers_dao.get_all_offers()

        for row_idx, row in enumerate(offers):
            self.offers_table.insertRow(row_idx)

            scope_str = self._scope_to_display(row[5])
            disc_type_str = self._discount_type_to_display(row[3])

            if row[3] == 'percent':
                value_str = f"{float(row[4]):,.2f} %"
            else:
                value_str = f"{float(row[4]):,.2f}"

            status_str = self._status_to_display(row[8])

            row_values = [
                str(row[0]),
                str(row[1]),
                scope_str,
                disc_type_str,
                value_str,
                str(row[6]),
                str(row[7]),
                status_str
            ]

            for col_idx, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 7:
                    item.setForeground(QColor(self._status_color(row[8])))

                self.offers_table.setItem(row_idx, col_idx, item)

        self.offers_table.blockSignals(False)
        self.lbl_offers_count.setText(f"عدد العروض: {len(offers)}")

        if selected_offer_id:
            self.reselect_current_offer(selected_offer_id)

    # ==========================================
    # إعادة تعيين النموذج
    # ==========================================
    def reset_form(self):
        self.offers_table.blockSignals(True)
        self.offers_table.clearSelection()
        self.offers_table.blockSignals(False)

        self.current_offer_id = None
        self.current_mode = 'view'
        self.current_offer_is_active = None
        self.selected_medicine_ids_cache.clear()

        self.lbl_form_title.setText("اختر عرضًا من القائمة لعرض تفاصيله")
        self.txt_name.clear()
        self.combo_discount_type.setCurrentIndex(0)
        self.spin_discount_value.setValue(0.01)
        self.date_start.setDate(QDate.currentDate())
        self.date_end.setDate(QDate.currentDate().addDays(7))
        self.txt_search_meds.clear()

        self.populate_medicines_list()
        self.update_ui_state()

    # ==========================================
    # تفعيل/تعطيل عناصر الواجهة
    # ==========================================
    def update_ui_state(self):
        is_editing = self.current_mode in ['new_item', 'new_cart', 'edit_item', 'edit_cart']
        scope_type = self._mode_scope_type()
        is_item_scope = scope_type == 'item'

        self.txt_name.setEnabled(is_editing)
        self.combo_discount_type.setEnabled(is_editing)
        self.spin_discount_value.setEnabled(is_editing)
        self.date_start.setEnabled(is_editing)
        self.date_end.setEnabled(is_editing)

        self.meds_group.setVisible(is_item_scope)
        self.list_medicines.setEnabled(is_editing and is_item_scope)
        self.txt_search_meds.setEnabled(is_editing and is_item_scope)

        self.btn_save.setVisible(is_editing)
        self.btn_cancel.setVisible(is_editing)

        self.btn_edit.setVisible(self.current_mode in ['view_item', 'view_cart'])
        self.btn_toggle_status.setVisible(self.current_mode in ['view_item', 'view_cart'])
        self.btn_delete.setVisible(self.current_mode in ['view_item', 'view_cart'])

        if self.current_mode in ['view_item', 'view_cart'] and self.current_offer_is_active is not None:
            if int(self.current_offer_is_active) == 1:
                self.btn_toggle_status.setText("⏸️ إيقاف العرض")
            else:
                self.btn_toggle_status.setText("▶️ تفعيل العرض")
        else:
            self.btn_toggle_status.setText("⏸️ إيقاف / تفعيل")

        self.refresh_status_card()

    # ==========================================
    # أوضاع الإنشاء
    # ==========================================
    def prepare_new_item_offer(self):
        self.reset_form()
        self.current_mode = 'new_item'
        self.current_offer_is_active = 1
        self.lbl_form_title.setText("✨ إنشاء عرض جديد على أصناف محددة")
        self.update_ui_state()

    def prepare_new_cart_offer(self):
        self.reset_form()
        self.current_mode = 'new_cart'
        self.current_offer_is_active = 1
        self.lbl_form_title.setText("🛒 إنشاء خصم جديد على إجمالي السلة")
        self.update_ui_state()

    def enable_edit_mode(self):
        if not self.current_offer_id:
            return

        if self.current_mode == 'view_item':
            self.current_mode = 'edit_item'
        elif self.current_mode == 'view_cart':
            self.current_mode = 'edit_cart'

        self.lbl_form_title.setText(f"✏️ تعديل العرض (ID: {self.current_offer_id})")
        self.update_ui_state()

    # ==========================================
    # اختيار عرض من الجدول
    # ==========================================
    def on_offer_selected(self):
        row = self.offers_table.currentRow()
        if row < 0:
            return

        try:
            offer_id = int(self.offers_table.item(row, 0).text())
        except Exception:
            return

        self.current_offer_id = offer_id

        header, medicines = self.offers_dao.get_offer_details(offer_id)
        if not header:
            QMessageBox.warning(self, "خطأ", "تعذر جلب تفاصيل العرض.")
            return

        self.txt_name.setText(header[1])

        d_type = header[3]
        self.combo_discount_type.setCurrentIndex(0 if d_type == 'percent' else 1)
        self.on_discount_type_changed()
        self.spin_discount_value.setValue(float(header[4]))

        start_date = QDate.fromString(header[6], "yyyy-MM-dd")
        end_date = QDate.fromString(header[7], "yyyy-MM-dd")
        if start_date.isValid():
            self.date_start.setDate(start_date)
        if end_date.isValid():
            self.date_end.setDate(end_date)

        scope_type = header[5]
        self.current_mode = 'view_item' if scope_type == 'item' else 'view_cart'
        self.current_offer_is_active = int(header[8]) if len(header) > 8 and header[8] is not None else 0
        self.lbl_form_title.setText(f"🔍 تفاصيل العرض: {header[1]}")

        linked_ids = [m[0] for m in medicines] if scope_type == 'item' else []
        self.selected_medicine_ids_cache = set(linked_ids)

        self.populate_medicines_list(self.txt_search_meds.text())
        self.update_ui_state()

    # ==========================================
    # تغيير نوع الخصم
    # ==========================================
    def on_discount_type_changed(self):
        self.spin_discount_value.blockSignals(True)

        if self.combo_discount_type.currentIndex() == 0:
            self.spin_discount_value.setRange(0.01, 100.00)
            self.spin_discount_value.setSuffix(" %")
        else:
            self.spin_discount_value.setRange(0.01, 1000000.00)
            self.spin_discount_value.setSuffix("")

        self.spin_discount_value.blockSignals(False)

    # ==========================================
    # حفظ العرض
    # ==========================================
    def save_offer(self):
        name = self.txt_name.text().strip()
        d_type = 'percent' if self.combo_discount_type.currentIndex() == 0 else 'fixed'
        d_val = self.spin_discount_value.value()
        s_date = self.date_start.date().toString("yyyy-MM-dd")
        e_date = self.date_end.date().toString("yyyy-MM-dd")

        if not name:
            QMessageBox.warning(self, "تنبيه", "اسم العرض مطلوب.")
            return

        if self.date_start.date() > self.date_end.date():
            QMessageBox.warning(self, "تنبيه", "تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء أو مساويًا له.")
            return

        success = False
        msg = ""
        returned_offer_id = None

        if self.current_mode in ['new_item', 'edit_item']:
            med_ids = self.get_selected_medicine_ids()
            if not med_ids:
                QMessageBox.warning(self, "تنبيه", "يجب تحديد دواء واحد على الأقل لهذا النوع من العروض.")
                return

            if self.current_mode == 'new_item':
                success, msg, returned_offer_id = self.offers_dao.add_item_offer(
                    name, d_type, d_val, s_date, e_date, self.user_id, med_ids
                )
            else:
                success, msg = self.offers_dao.update_item_offer(
                    self.current_offer_id, name, d_type, d_val, s_date, e_date, self.user_id, med_ids
                )
                returned_offer_id = self.current_offer_id

        elif self.current_mode in ['new_cart', 'edit_cart']:
            if self.current_mode == 'new_cart':
                success, msg, returned_offer_id = self.offers_dao.add_cart_offer(
                    name, d_type, d_val, s_date, e_date, self.user_id
                )
            else:
                success, msg = self.offers_dao.update_cart_offer(
                    self.current_offer_id, name, d_type, d_val, s_date, e_date, self.user_id
                )
                returned_offer_id = self.current_offer_id

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.load_offers()
            self.reselect_current_offer(returned_offer_id)
        else:
            QMessageBox.critical(self, "فشل (حماية النواة)", msg)

    # ==========================================
    # حذف العرض
    # ==========================================
    def delete_offer(self):
        if not self.current_offer_id:
            return

        reply = QMessageBox.question(
            self,
            "تأكيد الحذف",
            "هل أنت متأكد من حذف هذا العرض نهائيًا؟\n"
            "سيتم رفض العملية إذا كانت النواة لا تدعم الحذف بعد.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        if not hasattr(self.offers_dao, "delete_offer"):
            QMessageBox.warning(
                self,
                "غير مكتمل بعد",
                "واجهة الحذف أصبحت جاهزة، لكن نواة OffersDAO لا تحتوي بعد على دالة delete_offer.\n"
                "نحتاج الآن إلى تعديل models/offers_dao.py لإكمال الحذف الفعلي."
            )
            return

        success, msg = self.offers_dao.delete_offer(self.current_offer_id, self.user_id)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.load_offers()
            self.reset_form()
        else:
            QMessageBox.critical(self, "فشل (حماية النواة)", msg)

    # ==========================================
    # تفعيل/إيقاف العرض
    # ==========================================
    def toggle_status(self):
        if not self.current_offer_id:
            return

        reply = QMessageBox.question(
            self,
            "تأكيد",
            "هل أنت متأكد من تغيير حالة هذا العرض؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            success, msg = self.offers_dao.toggle_offer_status(self.current_offer_id, self.user_id)
            if success:
                QMessageBox.information(self, "نجاح", msg)
                self.load_offers()
                self.reselect_current_offer(self.current_offer_id)
            else:
                QMessageBox.critical(self, "فشل (حماية النواة)", msg)

    # ==========================================
    # إعادة تحديد العرض الحالي عبر ID
    # ==========================================
    def reselect_current_offer(self, offer_id):
        if not offer_id:
            return

        self.offers_table.blockSignals(True)
        matched_row = -1

        for r in range(self.offers_table.rowCount()):
            try:
                row_offer_id = int(self.offers_table.item(r, 0).text())
            except Exception:
                continue

            if row_offer_id == offer_id:
                matched_row = r
                self.offers_table.selectRow(r)
                self.offers_table.setCurrentCell(r, 0)
                break

        self.offers_table.blockSignals(False)

        if matched_row >= 0:
            self.on_offer_selected()
        else:
            self.reset_form()