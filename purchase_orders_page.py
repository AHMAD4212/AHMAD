"""
وظيفة الملف: واجهة إدارة أوامر الشراء (Purchase Orders UI - Planning Workflow).
الطبقة: Presentation Layer

ملاحظات معمارية وتشغيلية:
- [Visual RBAC]&#58; الصيدلي يرى أزرار التعديل والحذف لمسوداته فقط. المدير يرى للجميع.
- [Robustness]&#58; استخدام currentRow واستدعاء get_low_stock_medicines المضمون.
- [Workflow Stability]&#58; إعادة تحديد الأمر تلقائياً بعد الحفظ لضمان استمرار تدفق العمل.
- [Supplier Integration V25]&#58; دعم البنية الموسعة للموردين (شركة، هاتف، إيميل، عنوان، حالة) داخل قائمة الاختيار.
- [UI Rebuild]&#58; إعادة تنظيم الواجهة بالكامل لتفادي التزاحم البصري والقص على مختلف أحجام النوافذ.
- [Cross-Platform Friendly]&#58; تصميم مرن يحترم اختلاف المقاسات بين Windows / Linux / شاشات مختلفة.
- [Dumb Client]&#58; الواجهة لا تتخذ القرار الأمني النهائي، بل تعتمد على نواة DAO ورسائل الرفض القادمة منها.
"""

from functools import partial

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDateEdit, QMessageBox, QSplitter, QScrollArea,
    QGroupBox, QSpinBox, QDoubleSpinBox, QTextEdit,
    QAbstractItemView, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor

from models.purchase_orders_dao import PurchaseOrdersDAO
from models.suppliers_dao import SuppliersDAO
from models.medicine_dao import MedicineDAO


# ==========================================
# ثوابت التصميم
# ==========================================
FONT_FAMILY = "Times New Roman"

MAIN_BG = "#F4F6F9"
CARD_BG = "#FFFFFF"
TEXT_COLOR = "#2C3E50"
MUTED_TEXT = "#7F8C8D"
BORDER_COLOR = "#E0E6ED"

PRIMARY_COLOR = "#2980B9"
PRIMARY_HOVER = "#2471A3"

SUCCESS_COLOR = "#27AE60"
SUCCESS_HOVER = "#229954"

DANGER_COLOR = "#E74C3C"
DANGER_HOVER = "#CB4335"

WARNING_COLOR = "#F39C12"
WARNING_HOVER = "#D68910"

LIGHT_INFO_BG = "#F8F9F9"
NOTICE_BG = "#EAFAF1"
NOTICE_BORDER = "#ABEBC6"


class PurchaseOrdersPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role")

        self.po_dao = PurchaseOrdersDAO()
        self.suppliers_dao = SuppliersDAO()
        self.medicine_dao = MedicineDAO()

        self.current_po_id = None
        self.current_status = None
        self.current_creator_id = None

        self.setup_ui()
        self.load_suppliers()
        self.load_medicines()
        self.load_orders()

    # ==========================================
    # تحديث مرجعي عند إظهار الصفحة
    # ==========================================
    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.load_suppliers()
            self.load_medicines()
            self.load_orders()
        except Exception:
            pass

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def setup_ui(self):
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(f"background-color: {MAIN_BG}; font-family: '{FONT_FAMILY}';")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        title = QLabel("أوامر الشراء (تخطيط)")
        title.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {TEXT_COLOR};
            font-family: '{FONT_FAMILY}';
        """)
        main_layout.addWidget(title)

        subtitle = QLabel(
            "إنشاء مسودات الطلبات، إرسالها للمراجعة، اعتمادها، ثم تسليمها لاحقاً إلى شاشة فواتير الشراء عند الاستلام."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"""
            font-size: 14px;
            color: {MUTED_TEXT};
            font-family: '{FONT_FAMILY}';
            padding-bottom: 4px;
        """)
        main_layout.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)

        # ==========================================
        # القسم الأول: قائمة الأوامر
        # ==========================================
        list_container = self._create_card_frame()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(14, 14, 14, 14)
        list_layout.setSpacing(10)

        list_toolbar = QHBoxLayout()
        list_toolbar.setSpacing(10)

        filter_lbl = QLabel("تصفية بالحالة:")
        filter_lbl.setStyleSheet(self._label_style(bold=True, size=13))

        self.status_filter = QComboBox()
        self.status_filter.addItems([
            "الكل", "draft", "submitted", "approved",
            "partially_received", "received", "cancelled"
        ])
        self.status_filter.setMinimumHeight(40)
        self.status_filter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.status_filter.setStyleSheet(self._input_style())
        self.status_filter.currentTextChanged.connect(self.load_orders)

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.setMinimumHeight(40)
        self.btn_refresh.setMinimumWidth(110)
        self.btn_refresh.setStyleSheet(
            self._button_style("#ECF0F1", TEXT_COLOR, "#D5DBDB")
        )
        self.btn_refresh.clicked.connect(self.load_orders)

        self.btn_new_draft = QPushButton("➕ إنشاء مسودة جديدة")
        self.btn_new_draft.setMinimumHeight(40)
        self.btn_new_draft.setMinimumWidth(180)
        self.btn_new_draft.setStyleSheet(
            self._button_style(SUCCESS_COLOR, "white", SUCCESS_HOVER)
        )
        self.btn_new_draft.clicked.connect(self.clear_form)

        list_toolbar.addWidget(filter_lbl)
        list_toolbar.addWidget(self.status_filter, 1)
        list_toolbar.addWidget(self.btn_refresh)
        list_toolbar.addStretch()
        list_toolbar.addWidget(self.btn_new_draft)
        list_layout.addLayout(list_toolbar)

        self.orders_summary_lbl = QLabel("عدد الأوامر الظاهر: 0")
        self.orders_summary_lbl.setStyleSheet(self._label_style(size=12, color="#566573"))
        list_layout.addWidget(self.orders_summary_lbl)

        self.orders_table = QTableWidget()
        self.orders_table.setColumnCount(7)
        self.orders_table.setHorizontalHeaderLabels([
            "ID", "رقم الطلب", "المورد", "الحالة", "الإنشاء", "المتوقع", "البنود"
        ])
        self.orders_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.orders_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.orders_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.orders_table.setAlternatingRowColors(True)
        self.orders_table.verticalHeader().setVisible(False)
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.orders_table.setStyleSheet(self._table_style())
        self.orders_table.itemSelectionChanged.connect(self.on_order_selected)
        list_layout.addWidget(self.orders_table)

        # ==========================================
        # القسم الثاني: تفاصيل الطلب
        # ==========================================
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("background-color: transparent;")

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(4, 0, 4, 0)
        details_layout.setSpacing(12)

        # ------------------------------
        # بطاقة الحالة العليا
        # ------------------------------
        top_status_card = self._create_card_frame()
        status_grid = QGridLayout(top_status_card)
        status_grid.setContentsMargins(16, 14, 16, 14)
        status_grid.setHorizontalSpacing(16)
        status_grid.setVerticalSpacing(8)

        self.lbl_po_number = QLabel("رقم الطلب: (جديد)")
        self.lbl_po_number.setWordWrap(True)
        self.lbl_po_number.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {PRIMARY_COLOR};
            font-family: '{FONT_FAMILY}';
            border: none;
        """)

        self.lbl_po_status = QLabel("الحالة: draft")
        self.lbl_po_status.setWordWrap(True)
        self.lbl_po_status.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {WARNING_COLOR};
            font-family: '{FONT_FAMILY}';
            border: none;
        """)

        self.lbl_creator_hint = QLabel("منشئ الطلب (ID): —")
        self.lbl_creator_hint.setWordWrap(True)
        self.lbl_creator_hint.setStyleSheet(self._label_style(size=13, color="#566573"))

        status_grid.addWidget(self.lbl_po_number, 0, 0)
        status_grid.addWidget(self.lbl_po_status, 0, 1)
        status_grid.addWidget(self.lbl_creator_hint, 1, 0, 1, 2)

        details_layout.addWidget(top_status_card)

        # ------------------------------
        # مجموعة الرأس
        # ------------------------------
        header_group = self._create_groupbox("بيانات أمر الشراء (الرأس)")
        header_layout = QVBoxLayout(header_group)
        header_layout.setContentsMargins(14, 26, 14, 14)
        header_layout.setSpacing(12)

        header_grid = QGridLayout()
        header_grid.setHorizontalSpacing(12)
        header_grid.setVerticalSpacing(10)

        lbl_supplier = QLabel("المورد:")
        lbl_supplier.setStyleSheet(self._label_style(bold=True, size=13))

        self.combo_supplier = QComboBox()
        self.combo_supplier.setMinimumHeight(42)
        self.combo_supplier.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_supplier.setStyleSheet(self._input_style())
        self.combo_supplier.currentIndexChanged.connect(self.on_supplier_changed)

        lbl_expected = QLabel("التاريخ المتوقع:")
        lbl_expected.setStyleSheet(self._label_style(bold=True, size=13))

        self.date_expected = QDateEdit()
        self.date_expected.setCalendarPopup(True)
        self.date_expected.setDate(QDate.currentDate().addDays(3))
        self.date_expected.setMinimumHeight(42)
        self.date_expected.setStyleSheet(self._input_style())

        header_grid.addWidget(lbl_supplier, 0, 0)
        header_grid.addWidget(self.combo_supplier, 0, 1)
        header_grid.addWidget(lbl_expected, 0, 2)
        header_grid.addWidget(self.date_expected, 0, 3)

        header_layout.addLayout(header_grid)

        # معلومات المورد
        supplier_info_grid = QGridLayout()
        supplier_info_grid.setHorizontalSpacing(10)
        supplier_info_grid.setVerticalSpacing(10)

        self.lbl_supplier_company = self._create_info_badge("الشركة: —")
        self.lbl_supplier_phone = self._create_info_badge("الهاتف: —")
        self.lbl_supplier_email = self._create_info_badge("الإيميل: —")
        self.lbl_supplier_address = self._create_info_badge("العنوان: —")

        supplier_info_grid.addWidget(self.lbl_supplier_company, 0, 0)
        supplier_info_grid.addWidget(self.lbl_supplier_phone, 0, 1)
        supplier_info_grid.addWidget(self.lbl_supplier_email, 1, 0)
        supplier_info_grid.addWidget(self.lbl_supplier_address, 1, 1)

        header_layout.addLayout(supplier_info_grid)

        notes_lbl = QLabel("ملاحظات عامة للطلب:")
        notes_lbl.setStyleSheet(self._label_style(bold=True, size=13))

        self.txt_notes = QTextEdit()
        self.txt_notes.setPlaceholderText("أدخل هنا ملاحظات عامة على أمر الشراء...")
        self.txt_notes.setMinimumHeight(90)
        self.txt_notes.setMaximumHeight(120)
        self.txt_notes.setStyleSheet(self._text_edit_style())

        header_layout.addWidget(notes_lbl)
        header_layout.addWidget(self.txt_notes)

        details_layout.addWidget(header_group)

        # ------------------------------
        # مجموعة إضافة البنود
        # ------------------------------
        self.items_input_group = self._create_groupbox("إضافة أصناف للطلب")
        items_input_layout = QVBoxLayout(self.items_input_group)
        items_input_layout.setContentsMargins(14, 26, 14, 14)
        items_input_layout.setSpacing(12)

        # الصنف في صف مستقل لتفادي القص
        med_row = QVBoxLayout()
        med_row.setSpacing(6)

        med_lbl = QLabel("الصنف:")
        med_lbl.setStyleSheet(self._label_style(bold=True, size=13))

        self.combo_medicine = QComboBox()
        self.combo_medicine.setMinimumHeight(42)
        self.combo_medicine.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_medicine.setStyleSheet(self._input_style())

        med_row.addWidget(med_lbl)
        med_row.addWidget(self.combo_medicine)
        items_input_layout.addLayout(med_row)

        # الكمية والتكلفة في صف مستقل
        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(10)

        qty_lbl = QLabel("الكمية المطلوبة:")
        qty_lbl.setStyleSheet(self._label_style(bold=True, size=13))

        self.spin_qty = QSpinBox()
        self.spin_qty.setRange(1, 10000)
        self.spin_qty.setValue(1)
        self.spin_qty.setMinimumHeight(42)
        self.spin_qty.setStyleSheet(self._input_style())

        cost_lbl = QLabel("تكلفة التقدير:")
        cost_lbl.setStyleSheet(self._label_style(bold=True, size=13))

        self.spin_cost = QDoubleSpinBox()
        self.spin_cost.setRange(0.0, 1000000.0)
        self.spin_cost.setDecimals(2)
        self.spin_cost.setValue(0.0)
        self.spin_cost.setSingleStep(1.0)
        self.spin_cost.setMinimumHeight(42)
        self.spin_cost.setStyleSheet(self._input_style())

        metrics_grid.addWidget(qty_lbl, 0, 0)
        metrics_grid.addWidget(self.spin_qty, 0, 1)
        metrics_grid.addWidget(cost_lbl, 0, 2)
        metrics_grid.addWidget(self.spin_cost, 0, 3)

        items_input_layout.addLayout(metrics_grid)

        # الأزرار في صف مستقل لتجنب القص
        item_actions_row = QHBoxLayout()
        item_actions_row.setSpacing(10)

        self.btn_add_item = QPushButton("⬇️ إضافة الصنف")
        self.btn_add_item.setMinimumHeight(42)
        self.btn_add_item.setMinimumWidth(170)
        self.btn_add_item.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_add_item.setStyleSheet(
            self._button_style(PRIMARY_COLOR, "white", PRIMARY_HOVER)
        )
        self.btn_add_item.clicked.connect(self.add_item_to_table)

        self.btn_low_stock = QPushButton("📦 استيراد النواقص")
        self.btn_low_stock.setMinimumHeight(42)
        self.btn_low_stock.setMinimumWidth(170)
        self.btn_low_stock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_low_stock.setStyleSheet(
            self._button_style(WARNING_COLOR, "white", WARNING_HOVER)
        )
        self.btn_low_stock.clicked.connect(self.load_low_stock)

        item_actions_row.addWidget(self.btn_add_item)
        item_actions_row.addWidget(self.btn_low_stock)
        items_input_layout.addLayout(item_actions_row)

        details_layout.addWidget(self.items_input_group)

        # ------------------------------
        # جدول البنود
        # ------------------------------
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(8)
        self.items_table.setHorizontalHeaderLabels([
            "ID", "الدواء", "الباركود", "الكمية المطلوبة",
            "تكلفة التقدير", "المستلم", "المتبقي", "إجراء"
        ])
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setStretchLastSection(False)
        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.items_table.setMinimumHeight(220)
        self.items_table.setStyleSheet(self._table_style())

        details_layout.addWidget(self.items_table)

        # ------------------------------
        # إشعار التكامل
        # ------------------------------
        self.lbl_integration_notice = QLabel("✅ هذا الطلب أصبح جاهزاً للاستلام من شاشة فواتير الشراء")
        self.lbl_integration_notice.setAlignment(Qt.AlignCenter)
        self.lbl_integration_notice.setWordWrap(True)
        self.lbl_integration_notice.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {SUCCESS_COLOR};
            background-color: {NOTICE_BG};
            border: 1px solid {NOTICE_BORDER};
            border-radius: 6px;
            padding: 10px;
            font-family: '{FONT_FAMILY}';
        """)
        self.lbl_integration_notice.hide()
        details_layout.addWidget(self.lbl_integration_notice)

        # ------------------------------
        # أزرار العمليات
        # ------------------------------
        actions_card = self._create_card_frame()
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(14, 14, 14, 14)
        actions_layout.setSpacing(10)

        # الصف الأول
        row_actions_1 = QHBoxLayout()
        row_actions_1.setSpacing(10)

        self.btn_save_draft = QPushButton("💾 حفظ كمسودة")
        self.btn_save_draft.setMinimumHeight(42)
        self.btn_save_draft.setMinimumWidth(150)
        self.btn_save_draft.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_save_draft.setStyleSheet(
            self._button_style("#95A5A6", "white", "#7F8C8D")
        )
        self.btn_save_draft.clicked.connect(self.save_draft)

        self.btn_submit = QPushButton("📤 إرسال للمراجعة/للمورد")
        self.btn_submit.setMinimumHeight(42)
        self.btn_submit.setMinimumWidth(180)
        self.btn_submit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_submit.setStyleSheet(
            self._button_style(PRIMARY_COLOR, "white", PRIMARY_HOVER)
        )
        self.btn_submit.clicked.connect(self.submit_order)

        self.btn_approve = QPushButton("✅ اعتماد الطلب (Admin)")
        self.btn_approve.setMinimumHeight(42)
        self.btn_approve.setMinimumWidth(170)
        self.btn_approve.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_approve.setStyleSheet(
            self._button_style(SUCCESS_COLOR, "white", SUCCESS_HOVER)
        )
        self.btn_approve.clicked.connect(self.approve_order)

        row_actions_1.addWidget(self.btn_save_draft)
        row_actions_1.addWidget(self.btn_submit)
        row_actions_1.addWidget(self.btn_approve)

        # الصف الثاني
        row_actions_2 = QHBoxLayout()
        row_actions_2.setSpacing(10)

        self.btn_cancel = QPushButton("❌ إلغاء الطلب")
        self.btn_cancel.setMinimumHeight(42)
        self.btn_cancel.setMinimumWidth(150)
        self.btn_cancel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_cancel.setStyleSheet(
            self._button_style(DANGER_COLOR, "white", DANGER_HOVER)
        )
        self.btn_cancel.clicked.connect(self.cancel_order)

        self.btn_delete = QPushButton("🗑️ حذف المسودة")
        self.btn_delete.setMinimumHeight(42)
        self.btn_delete.setMinimumWidth(150)
        self.btn_delete.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_delete.setStyleSheet(
            self._button_style("#FDEDEC", DANGER_COLOR, "#FADBD8", border=f"1px solid {DANGER_COLOR}")
        )
        self.btn_delete.clicked.connect(self.delete_draft)

        row_actions_2.addWidget(self.btn_cancel)
        row_actions_2.addWidget(self.btn_delete)
        row_actions_2.addStretch()

        actions_layout.addLayout(row_actions_1)
        actions_layout.addLayout(row_actions_2)

        details_layout.addWidget(actions_card)

        scroll_area.setWidget(details_widget)

        splitter.addWidget(list_container)
        splitter.addWidget(scroll_area)
        splitter.setSizes([520, 920])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter)

        self.set_form_mode('draft')

    # ==========================================
    # أدوات تنسيق
    # ==========================================
    def _create_card_frame(self):
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
            }}
        """)
        return frame

    def _create_groupbox(self, title):
        box = QGroupBox(title)
        box.setStyleSheet(f"""
            QGroupBox {{
                font-size: 15px;
                font-weight: bold;
                color: {TEXT_COLOR};
                background-color: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
                margin-top: 12px;
                font-family: '{FONT_FAMILY}';
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top right;
                padding: 0 8px;
                color: {PRIMARY_COLOR};
                background-color: transparent;
            }}
        """)
        return box

    def _create_info_badge(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMinimumHeight(44)
        lbl.setStyleSheet(f"""
            background-color: {LIGHT_INFO_BG};
            border: 1px solid #E5E7E9;
            border-radius: 5px;
            padding: 8px;
            color: {TEXT_COLOR};
            font-size: 13px;
            font-family: '{FONT_FAMILY}';
        """)
        return lbl

    def _label_style(self, bold=False, size=14, color=TEXT_COLOR):
        weight = "bold" if bold else "normal"
        return f"""
            font-size: {size}px;
            font-weight: {weight};
            color: {color};
            font-family: '{FONT_FAMILY}';
        """

    def _input_style(self):
        return f"""
            font-size: 14px;
            color: {TEXT_COLOR};
            background-color: white;
            border: 1px solid #BDC3C7;
            border-radius: 6px;
            padding: 6px 10px;
            font-family: '{FONT_FAMILY}';
        """

    def _text_edit_style(self):
        return f"""
            font-size: 14px;
            color: {TEXT_COLOR};
            background-color: white;
            border: 1px solid #BDC3C7;
            border-radius: 6px;
            padding: 6px 10px;
            font-family: '{FONT_FAMILY}';
        """

    def _button_style(self, bg_color, text_color, hover_color, border="none"):
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                border: {border};
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 14px;
                font-family: '{FONT_FAMILY}';
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:disabled {{
                background-color: #E5E8E8;
                color: #BDC3C7;
                border: none;
            }}
        """

    def _table_style(self):
        return f"""
            QTableWidget {{
                background-color: white;
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                font-size: 14px;
                gridline-color: #F0F3F4;
                alternate-background-color: #FAFAFA;
                font-family: '{FONT_FAMILY}';
            }}
            QHeaderView::section {{
                background-color: #F8F9F9;
                border: none;
                border-bottom: 1px solid {BORDER_COLOR};
                padding: 8px;
                font-size: 14px;
                font-weight: bold;
                color: #5D6D7E;
                font-family: '{FONT_FAMILY}';
            }}
            QTableWidget::item {{
                padding: 4px;
            }}
        """

    # ==========================================
    # Helpers عامة
    # ==========================================
    def _safe_text(self, value, default="—"):
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    def _extract_supplier_record(self, sup):
        """
        يدعم البنية القديمة والجديدة للموردين.
        المتوقّع غالباً:
        (id, name, phone, company_name, balance, email, address, notes, is_active, ...)
        """
        if isinstance(sup, dict):
            return {
                "id": sup.get("id"),
                "name": self._safe_text(sup.get("name"), ""),
                "phone": self._safe_text(sup.get("phone")),
                "company": self._safe_text(sup.get("company_name")),
                "balance": sup.get("balance", 0.0),
                "email": self._safe_text(sup.get("email")),
                "address": self._safe_text(sup.get("address")),
                "is_active": int(sup.get("is_active", 1) or 1),
                "raw": sup,
            }

        supplier_id = sup[0] if len(sup) > 0 else None
        name = sup[1] if len(sup) > 1 else ""
        phone = sup[2] if len(sup) > 2 else None
        company = sup[3] if len(sup) > 3 else None
        balance = sup[4] if len(sup) > 4 else 0.0
        email = sup[5] if len(sup) > 5 else None
        address = sup[6] if len(sup) > 6 else None
        is_active = int(sup[8]) if len(sup) > 8 and sup[8] is not None else 1

        return {
            "id": supplier_id,
            "name": self._safe_text(name, ""),
            "phone": self._safe_text(phone),
            "company": self._safe_text(company),
            "balance": balance,
            "email": self._safe_text(email),
            "address": self._safe_text(address),
            "is_active": is_active,
            "raw": sup,
        }

    def _get_existing_item_ids(self):
        existing_ids = []
        for row in range(self.items_table.rowCount()):
            item = self.items_table.item(row, 0)
            if item is None:
                continue
            try:
                existing_ids.append(int(item.text()))
            except Exception:
                continue
        return existing_ids

    def _ensure_filter_shows_status(self, target_status):
        """
        يضمن أن حالة الفلتر الحالية تستطيع إظهار السجل بعد العملية.
        """
        current_filter = self.status_filter.currentText()
        if current_filter not in ("الكل", target_status):
            self.status_filter.setCurrentText(target_status)
            return
        self.load_orders()

    def _validate_form_before_save(self):
        supplier_id = self.combo_supplier.currentData()
        if supplier_id is None:
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار المورد أولاً.")
            return False

        if self.items_table.rowCount() == 0:
            QMessageBox.warning(self, "تنبيه", "لا يمكن حفظ طلب شراء بدون أصناف.")
            return False

        for row in range(self.items_table.rowCount()):
            try:
                qty_item = self.items_table.item(row, 3)
                cost_item = self.items_table.item(row, 4)
                qty = int(float(qty_item.text())) if qty_item else 0
                cost = float(cost_item.text()) if cost_item else 0.0
            except Exception:
                QMessageBox.warning(self, "تنبيه", "يوجد صف غير صالح ضمن بنود الطلب.")
                return False

            if qty <= 0:
                QMessageBox.warning(self, "تنبيه", "الكمية المطلوبة يجب أن تكون أكبر من صفر.")
                return False

            if cost < 0:
                QMessageBox.warning(self, "تنبيه", "تكلفة التقدير لا يمكن أن تكون سالبة.")
                return False

        return True

    # ==========================================
    # تحميل الموردين والأدوية
    # ==========================================
    def load_suppliers(self):
        previous_supplier_id = self.combo_supplier.currentData()

        self.combo_supplier.blockSignals(True)
        self.combo_supplier.clear()
        self.combo_supplier.addItem("-- اختر المورد --", None)

        try:
            suppliers = self.suppliers_dao.get_all_suppliers(active_only=True, include_extended=True)
        except TypeError:
            suppliers = self.suppliers_dao.get_all_suppliers()
        except Exception:
            suppliers = []

        for sup in suppliers:
            parsed = self._extract_supplier_record(sup)
            if parsed["is_active"] != 1:
                continue

            display_text = parsed["name"]
            if parsed["company"] != "—":
                display_text += f" - {parsed['company']}"
            elif parsed["phone"] != "—":
                display_text += f" ({parsed['phone']})"

            self.combo_supplier.addItem(display_text, parsed["id"])
            self.combo_supplier.setItemData(self.combo_supplier.count() - 1, parsed, Qt.UserRole + 1)

        if previous_supplier_id is not None:
            idx = self.combo_supplier.findData(previous_supplier_id)
            if idx >= 0:
                self.combo_supplier.setCurrentIndex(idx)

        self.combo_supplier.blockSignals(False)
        self.on_supplier_changed()

    def load_medicines(self):
        previous_med_id = self.combo_medicine.currentData()

        self.combo_medicine.clear()
        self.combo_medicine.addItem("-- اختر الصنف --", None)

        try:
            medicines = self.medicine_dao.get_all_medicines()
        except Exception:
            medicines = []

        for med in medicines:
            med_id = med[0]
            barcode = med[1] if len(med) > 1 else ""
            name = med[2] if len(med) > 2 else ""
            display = f"{name} ({barcode})" if barcode else name
            self.combo_medicine.addItem(display, med_id)

        if previous_med_id is not None:
            idx = self.combo_medicine.findData(previous_med_id)
            if idx >= 0:
                self.combo_medicine.setCurrentIndex(idx)

    def on_supplier_changed(self):
        idx = self.combo_supplier.currentIndex()
        sup = self.combo_supplier.itemData(idx, Qt.UserRole + 1)

        if not sup:
            self.lbl_supplier_company.setText("الشركة: —")
            self.lbl_supplier_phone.setText("الهاتف: —")
            self.lbl_supplier_email.setText("الإيميل: —")
            self.lbl_supplier_address.setText("العنوان: —")
            return

        self.lbl_supplier_company.setText(f"الشركة: {sup.get('company', '—')}")
        self.lbl_supplier_phone.setText(f"الهاتف: {sup.get('phone', '—')}")
        self.lbl_supplier_email.setText(f"الإيميل: {sup.get('email', '—')}")
        self.lbl_supplier_address.setText(f"العنوان: {sup.get('address', '—')}")

    # ==========================================
    # تحميل قائمة الأوامر
    # ==========================================
    def load_orders(self):
        selected_po_id = self.current_po_id

        self.orders_table.setRowCount(0)

        status_filter = self.status_filter.currentText()
        if status_filter == "الكل":
            status_filter = None

        try:
            rows = self.po_dao.list_purchase_orders(status_filter)
        except Exception:
            rows = []

        for row_idx, row_data in enumerate(rows):
            self.orders_table.insertRow(row_idx)

            po_id = row_data[0]
            po_number = row_data[1]
            supplier_name = row_data[2] or "غير محدد"
            po_status = row_data[3]
            created_at = row_data[4]
            expected_date = row_data[5] or ""
            items_count = row_data[7] if len(row_data) > 7 else ""

            values = [
                str(po_id),
                str(po_number),
                str(supplier_name),
                str(po_status),
                str(created_at),
                str(expected_date),
                str(items_count),
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.orders_table.setItem(row_idx, col_idx, item)

            row_color = self._get_status_row_color(po_status)
            text_color = self._get_status_text_color(po_status)

            for col in range(self.orders_table.columnCount()):
                table_item = self.orders_table.item(row_idx, col)
                if table_item:
                    table_item.setBackground(row_color)
                    if col == 3:
                        table_item.setForeground(text_color)

        self.orders_summary_lbl.setText(f"عدد الأوامر الظاهر: {len(rows)}")

        if selected_po_id:
            self._reselect_specific_order(selected_po_id)

    def _get_status_row_color(self, status):
        if status == "approved":
            return QColor("#EAFAF1")
        if status == "partially_received":
            return QColor("#FEF9E7")
        if status == "received":
            return QColor("#EBEDEF")
        if status == "cancelled":
            return QColor("#FDEDEC")
        if status == "submitted":
            return QColor("#EBF5FB")
        return QColor(Qt.white)

    def _get_status_text_color(self, status):
        if status == "approved":
            return QColor("#1E8449")
        if status == "partially_received":
            return QColor("#B9770E")
        if status == "received":
            return QColor("#566573")
        if status == "cancelled":
            return QColor("#C0392B")
        if status == "submitted":
            return QColor("#2874A6")
        return QColor("#7D6608")

    # ==========================================
    # اختيار وتحميل أمر
    # ==========================================
    def on_order_selected(self):
        row = self.orders_table.currentRow()
        if row < 0:
            return

        try:
            po_id = int(self.orders_table.item(row, 0).text())
        except Exception:
            return

        self.load_order_details(po_id)

    def load_order_details(self, po_id):
        header, items = self.po_dao.get_po_with_items(po_id)
        if not header:
            QMessageBox.warning(self, "خطأ", "تعذر جلب تفاصيل أمر الشراء.")
            return

        self.current_po_id = header[0]
        self.current_status = header[4] if len(header) > 4 else "draft"
        self.current_creator_id = header[10] if len(header) > 10 else None

        self.lbl_po_number.setText(f"رقم الطلب: {header[1]}")
        self.lbl_po_status.setText(f"الحالة: {self.current_status}")
        self.lbl_po_status.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {self._status_label_color(self.current_status)};
            font-family: '{FONT_FAMILY}';
            border: none;
        """)

        creator_text = str(self.current_creator_id) if self.current_creator_id is not None else "—"
        self.lbl_creator_hint.setText(f"منشئ الطلب (ID): {creator_text}")

        supplier_id = header[2] if len(header) > 2 else None
        idx = self.combo_supplier.findData(supplier_id)
        self.combo_supplier.setCurrentIndex(idx if idx >= 0 else 0)

        expected_date = header[7] if len(header) > 7 else None
        if expected_date:
            parsed = QDate.fromString(str(expected_date), "yyyy-MM-dd")
            if parsed.isValid():
                self.date_expected.setDate(parsed)

        notes = header[5] if len(header) > 5 and header[5] else ""
        self.txt_notes.setPlainText(str(notes))

        self.items_table.setRowCount(0)

        for row_idx, item in enumerate(items):
            self.items_table.insertRow(row_idx)

            medicine_id = item[1]
            medicine_name = item[2]
            barcode = item[3]
            requested_qty = item[4]
            estimated_cost = item[5]
            received_qty = item[6]
            remaining_qty = item[7]

            row_values = [
                str(medicine_id),
                str(medicine_name),
                str(barcode),
                str(requested_qty),
                str(estimated_cost),
                str(received_qty),
                str(remaining_qty),
            ]

            for col_idx, value in enumerate(row_values):
                table_item = QTableWidgetItem(value)
                table_item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 6 and self.current_status == "partially_received":
                    try:
                        if float(remaining_qty) > 0:
                            table_item.setForeground(QColor(DANGER_COLOR))
                    except Exception:
                        pass

                self.items_table.setItem(row_idx, col_idx, table_item)

            self._set_remove_button_for_row(row_idx)

        self.set_form_mode(self.current_status)

    def _status_label_color(self, status):
        if status == "approved":
            return "#1E8449"
        if status == "partially_received":
            return "#B9770E"
        if status == "received":
            return "#566573"
        if status == "cancelled":
            return "#C0392B"
        if status == "submitted":
            return "#2874A6"
        return "#E67E22"

    # ==========================================
    # تصفير النموذج
    # ==========================================
    def clear_form(self):
        self.current_po_id = None
        self.current_status = "draft"
        self.current_creator_id = self.user_id

        self.lbl_po_number.setText("رقم الطلب: (جديد)")
        self.lbl_po_status.setText("الحالة: draft")
        self.lbl_po_status.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {WARNING_COLOR};
            font-family: '{FONT_FAMILY}';
            border: none;
        """)

        creator_text = str(self.user_id) if self.user_id is not None else "—"
        self.lbl_creator_hint.setText(f"منشئ الطلب (ID): {creator_text}")

        self.combo_supplier.setCurrentIndex(0)
        self.date_expected.setDate(QDate.currentDate().addDays(3))
        self.txt_notes.clear()
        self.items_table.setRowCount(0)
        self.orders_table.clearSelection()
        self.lbl_integration_notice.hide()

        self.set_form_mode("draft")

    # ==========================================
    # صلاحيات العرض
    # ==========================================
    def set_form_mode(self, status):
        is_creator = (self.current_creator_id == self.user_id)
        has_edit_rights = (self.user_role == "admin") or (self.user_role == "pharmacist" and is_creator)

        is_draft = (status == "draft")
        can_edit_draft = is_draft and has_edit_rights

        self.combo_supplier.setEnabled(can_edit_draft)
        self.date_expected.setEnabled(can_edit_draft)
        self.txt_notes.setEnabled(can_edit_draft)
        self.items_input_group.setEnabled(can_edit_draft)

        for row in range(self.items_table.rowCount()):
            widget = self.items_table.cellWidget(row, 7)
            if widget:
                widget.setEnabled(can_edit_draft)

        self.btn_save_draft.setVisible(can_edit_draft)
        self.btn_submit.setVisible(can_edit_draft)
        self.btn_delete.setVisible(can_edit_draft and self.current_po_id is not None)
        self.btn_approve.setVisible(status == "submitted" and self.user_role == "admin")

        can_cancel = (
            (status == "draft" and has_edit_rights) or
            (status == "submitted" and has_edit_rights) or
            (status == "approved" and self.user_role == "admin")
        )
        self.btn_cancel.setVisible(can_cancel)

        self.lbl_integration_notice.setVisible(status in ["approved", "partially_received"])

    # ==========================================
    # إدارة البنود
    # ==========================================
    def add_item_to_table(self):
        med_id = self.combo_medicine.currentData()
        med_text = self.combo_medicine.currentText().strip()
        qty = self.spin_qty.value()
        cost = self.spin_cost.value()

        if not med_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار دواء أولاً.")
            return

        if qty <= 0:
            QMessageBox.warning(self, "تنبيه", "الكمية المطلوبة يجب أن تكون أكبر من صفر.")
            return

        if cost < 0:
            QMessageBox.warning(self, "تنبيه", "تكلفة التقدير لا يمكن أن تكون سالبة.")
            return

        existing_ids = self._get_existing_item_ids()
        if med_id in existing_ids:
            QMessageBox.warning(self, "تنبيه", "هذا الصنف موجود بالفعل في الطلب.")
            return

        row_idx = self.items_table.rowCount()
        self.items_table.insertRow(row_idx)

        name_part = med_text.split(" (")[0]
        barcode_part = ""
        if "(" in med_text and ")" in med_text:
            barcode_part = med_text.split("(", 1)[1].rsplit(")", 1)[0]

        values = [
            str(med_id),
            name_part,
            barcode_part,
            str(qty),
            f"{cost:.2f}",
            "0",
            str(qty),
        ]

        for col_idx, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            self.items_table.setItem(row_idx, col_idx, item)

        self._set_remove_button_for_row(row_idx)

    def _set_remove_button_for_row(self, row_idx):
        btn_remove = QPushButton("حذف")
        btn_remove.setMinimumHeight(34)
        btn_remove.setMinimumWidth(80)
        btn_remove.setStyleSheet(
            self._button_style("#FDEDEC", DANGER_COLOR, "#FADBD8", border=f"1px solid {DANGER_COLOR}")
        )
        btn_remove.clicked.connect(partial(self.remove_item, row_idx))
        self.items_table.setCellWidget(row_idx, 7, btn_remove)

    def remove_item(self, row_idx):
        self.items_table.removeRow(row_idx)
        self._rebind_remove_buttons()

    def _rebind_remove_buttons(self):
        for row in range(self.items_table.rowCount()):
            widget = self.items_table.cellWidget(row, 7)
            if widget:
                try:
                    widget.clicked.disconnect()
                except Exception:
                    pass
                widget.clicked.connect(partial(self.remove_item, row))

    def load_low_stock(self):
        try:
            low_stock_meds = self.medicine_dao.get_low_stock_medicines()
        except Exception:
            low_stock_meds = []

        existing_ids = self._get_existing_item_ids()
        added_count = 0

        for med in low_stock_meds:
            med_id = med[0]
            barcode = med[1]
            name = med[2]
            buy_price = med[3]
            qty = med[4]
            min_alert = med[5]

            if med_id in existing_ids:
                continue

            suggested_qty = (min_alert * 2) - qty if (min_alert * 2) > qty else min_alert
            if suggested_qty <= 0:
                suggested_qty = 10

            row_idx = self.items_table.rowCount()
            self.items_table.insertRow(row_idx)

            values = [
                str(med_id),
                str(name),
                str(barcode),
                str(suggested_qty),
                f"{float(buy_price or 0.0):.2f}",
                "0",
                str(suggested_qty),
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.items_table.setItem(row_idx, col_idx, item)

            self._set_remove_button_for_row(row_idx)
            added_count += 1

        if added_count > 0:
            QMessageBox.information(self, "استيراد النواقص", f"تمت إضافة {added_count} أصناف وصلت للحد الأدنى.")
        else:
            QMessageBox.information(self, "استيراد النواقص", "لا يوجد نواقص حالياً أو أنها مضافة مسبقاً.")

    # ==========================================
    # تجميع البيانات
    # ==========================================
    def collect_form_data(self):
        supplier_id = self.combo_supplier.currentData()
        expected_date = self.date_expected.date().toString("yyyy-MM-dd")
        notes = self.txt_notes.toPlainText().strip()

        items = []
        for row in range(self.items_table.rowCount()):
            med_id = int(self.items_table.item(row, 0).text())
            qty = int(float(self.items_table.item(row, 3).text()))
            cost = float(self.items_table.item(row, 4).text())

            items.append({
                "medicine_id": med_id,
                "requested_qty": qty,
                "estimated_unit_cost": cost,
                "notes": ""
            })

        return supplier_id, expected_date, notes, items

    # ==========================================
    # إعادة التحديد
    # ==========================================
    def _reselect_specific_order(self, po_id):
        for row in range(self.orders_table.rowCount()):
            try:
                row_po_id = int(self.orders_table.item(row, 0).text())
            except Exception:
                continue

            if row_po_id == po_id:
                self.orders_table.selectRow(row)
                self.orders_table.setCurrentCell(row, 0)
                return

    def _reselect_current_order(self):
        if not self.current_po_id:
            if self.orders_table.rowCount() > 0:
                self.orders_table.selectRow(0)
                self.orders_table.setCurrentCell(0, 0)
                self.on_order_selected()
            return

        self._reselect_specific_order(self.current_po_id)
        self.on_order_selected()

    # ==========================================
    # العمليات الأساسية
    # ==========================================
    def save_draft(self):
        if not self._validate_form_before_save():
            return

        supplier_id, expected_date, notes, items = self.collect_form_data()
        is_new = self.current_po_id is None

        if is_new:
            success, msg = self.po_dao.create_draft(
                supplier_id, expected_date, items, self.user_id, notes
            )
        else:
            success, msg = self.po_dao.update_draft(
                self.current_po_id, supplier_id, expected_date, items, self.user_id, notes
            )

        if success:
            QMessageBox.information(self, "نجاح", msg)

            # إذا كان الفلتر لا يعرض المسودات، نحوله تلقائياً
            if is_new:
                self.current_po_id = None
            self._ensure_filter_shows_status("draft")
            self._reselect_current_order()
        else:
            QMessageBox.critical(self, "فشل", msg)

    def submit_order(self):
        if not self.current_po_id:
            QMessageBox.warning(self, "تنبيه", "يجب حفظ المسودة أولاً قبل الإرسال.")
            return

        if not self._validate_form_before_save():
            return

        supplier_id, expected_date, notes, items = self.collect_form_data()

        update_success, msg = self.po_dao.update_draft(
            self.current_po_id, supplier_id, expected_date, items, self.user_id, notes
        )
        if not update_success:
            QMessageBox.critical(self, "فشل حفظ التعديلات", msg)
            return

        success, msg = self.po_dao.update_po_status(self.current_po_id, "submitted", self.user_id)
        if success:
            QMessageBox.information(self, "نجاح", msg)
            self._ensure_filter_shows_status("submitted")
            self._reselect_current_order()
        else:
            QMessageBox.critical(self, "فشل", msg)

    def approve_order(self):
        if not self.current_po_id:
            return

        success, msg = self.po_dao.update_po_status(self.current_po_id, "approved", self.user_id)
        if success:
            QMessageBox.information(self, "نجاح الاعتماد", msg)
            self._ensure_filter_shows_status("approved")
            self._reselect_current_order()
        else:
            QMessageBox.critical(self, "فشل الاعتماد", msg)

    def cancel_order(self):
        if not self.current_po_id:
            return

        reply = QMessageBox.question(
            self,
            "تأكيد الإلغاء",
            "هل أنت متأكد من إلغاء أمر الشراء؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success, msg = self.po_dao.update_po_status(self.current_po_id, "cancelled", self.user_id)
        if success:
            QMessageBox.information(self, "تم الإلغاء", msg)
            self._ensure_filter_shows_status("cancelled")
            self._reselect_current_order()
        else:
            QMessageBox.critical(self, "فشل", msg)

    def delete_draft(self):
        if not self.current_po_id:
            return

        reply = QMessageBox.question(
            self,
            "تأكيد الحذف",
            "هل أنت متأكد من الحذف النهائي لهذه المسودة؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success, msg = self.po_dao.delete_draft(self.current_po_id, self.user_id)
        if success:
            QMessageBox.information(self, "تم الحذف", msg)
            self.load_orders()
            self.clear_form()
        else:
            QMessageBox.critical(self, "فشل", msg)