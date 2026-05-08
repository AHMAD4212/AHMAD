"""
مهمة الملف:
واجهة إدارية مستقلة لإدارة المواد الخطرة.

الطبقة:
طبقة العرض

ملاحظات معمارية:
- هذه الواجهة لا تعدّل مخطط قاعدة البيانات إطلاقاً، بل تعمل فوق البنية الحالية فقط.
- تعتمد على الملف: models/hazardous_materials_dao.py
- هذه الصفحة تجعل المتطلب 28 واضحاً كمتطلب مستقل عبر:
  1) عرض الأصناف الخطرة
  2) عرض دفعات المواد الخطرة
  3) عرض سجل الإتلاف الخطر
  4) عرض ملخص تشغيلي سريع
- جميع النصوص والتعليقات داخل هذا الملف باللغة العربية فقط.
- الواجهة مصممة لتتحمل القاعدة الفارغة بدون أخطاء.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QLineEdit, QMessageBox, QComboBox,
    QDateEdit, QCheckBox, QScrollArea,
    QFrame, QSizePolicy, QGraphicsDropShadowEffect, QPlainTextEdit
)

from models.hazardous_materials_dao import HazardousMaterialsDAO

logger = logging.getLogger(__name__)


class SummaryCard(QFrame):
    """
    بطاقة موجزة لعرض رقم/مؤشر داخل أعلى الصفحة.
    """

    def __init__(self, title: str, value: str = "0", hint: str = ""):
        super().__init__()
        self.setObjectName("summaryCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(132)
        self.setMaximumHeight(132)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("summaryCardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignCenter)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("summaryCardValue")
        self.value_label.setAlignment(Qt.AlignCenter)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("summaryCardHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)

    def set_value(self, value: Any):
        self.value_label.setText("" if value is None else str(value))

    def set_hint(self, hint: str):
        self.hint_label.setText(hint or "")


class HazardousMaterialsPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()

        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")
        self.username = self.session.get("username")

        self.dao = HazardousMaterialsDAO()

        self.summary_cards: Dict[str, SummaryCard] = {}
        self._summary_cards_order: List[SummaryCard] = []

        self._medicines_cache: List[Dict[str, Any]] = []
        self._batches_cache: List[Dict[str, Any]] = []
        self._disposal_log_cache: List[Dict[str, Any]] = []

        self._apply_styles()
        self.init_ui()
        self.load_initial_data()

    # ==========================================
    # دعم التزامن الحي مع الجلسة
    # ==========================================
    def set_session_context(self, session_data: Dict[str, Any]):
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")
        self.username = self.session.get("username")

    def update_session_context(self, session_data: Dict[str, Any]):
        self.set_session_context(session_data)

    def refresh_session_context(self):
        return

    # ==========================================
    # التنسيق العام
    # ==========================================
    def _apply_styles(self):
        self.setObjectName("hazardousMaterialsPage")
        self.setLayoutDirection(Qt.RightToLeft)

        self.setStyleSheet("""
            QWidget#hazardousMaterialsPage {
                background-color: #F4F7FB;
                font-family: "Times New Roman";
                color: #243B53;
            }

            QFrame#heroCard,
            QFrame#surfaceCard,
            QFrame#summaryCard {
                background-color: white;
                border: 1px solid #DCE6F0;
                border-radius: 18px;
            }

            QLabel#pageTitle {
                font-size: 31px;
                font-weight: bold;
                color: #102A43;
                padding: 0;
            }

            QLabel#pageSubtitle {
                font-size: 15px;
                color: #6B7A8C;
                padding-top: 2px;
            }

            QLabel#sectionTitle {
                font-size: 17px;
                font-weight: bold;
                color: #0F4C81;
            }

            QLabel#sectionHint {
                color: #6B7A8C;
                font-size: 13px;
                font-style: italic;
            }

            QLabel#summaryCardTitle {
                font-size: 14px;
                font-weight: bold;
                color: #486581;
            }

            QLabel#summaryCardValue {
                font-size: 29px;
                font-weight: bold;
                color: #0F4C81;
            }

            QLabel#summaryCardHint {
                font-size: 12px;
                color: #829AB1;
            }

            QTabWidget::pane {
                border: 1px solid #D9E2EC;
                background: white;
                border-radius: 16px;
                top: -1px;
            }

            QTabBar::tab {
                background: #EEF3F8;
                color: #334E68;
                border: 1px solid #D9E2EC;
                padding: 11px 20px;
                margin-left: 4px;
                min-width: 165px;
                font-size: 14px;
                font-weight: bold;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }

            QTabBar::tab:selected {
                background: white;
                color: #0F4C81;
                border-bottom: 1px solid white;
            }

            QTabBar::tab:hover {
                background: #E6EEF7;
            }

            QLineEdit, QComboBox, QDateEdit, QPlainTextEdit {
                background-color: #FCFDFE;
                border: 1px solid #C9D6E2;
                border-radius: 10px;
                padding: 9px 10px;
                color: #243B53;
                font-size: 14px;
                min-height: 26px;
            }

            QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {
                border: 1px solid #3B82F6;
                background-color: white;
            }

            QPushButton {
                background-color: #EEF3F8;
                color: #1F2D3D;
                border: 1px solid #D3DCE6;
                border-radius: 10px;
                padding: 9px 16px;
                font-size: 14px;
                font-weight: bold;
                min-height: 18px;
            }

            QPushButton:hover {
                background-color: #E3ECF5;
            }

            QPushButton#primaryButton {
                background-color: #0F4C81;
                color: white;
                border: 1px solid #0F4C81;
            }

            QPushButton#primaryButton:hover {
                background-color: #0C3E68;
            }

            QPushButton#successButton {
                background-color: #198754;
                color: white;
                border: 1px solid #198754;
            }

            QPushButton#successButton:hover {
                background-color: #157347;
            }

            QPushButton#dangerButton {
                background-color: #C0392B;
                color: white;
                border: 1px solid #C0392B;
            }

            QPushButton#dangerButton:hover {
                background-color: #A93226;
            }

            QPushButton#warningButton {
                background-color: #D97706;
                color: white;
                border: 1px solid #D97706;
            }

            QPushButton#warningButton:hover {
                background-color: #B45309;
            }

            QPushButton#mutedButton {
                background-color: #64748B;
                color: white;
                border: 1px solid #64748B;
            }

            QPushButton#mutedButton:hover {
                background-color: #475569;
            }

            QCheckBox {
                spacing: 8px;
                font-size: 14px;
                color: #243B53;
                font-weight: bold;
            }

            QTableWidget {
                background-color: white;
                alternate-background-color: #F8FBFF;
                gridline-color: #E6EDF5;
                border: 1px solid #DCE6F0;
                border-radius: 12px;
                font-size: 14px;
                color: #243B53;
                selection-background-color: #DCEEFF;
                selection-color: #102A43;
            }

            QHeaderView::section {
                background-color: #EAF2F9;
                color: #1F3A56;
                border: none;
                border-bottom: 1px solid #D7E3EF;
                padding: 10px 6px;
                font-size: 14px;
                font-weight: bold;
            }

            QScrollArea {
                border: none;
                background: transparent;
            }

            QScrollBar:vertical {
                background: #F1F5F9;
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical {
                background: #B8C7D9;
                min-height: 30px;
                border-radius: 5px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar:horizontal {
                background: #F1F5F9;
                height: 10px;
                margin: 0px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal {
                background: #B8C7D9;
                min-width: 30px;
                border-radius: 5px;
            }

            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    def _apply_soft_shadow(self, widget: QWidget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(15, 23, 42, 16))
        widget.setGraphicsEffect(shadow)

    def _make_card_frame(self, object_name: str = "surfaceCard") -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        self._apply_soft_shadow(frame)
        return frame

    def _style_button(self, button: QPushButton, role: str = "default"):
        role_map = {
            "primary": "primaryButton",
            "success": "successButton",
            "danger": "dangerButton",
            "warning": "warningButton",
            "muted": "mutedButton"
        }
        button.setObjectName(role_map.get(role, ""))
        button.setCursor(Qt.PointingHandCursor)

    def _make_scrollable_tab(self, content_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content_widget)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return scroll

    def _add_tab(self, content_widget: QWidget, title: str):
        self.tabs.addTab(self._make_scrollable_tab(content_widget), title)

    def _configure_table(self, table: QTableWidget, headers: List[str]):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setShowGrid(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setMinimumHeight(340)

        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)

        for i in range(len(headers)):
            if i == 0:
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)

    def _set_center_item(self, table: QTableWidget, row: int, col: int, value: Any, raw_value: Any = None):
        text = "" if value is None else str(value)
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setToolTip(text)
        if raw_value is not None:
            item.setData(Qt.UserRole, raw_value)
        table.setItem(row, col, item)

    def _create_detail_view(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setMinimumHeight(230)

        font = QFont("Consolas")
        font.setPointSize(10)
        editor.setFont(font)

        editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0B1220;
                color: #D8E4F0;
                border: 1px solid #24364A;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        return editor

    def _show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)

    def _show_info(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def _normalize_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _safe_int(self, value: Any, field_name: str, required: bool = False) -> Optional[int]:
        text = str(value).strip() if value is not None else ""
        if not text:
            if required:
                raise ValueError(f"{field_name} حقل إلزامي.")
            return None

        try:
            parsed = int(text)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون عدداً موجباً.")
        return parsed

    def _safe_non_negative_int(self, value: Any, field_name: str, default: Optional[int] = None) -> Optional[int]:
        text = str(value).strip() if value is not None else ""
        if not text:
            return default

        try:
            parsed = int(text)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

        if parsed < 0:
            raise ValueError(f"{field_name} لا يجوز أن يكون سالباً.")
        return parsed

    def _pretty_dict(self, data: Dict[str, Any]) -> str:
        try:
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(data)

    def _set_detail_text(self, editor: QPlainTextEdit, data: Dict[str, Any]):
        editor.setPlainText(self._pretty_dict(data))

    def _clear_layout_items(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.setParent(None)
            elif child_layout is not None:
                self._clear_layout_items(child_layout)

    def _summary_columns(self) -> int:
        width = max(self.width(), 700)

        if width >= 1180:
            return 4
        if width >= 880:
            return 3
        if width >= 620:
            return 2
        return 1

    # ==========================================
    # إنشاء الواجهة
    # ==========================================
    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.page_content = QWidget()
        main_layout = QVBoxLayout(self.page_content)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        header_card = self._make_card_frame("heroCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(6)

        title = QLabel("إدارة المواد الخطرة")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "واجهة تشغيلية مستقلة لمراقبة الأصناف الخطرة، دفعاتها، الصلاحية، وسجل الإتلاف البيئي المرتبط بها."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        main_layout.addWidget(header_card)

        actions_card = self._make_card_frame("surfaceCard")
        actions_layout = QHBoxLayout(actions_card)
        actions_layout.setContentsMargins(14, 12, 14, 12)
        actions_layout.setSpacing(8)

        actions_title = QLabel("إجراءات سريعة")
        actions_title.setObjectName("sectionTitle")

        self.btn_refresh_all = QPushButton("تحديث كامل")
        self._style_button(self.btn_refresh_all, "primary")
        self.btn_refresh_all.clicked.connect(self.load_initial_data)

        self.btn_show_low_stock = QPushButton("عرض منخفض المخزون")
        self._style_button(self.btn_show_low_stock, "warning")
        self.btn_show_low_stock.clicked.connect(lambda: self.apply_external_filter("low_stock"))

        self.btn_show_expired_batches = QPushButton("عرض الدفعات المنتهية")
        self._style_button(self.btn_show_expired_batches, "danger")
        self.btn_show_expired_batches.clicked.connect(lambda: self.apply_external_filter("expired_batches"))

        self.btn_show_disposal_log = QPushButton("عرض سجل الإتلاف")
        self._style_button(self.btn_show_disposal_log, "muted")
        self.btn_show_disposal_log.clicked.connect(lambda: self.apply_external_filter("hazardous_disposals"))

        actions_layout.addWidget(actions_title)
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_refresh_all)
        actions_layout.addWidget(self.btn_show_low_stock)
        actions_layout.addWidget(self.btn_show_expired_batches)
        actions_layout.addWidget(self.btn_show_disposal_log)

        main_layout.addWidget(actions_card)

        self._build_summary_section(main_layout)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)

        self._init_medicines_tab()
        self._init_batches_tab()
        self._init_disposal_log_tab()

        main_layout.addWidget(self.tabs)

        main_layout.addStretch()

        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll.setWidget(self.page_content)

        outer_layout.addWidget(self.page_scroll)

        self._reflow_summary_cards()

    def _build_summary_section(self, parent_layout: QVBoxLayout):
        self.summary_section_card = self._make_card_frame("surfaceCard")
        root = QVBoxLayout(self.summary_section_card)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("الملخص التشغيلي للمواد الخطرة")
        title.setObjectName("sectionTitle")

        hint = QLabel("هذه المؤشرات تُحدَّث مباشرة من القاعدة الحالية وتظهر كلها بوضوح داخل نفس القسم دون قص أو تداخل.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)

        self.summary_cards_host = QWidget()
        self.summary_cards_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.summary_cards_grid = QGridLayout(self.summary_cards_host)
        self.summary_cards_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_cards_grid.setHorizontalSpacing(16)
        self.summary_cards_grid.setVerticalSpacing(16)

        cards_meta = [
            ("total_hazardous_medicines", "إجمالي الأصناف الخطرة", "عدد الأدوية الموسومة كمواد خطرة"),
            ("low_stock_count", "منخفضة المخزون", "الأصناف التي وصلت إلى حد التنبيه أو أقل"),
            ("out_of_stock_count", "نافدة المخزون", "الأصناف التي أصبحت كميتها صفراً"),
            ("total_live_batches", "الدفعات الحية", "الدفعات التي ما زالت تحمل كمية فعلية"),
            ("expired_batches_count", "دفعات منتهية", "دفعات خطرة منتهية وما زالت بكميات موجودة"),
            ("expiring_soon_batches_count", "قريبة الانتهاء", "دفعات ستنتهي ضمن النافذة المحددة"),
            ("disposal_events_count", "عمليات الإتلاف", "عدد سجلات الإتلاف الخطر المسجلة"),
            ("total_disposed_qty", "إجمالي الكمية المتلفة", "مجموع الكميات التي تم التخلص منها")
        ]

        self.summary_cards = {}
        self._summary_cards_order = []

        for key, title_text, hint_text in cards_meta:
            card = SummaryCard(title=title_text, value="0", hint=hint_text)
            self.summary_cards[key] = card
            self._summary_cards_order.append(card)

        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self.summary_cards_host)

        parent_layout.addWidget(self.summary_section_card)

    def _reflow_summary_cards(self):
        if not hasattr(self, "summary_cards_grid"):
            return

        self._clear_layout_items(self.summary_cards_grid)

        cols = self._summary_columns()
        spacing = self.summary_cards_grid.verticalSpacing()
        margins = self.summary_cards_grid.contentsMargins()
        card_height = 132

        row_count = (len(self._summary_cards_order) + cols - 1) // cols

        for idx, card in enumerate(self._summary_cards_order):
            row = idx // cols
            col = idx % cols
            self.summary_cards_grid.addWidget(card, row, col)

        for col in range(cols):
            self.summary_cards_grid.setColumnStretch(col, 1)

        total_height = (
            row_count * card_height
            + max(0, row_count - 1) * spacing
            + margins.top()
            + margins.bottom()
        )

        self.summary_cards_host.setMinimumHeight(total_height)
        self.summary_cards_host.setMaximumHeight(total_height)
        self.summary_cards_host.updateGeometry()
        self.summary_section_card.updateGeometry()

    # ==========================================
    # تبويب الأصناف الخطرة
    # ==========================================
    def _init_medicines_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        filter_card = self._make_card_frame("surfaceCard")
        filter_root = QVBoxLayout(filter_card)
        filter_root.setContentsMargins(14, 14, 14, 14)
        filter_root.setSpacing(10)

        filter_title = QLabel("مرشحات الأصناف الخطرة")
        filter_title.setObjectName("sectionTitle")

        filter_form = QGridLayout()
        filter_form.setContentsMargins(0, 0, 0, 0)
        filter_form.setHorizontalSpacing(14)
        filter_form.setVerticalSpacing(10)

        self.med_search_input = QLineEdit()
        self.med_search_input.setPlaceholderText("ابحث باسم الدواء أو الباركود أو المادة الفعالة أو فئة الخطورة")

        self.med_supplier_id_input = QLineEdit()
        self.med_supplier_id_input.setPlaceholderText("اختياري")

        self.med_low_stock_only = QCheckBox("إظهار منخفضة المخزون فقط")
        self.med_out_of_stock_only = QCheckBox("إظهار نافدة المخزون فقط")

        self.med_sort_combo = QComboBox()
        self.med_sort_combo.addItem("الاسم", "name")
        self.med_sort_combo.addItem("الكمية", "quantity")
        self.med_sort_combo.addItem("أقرب انتهاء", "nearest_expiry")
        self.med_sort_combo.addItem("فئة الخطورة", "hazard_class")
        self.med_sort_combo.addItem("المورد", "supplier")

        filter_form.addWidget(QLabel("البحث"), 0, 0)
        filter_form.addWidget(self.med_search_input, 0, 1, 1, 3)
        filter_form.addWidget(QLabel("معرف المورد"), 1, 0)
        filter_form.addWidget(self.med_supplier_id_input, 1, 1)
        filter_form.addWidget(QLabel("الترتيب"), 1, 2)
        filter_form.addWidget(self.med_sort_combo, 1, 3)
        filter_form.addWidget(self.med_low_stock_only, 2, 1)
        filter_form.addWidget(self.med_out_of_stock_only, 2, 2)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self.btn_med_load = QPushButton("تحميل الأصناف")
        self._style_button(self.btn_med_load, "primary")
        self.btn_med_load.clicked.connect(self.load_hazardous_medicines_table)

        self.btn_med_reset = QPushButton("إعادة الضبط")
        self._style_button(self.btn_med_reset, "muted")
        self.btn_med_reset.clicked.connect(self.reset_medicines_filters)

        self.btn_med_open_batches = QPushButton("عرض دفعات الصنف المحدد")
        self._style_button(self.btn_med_open_batches, "success")
        self.btn_med_open_batches.clicked.connect(self.open_batches_for_selected_medicine)

        btn_row.addWidget(self.btn_med_load)
        btn_row.addWidget(self.btn_med_reset)
        btn_row.addWidget(self.btn_med_open_batches)
        btn_row.addStretch()

        filter_root.addWidget(filter_title)
        filter_root.addLayout(filter_form)
        filter_root.addLayout(btn_row)

        self.medicines_table = QTableWidget()
        self._configure_table(
            self.medicines_table,
            [
                "ID", "الدواء", "المادة الفعالة", "الشكل/التركيز", "المورد",
                "الكمية", "حد التنبيه", "حالة المخزون", "أقرب انتهاء",
                "دفعات نشطة", "دفعات منتهية", "فئة الخطورة"
            ]
        )
        self.medicines_table.itemSelectionChanged.connect(self.on_medicine_selected)

        detail_card = self._make_card_frame("surfaceCard")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(8)

        detail_title = QLabel("تفاصيل الصنف الخطر المحدد")
        detail_title.setObjectName("sectionTitle")

        self.med_details_view = self._create_detail_view()

        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.med_details_view)

        layout.addWidget(filter_card)
        layout.addWidget(self.medicines_table, stretch=1)
        layout.addWidget(detail_card)

        self._add_tab(tab_content, "الأصناف الخطرة")

    # ==========================================
    # تبويب الدفعات
    # ==========================================
    def _init_batches_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        filter_card = self._make_card_frame("surfaceCard")
        filter_root = QVBoxLayout(filter_card)
        filter_root.setContentsMargins(14, 14, 14, 14)
        filter_root.setSpacing(10)

        filter_title = QLabel("مرشحات دفعات المواد الخطرة")
        filter_title.setObjectName("sectionTitle")

        filter_form = QGridLayout()
        filter_form.setContentsMargins(0, 0, 0, 0)
        filter_form.setHorizontalSpacing(14)
        filter_form.setVerticalSpacing(10)

        self.batch_search_input = QLineEdit()
        self.batch_search_input.setPlaceholderText("ابحث باسم الدواء أو رقم التشغيلة أو الباركود")

        self.batch_medicine_id_input = QLineEdit()
        self.batch_medicine_id_input.setPlaceholderText("اختياري")

        self.batch_status_combo = QComboBox()
        self.batch_status_combo.addItem("الكل", None)
        self.batch_status_combo.addItem("نشطة", "active")
        self.batch_status_combo.addItem("منتهية", "expired")
        self.batch_status_combo.addItem("مستنفدة", "depleted")
        self.batch_status_combo.addItem("مسحوبة", "recalled")

        self.batch_expired_only = QCheckBox("إظهار المنتهي فقط")
        self.batch_include_zero_qty = QCheckBox("تضمين الدفعات ذات الكمية الصفرية")

        self.batch_expiring_days_input = QLineEdit()
        self.batch_expiring_days_input.setPlaceholderText("مثال: 30")

        self.batch_sort_combo = QComboBox()
        self.batch_sort_combo.addItem("تاريخ الانتهاء", "expiry_date")
        self.batch_sort_combo.addItem("اسم الدواء", "medicine_name")
        self.batch_sort_combo.addItem("الكمية", "quantity")
        self.batch_sort_combo.addItem("الحالة", "status")

        filter_form.addWidget(QLabel("البحث"), 0, 0)
        filter_form.addWidget(self.batch_search_input, 0, 1, 1, 3)
        filter_form.addWidget(QLabel("معرف الدواء"), 1, 0)
        filter_form.addWidget(self.batch_medicine_id_input, 1, 1)
        filter_form.addWidget(QLabel("حالة الدفعة"), 1, 2)
        filter_form.addWidget(self.batch_status_combo, 1, 3)
        filter_form.addWidget(QLabel("نافذة القرب من الانتهاء (بالأيام)"), 2, 0)
        filter_form.addWidget(self.batch_expiring_days_input, 2, 1)
        filter_form.addWidget(QLabel("الترتيب"), 2, 2)
        filter_form.addWidget(self.batch_sort_combo, 2, 3)
        filter_form.addWidget(self.batch_expired_only, 3, 1)
        filter_form.addWidget(self.batch_include_zero_qty, 3, 2)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self.btn_batch_load = QPushButton("تحميل الدفعات")
        self._style_button(self.btn_batch_load, "primary")
        self.btn_batch_load.clicked.connect(self.load_hazardous_batches_table)

        self.btn_batch_reset = QPushButton("إعادة الضبط")
        self._style_button(self.btn_batch_reset, "muted")
        self.btn_batch_reset.clicked.connect(self.reset_batches_filters)

        self.btn_batch_open_disposals = QPushButton("عرض إتلاف الصنف المحدد")
        self._style_button(self.btn_batch_open_disposals, "warning")
        self.btn_batch_open_disposals.clicked.connect(self.open_disposals_for_selected_batch)

        btn_row.addWidget(self.btn_batch_load)
        btn_row.addWidget(self.btn_batch_reset)
        btn_row.addWidget(self.btn_batch_open_disposals)
        btn_row.addStretch()

        filter_root.addWidget(filter_title)
        filter_root.addLayout(filter_form)
        filter_root.addLayout(btn_row)

        self.batches_table = QTableWidget()
        self._configure_table(
            self.batches_table,
            [
                "معرف الدفعة", "الدواء", "التشغيلة", "تاريخ الانتهاء",
                "الأيام المتبقية", "الكمية", "الحالة", "حالة الصلاحية",
                "فئة الخطورة", "المورد"
            ]
        )
        self.batches_table.itemSelectionChanged.connect(self.on_batch_selected)

        detail_card = self._make_card_frame("surfaceCard")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(8)

        detail_title = QLabel("تفاصيل الدفعة المحددة")
        detail_title.setObjectName("sectionTitle")

        self.batch_details_view = self._create_detail_view()

        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.batch_details_view)

        layout.addWidget(filter_card)
        layout.addWidget(self.batches_table, stretch=1)
        layout.addWidget(detail_card)

        self._add_tab(tab_content, "دفعات المواد الخطرة")

    # ==========================================
    # تبويب سجل الإتلاف
    # ==========================================
    def _init_disposal_log_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        filter_card = self._make_card_frame("surfaceCard")
        filter_root = QVBoxLayout(filter_card)
        filter_root.setContentsMargins(14, 14, 14, 14)
        filter_root.setSpacing(10)

        filter_title = QLabel("مرشحات سجل الإتلاف الخطر")
        filter_title.setObjectName("sectionTitle")

        filter_form = QGridLayout()
        filter_form.setContentsMargins(0, 0, 0, 0)
        filter_form.setHorizontalSpacing(14)
        filter_form.setVerticalSpacing(10)

        self.disp_search_input = QLineEdit()
        self.disp_search_input.setPlaceholderText("ابحث باسم الدواء أو رقم التشغيلة أو طريقة الإتلاف أو الجهة المستلمة")

        self.disp_medicine_id_input = QLineEdit()
        self.disp_medicine_id_input.setPlaceholderText("اختياري")

        self.disp_manifest_input = QLineEdit()
        self.disp_manifest_input.setPlaceholderText("اختياري")

        self.disp_enable_start_date = QCheckBox("تفعيل تاريخ البداية")
        self.disp_start_date = QDateEdit()
        self.disp_start_date.setCalendarPopup(True)
        self.disp_start_date.setDate(QDate.currentDate().addMonths(-1))

        self.disp_enable_end_date = QCheckBox("تفعيل تاريخ النهاية")
        self.disp_end_date = QDateEdit()
        self.disp_end_date.setCalendarPopup(True)
        self.disp_end_date.setDate(QDate.currentDate())

        filter_form.addWidget(QLabel("البحث"), 0, 0)
        filter_form.addWidget(self.disp_search_input, 0, 1, 1, 3)
        filter_form.addWidget(QLabel("معرف الدواء"), 1, 0)
        filter_form.addWidget(self.disp_medicine_id_input, 1, 1)
        filter_form.addWidget(QLabel("رقم المستند/البيان"), 1, 2)
        filter_form.addWidget(self.disp_manifest_input, 1, 3)
        filter_form.addWidget(self.disp_enable_start_date, 2, 0)
        filter_form.addWidget(self.disp_start_date, 2, 1)
        filter_form.addWidget(self.disp_enable_end_date, 2, 2)
        filter_form.addWidget(self.disp_end_date, 2, 3)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self.btn_disp_load = QPushButton("تحميل السجل")
        self._style_button(self.btn_disp_load, "primary")
        self.btn_disp_load.clicked.connect(self.load_hazardous_disposal_log_table)

        self.btn_disp_reset = QPushButton("إعادة الضبط")
        self._style_button(self.btn_disp_reset, "muted")
        self.btn_disp_reset.clicked.connect(self.reset_disposal_log_filters)

        btn_row.addWidget(self.btn_disp_load)
        btn_row.addWidget(self.btn_disp_reset)
        btn_row.addStretch()

        filter_root.addWidget(filter_title)
        filter_root.addLayout(filter_form)
        filter_root.addLayout(btn_row)

        self.disposal_log_table = QTableWidget()
        self._configure_table(
            self.disposal_log_table,
            [
                "ID", "تاريخ الإتلاف", "الدواء", "التشغيلة", "الكمية",
                "طريقة الإتلاف", "الجهة المستلمة", "البيان/المستند", "بواسطة"
            ]
        )
        self.disposal_log_table.itemSelectionChanged.connect(self.on_disposal_log_selected)

        detail_card = self._make_card_frame("surfaceCard")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(8)

        detail_title = QLabel("تفاصيل سجل الإتلاف المحدد")
        detail_title.setObjectName("sectionTitle")

        self.disposal_details_view = self._create_detail_view()

        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.disposal_details_view)

        layout.addWidget(filter_card)
        layout.addWidget(self.disposal_log_table, stretch=1)
        layout.addWidget(detail_card)

        self._add_tab(tab_content, "سجل الإتلاف الخطر")

    # ==========================================
    # التحميل الأولي
    # ==========================================
    def load_initial_data(self):
        self.load_summary()
        self.load_hazardous_medicines_table()
        self.load_hazardous_batches_table()
        self.load_hazardous_disposal_log_table()

    def load_summary(self):
        try:
            summary = self.dao.get_hazardous_dashboard_summary(expiring_within_days=30)

            for key, card in self.summary_cards.items():
                card.set_value(summary.get(key, 0))

            self.summary_cards["expiring_soon_batches_count"].set_hint(
                f"دفعات ستنتهي خلال {summary.get('expiring_within_days', 30)} يوماً"
            )

        except Exception:
            logger.exception("فشل تحميل ملخص المواد الخطرة.")
            for card in self.summary_cards.values():
                card.set_value("0")

    # ==========================================
    # تحميل جدول الأصناف الخطرة
    # ==========================================
    def load_hazardous_medicines_table(self):
        try:
            supplier_id = self._safe_int(self.med_supplier_id_input.text(), "معرف المورد", required=False)

            rows = self.dao.get_all_hazardous_medicines(
                search_term=self._normalize_text(self.med_search_input.text()),
                low_stock_only=self.med_low_stock_only.isChecked(),
                out_of_stock_only=self.med_out_of_stock_only.isChecked(),
                supplier_id=supplier_id,
                sort_by=self.med_sort_combo.currentData()
            )

            self._medicines_cache = rows if isinstance(rows, list) else []
            self.medicines_table.setRowCount(0)

            for row_idx, row in enumerate(self._medicines_cache):
                self.medicines_table.insertRow(row_idx)

                stock_state_raw = str(row.get("stock_state") or "")
                stock_state = {
                    "normal": "طبيعي",
                    "low_stock": "منخفض",
                    "out_of_stock": "نافد"
                }.get(stock_state_raw, stock_state_raw)

                display_strength = row.get("display_strength") or "-"

                values = [
                    row.get("id"),
                    row.get("name"),
                    row.get("active_ingredient"),
                    display_strength,
                    row.get("supplier_name"),
                    row.get("system_quantity"),
                    row.get("min_stock_alert"),
                    stock_state,
                    row.get("nearest_expiry_date"),
                    row.get("active_batches_count"),
                    row.get("expired_batches_count"),
                    row.get("hazard_class")
                ]

                for col_idx, value in enumerate(values):
                    self._set_center_item(self.medicines_table, row_idx, col_idx, value)

                    item = self.medicines_table.item(row_idx, col_idx)
                    if item and stock_state_raw == "out_of_stock":
                        item.setForeground(QColor("#C0392B"))
                    elif item and stock_state_raw == "low_stock":
                        item.setForeground(QColor("#D97706"))

            self.med_details_view.clear()

        except Exception as e:
            logger.exception("فشل تحميل جدول الأصناف الخطرة.")
            self._show_error("خطأ", str(e))

    def on_medicine_selected(self):
        row = self.medicines_table.currentRow()
        if row < 0 or row >= len(self._medicines_cache):
            return

        data = self._medicines_cache[row]
        self._set_detail_text(self.med_details_view, data)

    def reset_medicines_filters(self):
        self.med_search_input.clear()
        self.med_supplier_id_input.clear()
        self.med_low_stock_only.setChecked(False)
        self.med_out_of_stock_only.setChecked(False)
        self.med_sort_combo.setCurrentIndex(0)
        self.load_hazardous_medicines_table()

    def open_batches_for_selected_medicine(self):
        row = self.medicines_table.currentRow()
        if row < 0 or row >= len(self._medicines_cache):
            self._show_error("تنبيه", "الرجاء تحديد صنف خطر أولاً.")
            return

        data = self._medicines_cache[row]
        self.batch_medicine_id_input.setText(str(data.get("id") or ""))
        self.tabs.setCurrentIndex(1)
        self.load_hazardous_batches_table()

    # ==========================================
    # تحميل جدول الدفعات
    # ==========================================
    def load_hazardous_batches_table(self):
        try:
            medicine_id = self._safe_int(self.batch_medicine_id_input.text(), "معرف الدواء", required=False)
            expiring_days = self._safe_non_negative_int(
                self.batch_expiring_days_input.text(),
                "عدد الأيام",
                default=None
            )

            rows = self.dao.get_hazardous_batches(
                search_term=self._normalize_text(self.batch_search_input.text()),
                medicine_id=medicine_id,
                batch_status=self.batch_status_combo.currentData(),
                expired_only=self.batch_expired_only.isChecked(),
                expiring_within_days=expiring_days,
                include_zero_qty=self.batch_include_zero_qty.isChecked(),
                sort_by=self.batch_sort_combo.currentData()
            )

            self._batches_cache = rows if isinstance(rows, list) else []
            self.batches_table.setRowCount(0)

            batch_status_map = {
                "active": "نشطة",
                "expired": "منتهية",
                "depleted": "مستنفدة",
                "recalled": "مسحوبة"
            }

            expiry_state_map = {
                "expired": "منتهية",
                "expiring_soon": "قريبة الانتهاء",
                "valid": "صالحة"
            }

            for row_idx, row in enumerate(self._batches_cache):
                self.batches_table.insertRow(row_idx)

                batch_status = batch_status_map.get(str(row.get("status") or ""), row.get("status"))
                expiry_state_raw = str(row.get("expiry_state") or "")
                expiry_state = expiry_state_map.get(expiry_state_raw, expiry_state_raw)

                values = [
                    row.get("batch_id"),
                    row.get("medicine_name"),
                    row.get("batch_number"),
                    row.get("expiry_date"),
                    row.get("days_to_expiry"),
                    row.get("quantity"),
                    batch_status,
                    expiry_state,
                    row.get("hazard_class"),
                    row.get("supplier_name")
                ]

                for col_idx, value in enumerate(values):
                    self._set_center_item(self.batches_table, row_idx, col_idx, value)

                    item = self.batches_table.item(row_idx, col_idx)
                    if item and expiry_state_raw == "expired":
                        item.setForeground(QColor("#C0392B"))
                    elif item and expiry_state_raw == "expiring_soon":
                        item.setForeground(QColor("#D97706"))

            self.batch_details_view.clear()

        except Exception as e:
            logger.exception("فشل تحميل جدول دفعات المواد الخطرة.")
            self._show_error("خطأ", str(e))

    def on_batch_selected(self):
        row = self.batches_table.currentRow()
        if row < 0 or row >= len(self._batches_cache):
            return

        data = self._batches_cache[row]
        self._set_detail_text(self.batch_details_view, data)

    def reset_batches_filters(self):
        self.batch_search_input.clear()
        self.batch_medicine_id_input.clear()
        self.batch_status_combo.setCurrentIndex(0)
        self.batch_expired_only.setChecked(False)
        self.batch_include_zero_qty.setChecked(False)
        self.batch_expiring_days_input.clear()
        self.batch_sort_combo.setCurrentIndex(0)
        self.load_hazardous_batches_table()

    def open_disposals_for_selected_batch(self):
        row = self.batches_table.currentRow()
        if row < 0 or row >= len(self._batches_cache):
            self._show_error("تنبيه", "الرجاء تحديد دفعة أولاً.")
            return

        data = self._batches_cache[row]
        self.disp_medicine_id_input.setText(str(data.get("medicine_id") or ""))
        self.tabs.setCurrentIndex(2)
        self.load_hazardous_disposal_log_table()

    # ==========================================
    # تحميل سجل الإتلاف
    # ==========================================
    def load_hazardous_disposal_log_table(self):
        try:
            medicine_id = self._safe_int(self.disp_medicine_id_input.text(), "معرف الدواء", required=False)

            start_date = None
            end_date = None

            if self.disp_enable_start_date.isChecked():
                start_date = self.disp_start_date.date().toString("yyyy-MM-dd")

            if self.disp_enable_end_date.isChecked():
                end_date = self.disp_end_date.date().toString("yyyy-MM-dd")

            rows = self.dao.get_hazardous_disposal_log(
                search_term=self._normalize_text(self.disp_search_input.text()),
                medicine_id=medicine_id,
                start_date=start_date,
                end_date=end_date,
                manifest_number=self._normalize_text(self.disp_manifest_input.text())
            )

            self._disposal_log_cache = rows if isinstance(rows, list) else []
            self.disposal_log_table.setRowCount(0)

            for row_idx, row in enumerate(self._disposal_log_cache):
                self.disposal_log_table.insertRow(row_idx)

                values = [
                    row.get("id"),
                    row.get("disposal_date") or row.get("logged_at"),
                    row.get("medicine_name"),
                    row.get("batch_number"),
                    row.get("quantity"),
                    row.get("disposal_method"),
                    row.get("receiver_entity"),
                    row.get("manifest_number"),
                    row.get("username")
                ]

                for col_idx, value in enumerate(values):
                    self._set_center_item(self.disposal_log_table, row_idx, col_idx, value)

            self.disposal_details_view.clear()

        except Exception as e:
            logger.exception("فشل تحميل سجل الإتلاف الخطر.")
            self._show_error("خطأ", str(e))

    def on_disposal_log_selected(self):
        row = self.disposal_log_table.currentRow()
        if row < 0 or row >= len(self._disposal_log_cache):
            return

        data = self._disposal_log_cache[row]
        self._set_detail_text(self.disposal_details_view, data)

    def reset_disposal_log_filters(self):
        self.disp_search_input.clear()
        self.disp_medicine_id_input.clear()
        self.disp_manifest_input.clear()
        self.disp_enable_start_date.setChecked(False)
        self.disp_enable_end_date.setChecked(False)
        self.disp_start_date.setDate(QDate.currentDate().addMonths(-1))
        self.disp_end_date.setDate(QDate.currentDate())
        self.load_hazardous_disposal_log_table()

    # ==========================================
    # فلاتر خارجية مستقبلية
    # ==========================================
    def apply_external_filter(self, filter_type: Optional[str]):
        filter_type = (filter_type or "").strip().lower()

        if not filter_type:
            self.tabs.setCurrentIndex(0)
            self.reset_medicines_filters()
            self.reset_batches_filters()
            self.reset_disposal_log_filters()
            return

        if filter_type == "low_stock":
            self.tabs.setCurrentIndex(0)
            self.reset_medicines_filters()
            self.med_low_stock_only.setChecked(True)
            self.load_hazardous_medicines_table()
            return

        if filter_type == "out_of_stock":
            self.tabs.setCurrentIndex(0)
            self.reset_medicines_filters()
            self.med_out_of_stock_only.setChecked(True)
            self.load_hazardous_medicines_table()
            return

        if filter_type == "expired_batches":
            self.tabs.setCurrentIndex(1)
            self.reset_batches_filters()
            self.batch_expired_only.setChecked(True)
            self.load_hazardous_batches_table()
            return

        if filter_type == "expiring_soon":
            self.tabs.setCurrentIndex(1)
            self.reset_batches_filters()
            self.batch_expiring_days_input.setText("30")
            self.load_hazardous_batches_table()
            return

        if filter_type == "hazardous_disposals":
            self.tabs.setCurrentIndex(2)
            self.reset_disposal_log_filters()
            self.load_hazardous_disposal_log_table()
            return

    # ==========================================
    # الاستجابة مع تغيير الحجم
    # ==========================================
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_summary_cards()