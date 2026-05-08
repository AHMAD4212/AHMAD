"""
مهمة الملف:
واجهة إدارية مستقلة لإدارة التأمين الصحي الداخلي.

الطبقة:
طبقة العرض

ملاحظات معمارية:
- هذه الواجهة مستقلة عن شاشة نقطة البيع، لمنع خلط منطق التأمين بمسار البيع المباشر.
- تجمع إدارة مزودي التأمين، الوثائق، المطالبات، والتحصيلات في شاشة واحدة منظمة.
- لا تحتوي أي أوامر SQL مباشرة؛ جميع العمليات تمر عبر DAO أو طبقة الخدمة.
- تم تصميم الواجهة لتكون مرنة مع تغيير حجم النافذة، مع دعم التمرير عند الحاجة.
- جميع النصوص والتعليقات داخل هذا الملف باللغة العربية فقط.
"""

import json
import inspect
import logging
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QDate, QRegularExpression
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QSyntaxHighlighter
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QLineEdit, QTextEdit, QMessageBox, QComboBox, QDateEdit, QCheckBox,
    QGroupBox, QFormLayout, QPlainTextEdit, QScrollArea,
    QFrame, QSizePolicy, QGridLayout, QGraphicsDropShadowEffect,
    QDoubleSpinBox, QAbstractSpinBox
)

from models.insurance_providers_dao import InsuranceProvidersDAO
from models.customer_insurance_policies_dao import CustomerInsurancePoliciesDAO
from services.insurance_workflow_service import InsuranceWorkflowService

logger = logging.getLogger(__name__)


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    """
    ملوّن صياغة بسيط لعرض JSON بشكل أوضح داخل حقول العرض.
    """

    def __init__(self, document):
        super().__init__(document)
        self.rules = []

        def _format(color: str, bold: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            return fmt

        self.rules.append(
            (QRegularExpression(r'"([^"\\]|\\.)*"\s*(?=:)'), _format("#93C5FD", True))
        )
        self.rules.append(
            (QRegularExpression(r'"([^"\\]|\\.)*"'), _format("#86EFAC"))
        )
        self.rules.append(
            (QRegularExpression(r'\b(true|false|null)\b'), _format("#FCA5A5", True))
        )
        self.rules.append(
            (QRegularExpression(r'\b-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?\b'), _format("#FCD34D"))
        )
        self.rules.append(
            (QRegularExpression(r'[\{\}\[\]:,]'), _format("#CBD5E1", True))
        )

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class InsuranceManagementPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()

        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.providers_dao = InsuranceProvidersDAO()
        self.policies_dao = CustomerInsurancePoliciesDAO()
        self.workflow = InsuranceWorkflowService()

        self.selected_provider_id = None
        self.selected_policy_id = None
        self.selected_claim_id = None
        self.selected_claim_item_row = None

        self._provider_cache: List[Dict[str, Any]] = []
        self._policy_cache: List[Dict[str, Any]] = []
        self._claim_cache: List[Dict[str, Any]] = []
        self._collectible_claims_cache: List[Dict[str, Any]] = []
        self._claim_items_buffer: List[Dict[str, Any]] = []

        self._apply_styles()
        self.init_ui()
        self.load_initial_data()

    # ==========================================
    # تهيئة المظهر العام
    # ==========================================
    def _apply_styles(self):
        self.setObjectName("insuranceManagementPage")
        self.setLayoutDirection(Qt.RightToLeft)

        self.setStyleSheet("""
            QWidget#insuranceManagementPage {
                background-color: #F4F7FB;
                font-family: "Times New Roman";
                color: #243B53;
            }

            QLabel#pageTitle {
                font-size: 30px;
                font-weight: bold;
                color: #102A43;
                padding: 4px 0;
            }

            QLabel#pageSubtitle {
                font-size: 15px;
                color: #6B7A8C;
                padding-bottom: 6px;
            }

            QLabel#metricTitle {
                font-size: 13px;
                color: #6B7A8C;
                font-weight: bold;
            }

            QLabel#metricValue {
                font-size: 22px;
                color: #0F4C81;
                font-weight: bold;
            }

            QFrame#heroCard {
                background-color: white;
                border: 1px solid #E3E8EF;
                border-radius: 20px;
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
                padding: 11px 18px;
                margin-left: 4px;
                min-width: 135px;
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

            QGroupBox {
                background-color: white;
                border: 1px solid #DEE6EF;
                border-radius: 16px;
                margin-top: 14px;
                padding: 16px 14px 14px 14px;
                font-size: 15px;
                font-weight: bold;
                color: #243B53;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                right: 12px;
                padding: 0 8px;
                color: #0F4C81;
                background-color: white;
            }

            QLineEdit, QComboBox, QDateEdit, QTextEdit, QPlainTextEdit, QDoubleSpinBox {
                background-color: #FCFDFE;
                border: 1px solid #C9D6E2;
                border-radius: 10px;
                padding: 8px 10px;
                color: #243B53;
                font-size: 14px;
                min-height: 24px;
            }

            QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
            QTextEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #3B82F6;
                background-color: white;
            }

            QComboBox {
                padding-left: 24px;
            }

            QComboBox::drop-down {
                border: none;
                width: 22px;
            }

            QTextEdit, QPlainTextEdit {
                padding-top: 10px;
                padding-bottom: 10px;
            }

            QCheckBox {
                spacing: 8px;
                font-size: 14px;
                color: #243B53;
                font-weight: bold;
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

            QLabel#sectionHint {
                color: #6B7A8C;
                font-size: 13px;
                font-style: italic;
            }

            QLabel#sectionTitle {
                color: #0F4C81;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 4px;
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

    def _style_button(self, button: QPushButton, role: str = "default"):
        button.setCursor(Qt.PointingHandCursor)
        role_map = {
            "primary": "primaryButton",
            "success": "successButton",
            "danger": "dangerButton",
            "warning": "warningButton",
            "muted": "mutedButton"
        }
        button.setObjectName(role_map.get(role, ""))

    def _apply_soft_shadow(self, widget: QWidget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 28))
        widget.setGraphicsEffect(shadow)

    def _make_scrollable_tab(self, content_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content_widget)
        return scroll

    def _add_tab(self, content_widget: QWidget, title: str, scrollable: bool = True):
        if scrollable:
            self.tabs.addTab(self._make_scrollable_tab(content_widget), title)
        else:
            self.tabs.addTab(content_widget, title)

    def _make_card_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("heroCard")
        self._apply_soft_shadow(frame)
        return frame

    def _create_metric_card(self, title: str, value: str = "0.00") -> QFrame:
        card = self._make_card_frame()
        card.setMinimumHeight(88)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        title_label.setAlignment(Qt.AlignCenter)

        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        card.value_label = value_label
        return card

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
        table.setMinimumHeight(260)

        header = table.horizontalHeader()
        header.setStretchLastSection(False)
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

    def _create_json_viewer(self, min_height: int = 220) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLayoutDirection(Qt.LeftToRight)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setMinimumHeight(min_height)

        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)
        mono_font.setPointSize(10)
        editor.setFont(mono_font)
        editor.setTabStopDistance(32)

        editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0B1220;
                color: #D8E4F0;
                border: 1px solid #24364A;
                border-radius: 12px;
                padding: 10px;
                selection-background-color: #1D4ED8;
            }
        """)

        editor._json_highlighter = JsonSyntaxHighlighter(editor.document())
        return editor

    def _configure_decimal_spin(
        self,
        spin: QDoubleSpinBox,
        decimals: int = 2,
        minimum: float = 0.0,
        maximum: float = 999999999.99,
        step: float = 1.0,
        default_value: float = 0.0
    ):
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(default_value)
        spin.setAlignment(Qt.AlignCenter)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setMinimumHeight(38)

    def _set_json_content(self, editor: QPlainTextEdit, data: Any):
        editor.setPlainText(self._pretty_json(data))

    def _show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)

    def _show_info(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def _confirm(self, title: str, message: str) -> bool:
        reply = QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

    def _pretty_json(self, data: Any) -> str:
        try:
            if isinstance(data, str):
                stripped = data.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    parsed = json.loads(stripped)
                    return json.dumps(parsed, ensure_ascii=False, indent=2)
                return data
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return str(data)

    def _safe_set_date(self, widget: QDateEdit, value: Any):
        if not value:
            return

        qdate = QDate.fromString(str(value), "yyyy-MM-dd")
        if qdate.isValid():
            widget.setDate(qdate)

    def _update_responsive_layouts(self):
        return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layouts()

    # ==========================================
    # مساعدات عامة للنداء والتحقق
    # ==========================================
    def _unwrap_result(self, result: Any) -> Tuple[bool, Any]:
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            return result
        return True, result

    def _filter_kwargs_for_callable(self, func, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        sig = inspect.signature(func)

        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return kwargs

        accepted = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in accepted}

    def _call_first_available(self, target: Any, method_names: List[str], *args, **kwargs) -> Any:
        last_error = None

        for method_name in method_names:
            method = getattr(target, method_name, None)
            if not callable(method):
                continue

            try:
                filtered_kwargs = self._filter_kwargs_for_callable(method, kwargs)
                return method(*args, **filtered_kwargs)
            except TypeError as exc:
                last_error = exc
                continue

        joined = ", ".join(method_names)
        if last_error:
            raise AttributeError(f"تعذر العثور على دالة مناسبة من بين: {joined}. آخر خطأ: {last_error}")
        raise AttributeError(f"لم يتم العثور على أي دالة صالحة من بين: {joined}")

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

    def _safe_float(self, value: Any, field_name: str, required: bool = False) -> Optional[float]:
        text = str(value).strip() if value is not None else ""
        if not text:
            if required:
                raise ValueError(f"{field_name} حقل إلزامي.")
            return None

        try:
            return float(text)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون رقماً صالحاً.")

    def _safe_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    # ==========================================
    # خرائط العرض العربية
    # ==========================================
    def _provider_status_label(self, is_active: Any) -> str:
        return "نشط ✅" if int(is_active or 0) == 1 else "معطل ❌"

    def _policy_status_label(self, status: Any) -> str:
        mapping = {
            "active": "نشطة",
            "suspended": "معلقة",
            "expired": "منتهية",
            "cancelled": "ملغاة"
        }
        return mapping.get(str(status or "").lower(), str(status or "-"))

    def _claim_status_label(self, status: Any) -> str:
        mapping = {
            "draft": "مسودة",
            "submitted": "مرسلة",
            "approved": "معتمدة",
            "partially_approved": "اعتماد جزئي",
            "rejected": "مرفوضة",
            "collected": "محصلة",
            "cancelled": "ملغاة"
        }
        return mapping.get(str(status or "").lower(), str(status or "-"))

    def _payment_method_label(self, method: Any) -> str:
        mapping = {
            "bank_transfer": "تحويل بنكي",
            "cash": "نقدي",
            "check": "شيك",
            "other": "أخرى"
        }
        return mapping.get(str(method or "").lower(), str(method or "-"))

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        hero = self._make_card_frame()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 18, 22, 18)
        hero_layout.setSpacing(4)

        title = QLabel("إدارة التأمين الصحي الداخلي")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "واجهة إدارية مستقلة لإدارة مزودي التأمين، الوثائق التأمينية، المطالبات، والتحصيلات المالية."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        main_layout.addWidget(hero)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)

        self._init_providers_tab()
        self._init_policies_tab()
        self._init_claims_tab()
        self._init_collections_tab()

        main_layout.addWidget(self.tabs, 1)
        self._update_responsive_layouts()

    # ==========================================
    # تبويب مزودي التأمين
    # ==========================================
    def _init_providers_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        form_group = QGroupBox("بيانات مزود التأمين")
        form_layout = QFormLayout(form_group)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(12)
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.provider_name_input = QLineEdit()
        self.provider_name_input.setPlaceholderText("أدخل اسم شركة التأمين")

        self.provider_code_input = QLineEdit()
        self.provider_code_input.setPlaceholderText("رمز مختصر اختياري")

        self.provider_contact_input = QLineEdit()
        self.provider_contact_input.setPlaceholderText("اسم جهة/شخص التواصل")

        self.provider_phone_input = QLineEdit()
        self.provider_phone_input.setPlaceholderText("رقم الهاتف")

        self.provider_email_input = QLineEdit()
        self.provider_email_input.setPlaceholderText("البريد الإلكتروني")

        self.provider_address_input = QLineEdit()
        self.provider_address_input.setPlaceholderText("العنوان")

        self.provider_default_coverage_input = QLineEdit()
        self.provider_default_coverage_input.setText("80")
        self.provider_default_coverage_input.setPlaceholderText("مثال: 80")

        self.provider_notes_input = QTextEdit()
        self.provider_notes_input.setPlaceholderText("ملاحظات داخلية عن المزود")
        self.provider_notes_input.setMinimumHeight(90)

        form_layout.addRow("اسم المزود *", self.provider_name_input)
        form_layout.addRow("الكود", self.provider_code_input)
        form_layout.addRow("جهة التواصل", self.provider_contact_input)
        form_layout.addRow("الهاتف", self.provider_phone_input)
        form_layout.addRow("البريد الإلكتروني", self.provider_email_input)
        form_layout.addRow("العنوان", self.provider_address_input)
        form_layout.addRow("نسبة التغطية الافتراضية %", self.provider_default_coverage_input)
        form_layout.addRow("ملاحظات", self.provider_notes_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_provider_create = QPushButton("إضافة مزود")
        self._style_button(self.btn_provider_create, "primary")

        self.btn_provider_update = QPushButton("تحديث المحدد")
        self._style_button(self.btn_provider_update, "success")

        self.btn_provider_activate = QPushButton("تفعيل")
        self._style_button(self.btn_provider_activate, "success")

        self.btn_provider_deactivate = QPushButton("تعطيل")
        self._style_button(self.btn_provider_deactivate, "danger")

        self.btn_provider_refresh = QPushButton("تحديث الجدول")
        self._style_button(self.btn_provider_refresh, "muted")

        self.btn_provider_create.clicked.connect(self.create_provider)
        self.btn_provider_update.clicked.connect(self.update_provider)
        self.btn_provider_activate.clicked.connect(lambda: self.change_provider_status(True))
        self.btn_provider_deactivate.clicked.connect(lambda: self.change_provider_status(False))
        self.btn_provider_refresh.clicked.connect(self.load_providers_table)

        btn_row.addWidget(self.btn_provider_create)
        btn_row.addWidget(self.btn_provider_update)
        btn_row.addWidget(self.btn_provider_activate)
        btn_row.addWidget(self.btn_provider_deactivate)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_provider_refresh)

        search_card = self._make_card_frame()
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(14, 12, 14, 12)
        search_layout.setSpacing(8)

        search_label = QLabel("البحث:")
        self.provider_search_input = QLineEdit()
        self.provider_search_input.setPlaceholderText("ابحث باسم الشركة أو الكود")
        self.btn_provider_search = QPushButton("تنفيذ البحث")
        self._style_button(self.btn_provider_search, "primary")
        self.btn_provider_search.clicked.connect(self.search_providers)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.provider_search_input, stretch=1)
        search_layout.addWidget(self.btn_provider_search)

        self.providers_table = QTableWidget()
        self._configure_table(
            self.providers_table,
            ["ID", "الاسم", "الكود", "جهة التواصل", "الهاتف", "البريد", "التغطية %", "الحالة"]
        )
        self.providers_table.itemSelectionChanged.connect(self.on_provider_selected)

        layout.addWidget(form_group)
        layout.addLayout(btn_row)
        layout.addWidget(search_card)
        layout.addWidget(self.providers_table, stretch=1)

        self._add_tab(tab_content, "مزودو التأمين", scrollable=True)

    # ==========================================
    # تبويب الوثائق
    # ==========================================
    def _init_policies_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        form_group = QGroupBox("بيانات الوثيقة التأمينية")
        form_layout = QFormLayout(form_group)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(12)
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.policy_customer_id_input = QLineEdit()
        self.policy_customer_id_input.setPlaceholderText("أدخل معرف العميل")

        self.policy_provider_combo = QComboBox()

        self.policy_number_input = QLineEdit()
        self.policy_number_input.setPlaceholderText("رقم الوثيقة")

        self.policy_member_number_input = QLineEdit()
        self.policy_member_number_input.setPlaceholderText("رقم العضوية أو الاشتراك")

        self.policy_default_coverage_input = QLineEdit()
        self.policy_default_coverage_input.setText("80")

        self.policy_patient_share_input = QLineEdit()
        self.policy_patient_share_input.setText("20")

        self.policy_limit_input = QLineEdit()
        self.policy_limit_input.setPlaceholderText("اتركه فارغاً إذا لم يوجد حد")

        self.policy_valid_from = QDateEdit()
        self.policy_valid_from.setCalendarPopup(True)
        self.policy_valid_from.setDate(QDate.currentDate())

        self.policy_valid_to = QDateEdit()
        self.policy_valid_to.setCalendarPopup(True)
        self.policy_valid_to.setDate(QDate.currentDate().addYears(1))

        self.policy_status_combo = QComboBox()
        self.policy_status_combo.addItem("نشطة", "active")
        self.policy_status_combo.addItem("معلقة", "suspended")
        self.policy_status_combo.addItem("منتهية", "expired")
        self.policy_status_combo.addItem("ملغاة", "cancelled")

        self.policy_is_default = QCheckBox("جعل هذه الوثيقة افتراضية للعميل")

        self.policy_notes_input = QTextEdit()
        self.policy_notes_input.setPlaceholderText("ملاحظات داخلية عن الوثيقة")
        self.policy_notes_input.setMinimumHeight(90)

        form_layout.addRow("معرف العميل *", self.policy_customer_id_input)
        form_layout.addRow("مزود التأمين *", self.policy_provider_combo)
        form_layout.addRow("رقم الوثيقة *", self.policy_number_input)
        form_layout.addRow("رقم العضوية", self.policy_member_number_input)
        form_layout.addRow("نسبة التغطية %", self.policy_default_coverage_input)
        form_layout.addRow("حصة المريض %", self.policy_patient_share_input)
        form_layout.addRow("حد التغطية", self.policy_limit_input)
        form_layout.addRow("صالح من", self.policy_valid_from)
        form_layout.addRow("صالح إلى", self.policy_valid_to)
        form_layout.addRow("الحالة", self.policy_status_combo)
        form_layout.addRow("", self.policy_is_default)
        form_layout.addRow("ملاحظات", self.policy_notes_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_policy_create = QPushButton("إضافة وثيقة")
        self._style_button(self.btn_policy_create, "primary")

        self.btn_policy_update = QPushButton("تحديث الوثيقة")
        self._style_button(self.btn_policy_update, "success")

        self.btn_policy_activate = QPushButton("تفعيل")
        self._style_button(self.btn_policy_activate, "success")

        self.btn_policy_suspend = QPushButton("تعليق")
        self._style_button(self.btn_policy_suspend, "warning")

        self.btn_policy_expire = QPushButton("إنهاء")
        self._style_button(self.btn_policy_expire, "warning")

        self.btn_policy_cancel = QPushButton("إلغاء")
        self._style_button(self.btn_policy_cancel, "danger")

        self.btn_policy_refresh = QPushButton("تحديث الجدول")
        self._style_button(self.btn_policy_refresh, "muted")

        self.btn_policy_create.clicked.connect(self.create_policy)
        self.btn_policy_update.clicked.connect(self.update_policy)
        self.btn_policy_activate.clicked.connect(lambda: self.change_policy_status("activate"))
        self.btn_policy_suspend.clicked.connect(lambda: self.change_policy_status("suspend"))
        self.btn_policy_expire.clicked.connect(lambda: self.change_policy_status("expire"))
        self.btn_policy_cancel.clicked.connect(lambda: self.change_policy_status("cancel"))
        self.btn_policy_refresh.clicked.connect(self.load_policies_table)

        btn_row.addWidget(self.btn_policy_create)
        btn_row.addWidget(self.btn_policy_update)
        btn_row.addWidget(self.btn_policy_activate)
        btn_row.addWidget(self.btn_policy_suspend)
        btn_row.addWidget(self.btn_policy_expire)
        btn_row.addWidget(self.btn_policy_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_policy_refresh)

        filter_card = self._make_card_frame()
        filter_layout = QHBoxLayout(filter_card)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setSpacing(8)

        self.policy_filter_customer_id_input = QLineEdit()
        self.policy_filter_customer_id_input.setPlaceholderText("فلترة بمعرف العميل")

        self.policy_filter_provider_combo = QComboBox()
        self.policy_filter_status_combo = QComboBox()
        self.policy_filter_status_combo.addItem("الكل", None)
        self.policy_filter_status_combo.addItem("نشطة", "active")
        self.policy_filter_status_combo.addItem("معلقة", "suspended")
        self.policy_filter_status_combo.addItem("منتهية", "expired")
        self.policy_filter_status_combo.addItem("ملغاة", "cancelled")

        self.btn_policy_filter = QPushButton("تطبيق الفلتر")
        self._style_button(self.btn_policy_filter, "primary")
        self.btn_policy_filter.clicked.connect(self.load_policies_table)

        filter_layout.addWidget(QLabel("العميل:"))
        filter_layout.addWidget(self.policy_filter_customer_id_input)
        filter_layout.addWidget(QLabel("المزود:"))
        filter_layout.addWidget(self.policy_filter_provider_combo)
        filter_layout.addWidget(QLabel("الحالة:"))
        filter_layout.addWidget(self.policy_filter_status_combo)
        filter_layout.addWidget(self.btn_policy_filter)

        self.policies_table = QTableWidget()
        self._configure_table(
            self.policies_table,
            [
                "ID", "العميل", "المزود", "رقم الوثيقة", "رقم العضوية",
                "التغطية %", "حصة المريض %", "حد التغطية", "من", "إلى", "افتراضية", "الحالة"
            ]
        )
        self.policies_table.itemSelectionChanged.connect(self.on_policy_selected)

        layout.addWidget(form_group)
        layout.addLayout(btn_row)
        layout.addWidget(filter_card)
        layout.addWidget(self.policies_table, stretch=1)

        self._add_tab(tab_content, "الوثائق", scrollable=True)

    # ==========================================
    # تبويب المطالبات
    # ==========================================
    def _init_claims_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        filter_card = self._make_card_frame()
        filter_layout = QHBoxLayout(filter_card)
        filter_layout.setContentsMargins(16, 14, 16, 14)
        filter_layout.setSpacing(10)

        filter_title = QLabel("فلترة سجل المطالبات")
        filter_title.setObjectName("sectionTitle")

        self.claim_filter_customer_id_input = QLineEdit()
        self.claim_filter_customer_id_input.setPlaceholderText("فلترة بمعرف العميل")

        self.btn_claim_apply_filter = QPushButton("تطبيق الفلتر")
        self._style_button(self.btn_claim_apply_filter, "primary")
        self.btn_claim_apply_filter.clicked.connect(self.load_claims_table)

        filter_layout.addWidget(filter_title)
        filter_layout.addStretch()
        filter_layout.addWidget(QLabel("العميل:"))
        filter_layout.addWidget(self.claim_filter_customer_id_input, 1)
        filter_layout.addWidget(self.btn_claim_apply_filter)

        table_group = QGroupBox("سجل المطالبات")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(10)

        self.claims_table = QTableWidget()
        self._configure_table(
            self.claims_table,
            [
                "ID", "رقم المطالبة", "المزود", "العميل", "الحالة",
                "تاريخ الخدمة", "الإجمالي", "حصة المؤمن", "المعتمد", "المحصل"
            ]
        )
        self.claims_table.setMinimumHeight(280)
        self.claims_table.itemSelectionChanged.connect(self.on_claim_selected)

        table_actions = QHBoxLayout()
        table_actions.setContentsMargins(0, 0, 0, 0)
        table_actions.setSpacing(8)

        self.btn_claim_refresh = QPushButton("تحديث السجل")
        self._style_button(self.btn_claim_refresh, "muted")
        self.btn_claim_refresh.clicked.connect(self.load_claims_table)

        self.btn_claim_snapshot = QPushButton("عرض اللقطة الكاملة")
        self._style_button(self.btn_claim_snapshot, "muted")
        self.btn_claim_snapshot.clicked.connect(self.show_claim_snapshot)

        table_actions.addStretch()
        table_actions.addWidget(self.btn_claim_snapshot)
        table_actions.addWidget(self.btn_claim_refresh)

        table_layout.addWidget(self.claims_table)
        table_layout.addLayout(table_actions)

        details_group = QGroupBox("اللقطة الكاملة للمطالبة المحددة")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(12, 12, 12, 12)

        self.claim_details_view = self._create_json_viewer(min_height=240)
        details_layout.addWidget(self.claim_details_view)

        create_group = QGroupBox("إنشاء مطالبة تأمينية")
        create_group_layout = QVBoxLayout(create_group)
        create_group_layout.setContentsMargins(12, 12, 12, 12)
        create_group_layout.setSpacing(14)

        basic_group = QGroupBox("البيانات الأساسية للمطالبة")
        basic_form = QFormLayout(basic_group)
        basic_form.setLabelAlignment(Qt.AlignRight)
        basic_form.setFormAlignment(Qt.AlignTop)
        basic_form.setHorizontalSpacing(16)
        basic_form.setVerticalSpacing(12)
        basic_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.claim_customer_id_input = QLineEdit()
        self.claim_customer_id_input.setPlaceholderText("معرف العميل")

        self.claim_provider_combo = QComboBox()

        self.claim_policy_id_input = QLineEdit()
        self.claim_policy_id_input.setPlaceholderText("اختياري")

        self.claim_sale_id_input = QLineEdit()
        self.claim_sale_id_input.setPlaceholderText("اختياري")

        self.claim_prescription_id_input = QLineEdit()
        self.claim_prescription_id_input.setPlaceholderText("اختياري")

        self.claim_service_date = QDateEdit()
        self.claim_service_date.setCalendarPopup(True)
        self.claim_service_date.setDate(QDate.currentDate())

        self.claim_external_number_input = QLineEdit()
        self.claim_external_number_input.setPlaceholderText("مرجع خارجي لدى شركة التأمين")

        self.claim_submission_notes_input = QTextEdit()
        self.claim_submission_notes_input.setPlaceholderText("ملاحظات الإرسال أو وصف مختصر للمطالبة")
        self.claim_submission_notes_input.setMinimumHeight(90)
        self.claim_submission_notes_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.claim_auto_submit_checkbox = QCheckBox("إرسال المطالبة مباشرة بعد الإنشاء")

        basic_form.addRow("معرف العميل *", self.claim_customer_id_input)
        basic_form.addRow("مزود التأمين", self.claim_provider_combo)
        basic_form.addRow("معرف الوثيقة", self.claim_policy_id_input)
        basic_form.addRow("معرف البيع", self.claim_sale_id_input)
        basic_form.addRow("معرف الوصفة", self.claim_prescription_id_input)
        basic_form.addRow("تاريخ الخدمة", self.claim_service_date)
        basic_form.addRow("المرجع الخارجي", self.claim_external_number_input)
        basic_form.addRow("ملاحظات الإرسال", self.claim_submission_notes_input)
        basic_form.addRow("", self.claim_auto_submit_checkbox)

        items_group = QGroupBox("عناصر المطالبة")
        items_layout = QVBoxLayout(items_group)
        items_layout.setContentsMargins(12, 12, 12, 12)
        items_layout.setSpacing(12)

        item_hint = QLabel(
            "أضف البنود سطراً بسطر. لا حاجة لإدخال JSON. النظام سيحوّل البنود داخلياً إلى البنية المناسبة لطبقة الخدمة."
        )
        item_hint.setObjectName("sectionHint")
        item_hint.setWordWrap(True)

        item_form_frame = self._make_card_frame()
        item_form_layout = QGridLayout(item_form_frame)
        item_form_layout.setContentsMargins(14, 14, 14, 14)
        item_form_layout.setHorizontalSpacing(12)
        item_form_layout.setVerticalSpacing(10)

        self.claim_item_sale_item_id_input = QLineEdit()
        self.claim_item_sale_item_id_input.setPlaceholderText("اختياري")

        self.claim_item_medicine_id_input = QLineEdit()
        self.claim_item_medicine_id_input.setPlaceholderText("اختياري")

        self.claim_item_quantity_input = QDoubleSpinBox()
        self._configure_decimal_spin(self.claim_item_quantity_input, decimals=2, minimum=0.01, step=1.0, default_value=1.0)

        self.claim_item_unit_price_input = QDoubleSpinBox()
        self._configure_decimal_spin(self.claim_item_unit_price_input, decimals=2, minimum=0.0, step=1.0, default_value=0.0)

        self.claim_item_gross_amount_input = QDoubleSpinBox()
        self._configure_decimal_spin(self.claim_item_gross_amount_input, decimals=2, minimum=0.0, step=1.0, default_value=0.0)

        self.claim_item_covered_amount_input = QDoubleSpinBox()
        self._configure_decimal_spin(self.claim_item_covered_amount_input, decimals=2, minimum=0.0, step=1.0, default_value=0.0)

        self.claim_item_patient_amount_input = QDoubleSpinBox()
        self._configure_decimal_spin(self.claim_item_patient_amount_input, decimals=2, minimum=0.0, step=1.0, default_value=0.0)

        item_form_layout.addWidget(QLabel("معرف بند البيع"), 0, 0)
        item_form_layout.addWidget(self.claim_item_sale_item_id_input, 0, 1)
        item_form_layout.addWidget(QLabel("معرف الدواء"), 0, 2)
        item_form_layout.addWidget(self.claim_item_medicine_id_input, 0, 3)

        item_form_layout.addWidget(QLabel("الكمية *"), 1, 0)
        item_form_layout.addWidget(self.claim_item_quantity_input, 1, 1)
        item_form_layout.addWidget(QLabel("سعر الوحدة"), 1, 2)
        item_form_layout.addWidget(self.claim_item_unit_price_input, 1, 3)

        item_form_layout.addWidget(QLabel("الإجمالي *"), 2, 0)
        item_form_layout.addWidget(self.claim_item_gross_amount_input, 2, 1)
        item_form_layout.addWidget(QLabel("حصة المؤمن *"), 2, 2)
        item_form_layout.addWidget(self.claim_item_covered_amount_input, 2, 3)

        item_form_layout.addWidget(QLabel("حصة المريض *"), 3, 0)
        item_form_layout.addWidget(self.claim_item_patient_amount_input, 3, 1)

        item_actions = QHBoxLayout()
        item_actions.setContentsMargins(0, 0, 0, 0)
        item_actions.setSpacing(8)

        self.btn_claim_item_add = QPushButton("إضافة بند")
        self._style_button(self.btn_claim_item_add, "primary")

        self.btn_claim_item_update = QPushButton("تحديث البند المحدد")
        self._style_button(self.btn_claim_item_update, "success")

        self.btn_claim_item_remove = QPushButton("حذف البند المحدد")
        self._style_button(self.btn_claim_item_remove, "danger")

        self.btn_claim_item_clear_inputs = QPushButton("تفريغ حقول البند")
        self._style_button(self.btn_claim_item_clear_inputs, "muted")

        self.btn_claim_items_clear_all = QPushButton("تفريغ جميع البنود")
        self._style_button(self.btn_claim_items_clear_all, "warning")

        self.btn_claim_item_add.clicked.connect(self.add_claim_item)
        self.btn_claim_item_update.clicked.connect(self.update_selected_claim_item)
        self.btn_claim_item_remove.clicked.connect(self.remove_selected_claim_item)
        self.btn_claim_item_clear_inputs.clicked.connect(self.clear_claim_item_inputs)
        self.btn_claim_items_clear_all.clicked.connect(self.clear_all_claim_items)

        item_actions.addWidget(self.btn_claim_item_add)
        item_actions.addWidget(self.btn_claim_item_update)
        item_actions.addWidget(self.btn_claim_item_remove)
        item_actions.addStretch()
        item_actions.addWidget(self.btn_claim_item_clear_inputs)
        item_actions.addWidget(self.btn_claim_items_clear_all)

        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(10)

        self.claim_items_count_card = self._create_metric_card("عدد البنود", "0")
        self.claim_items_gross_card = self._create_metric_card("إجمالي المطالبة", "0.00")
        self.claim_items_covered_card = self._create_metric_card("حصة المؤمن", "0.00")
        self.claim_items_patient_card = self._create_metric_card("حصة المريض", "0.00")

        metrics_row.addWidget(self.claim_items_count_card)
        metrics_row.addWidget(self.claim_items_gross_card)
        metrics_row.addWidget(self.claim_items_covered_card)
        metrics_row.addWidget(self.claim_items_patient_card)

        self.claim_items_table = QTableWidget()
        self._configure_table(
            self.claim_items_table,
            ["#", "معرف بند البيع", "معرف الدواء", "الكمية", "سعر الوحدة", "الإجمالي", "حصة المؤمن", "حصة المريض"]
        )
        self.claim_items_table.setMinimumHeight(240)
        self.claim_items_table.itemSelectionChanged.connect(self.on_claim_item_selected)

        items_layout.addWidget(item_hint)
        items_layout.addWidget(item_form_frame)
        items_layout.addLayout(item_actions)
        items_layout.addLayout(metrics_row)
        items_layout.addWidget(self.claim_items_table)

        create_actions = QHBoxLayout()
        create_actions.setContentsMargins(0, 0, 0, 0)
        create_actions.setSpacing(8)

        self.btn_claim_clear_form = QPushButton("تفريغ نموذج المطالبة")
        self._style_button(self.btn_claim_clear_form, "muted")

        self.btn_claim_create = QPushButton("إنشاء مطالبة")
        self._style_button(self.btn_claim_create, "primary")

        self.btn_claim_clear_form.clicked.connect(self.clear_claim_form)
        self.btn_claim_create.clicked.connect(self.create_claim)

        create_actions.addStretch()
        create_actions.addWidget(self.btn_claim_clear_form)
        create_actions.addWidget(self.btn_claim_create)

        create_group_layout.addWidget(basic_group)
        create_group_layout.addWidget(items_group)
        create_group_layout.addLayout(create_actions)

        manage_group = QGroupBox("إدارة المطالبة المحددة")
        manage_form = QFormLayout(manage_group)
        manage_form.setLabelAlignment(Qt.AlignRight)
        manage_form.setFormAlignment(Qt.AlignTop)
        manage_form.setHorizontalSpacing(16)
        manage_form.setVerticalSpacing(12)
        manage_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.claim_selected_id_label = QLabel("-")
        self.claim_selected_id_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #0F4C81;"
        )

        self.claim_approved_amount_input = QLineEdit()
        self.claim_approved_amount_input.setPlaceholderText("اتركه فارغاً لاستخدام القيمة الممررة من النواة")

        self.claim_decision_notes_input = QTextEdit()
        self.claim_decision_notes_input.setPlaceholderText("ملاحظات القرار")
        self.claim_decision_notes_input.setMinimumHeight(85)
        self.claim_decision_notes_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.claim_rejection_reason_input = QLineEdit()
        self.claim_rejection_reason_input.setPlaceholderText("سبب الرفض عند الحاجة")

        manage_form.addRow("المطالبة المحددة", self.claim_selected_id_label)
        manage_form.addRow("المبلغ المعتمد", self.claim_approved_amount_input)
        manage_form.addRow("ملاحظات القرار", self.claim_decision_notes_input)
        manage_form.addRow("سبب الرفض", self.claim_rejection_reason_input)

        manage_actions = QGridLayout()
        manage_actions.setContentsMargins(0, 0, 0, 0)
        manage_actions.setHorizontalSpacing(8)
        manage_actions.setVerticalSpacing(8)

        self.btn_claim_submit = QPushButton("إرسال المحددة")
        self._style_button(self.btn_claim_submit, "primary")

        self.btn_claim_approve = QPushButton("اعتماد المحددة")
        self._style_button(self.btn_claim_approve, "success")

        self.btn_claim_reject = QPushButton("رفض المحددة")
        self._style_button(self.btn_claim_reject, "danger")

        self.btn_claim_cancel = QPushButton("إلغاء المحددة")
        self._style_button(self.btn_claim_cancel, "warning")

        self.btn_claim_submit.clicked.connect(self.submit_selected_claim)
        self.btn_claim_approve.clicked.connect(self.approve_selected_claim)
        self.btn_claim_reject.clicked.connect(self.reject_selected_claim)
        self.btn_claim_cancel.clicked.connect(self.cancel_selected_claim)

        manage_actions.addWidget(self.btn_claim_submit, 0, 0)
        manage_actions.addWidget(self.btn_claim_approve, 0, 1)
        manage_actions.addWidget(self.btn_claim_reject, 1, 0)
        manage_actions.addWidget(self.btn_claim_cancel, 1, 1)
        manage_actions.setColumnStretch(2, 1)

        layout.addWidget(filter_card)
        layout.addWidget(table_group)
        layout.addWidget(details_group)
        layout.addWidget(create_group)
        layout.addWidget(manage_group)
        layout.addLayout(manage_actions)
        layout.addStretch()

        self._add_tab(tab_content, "المطالبات", scrollable=True)

    # ==========================================
    # تبويب التحصيلات
    # ==========================================
    def _init_collections_tab(self):
        tab_content = QWidget()
        layout = QVBoxLayout(tab_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        top_group = QGroupBox("تسجيل تحصيل تأميني")
        top_form = QFormLayout(top_group)
        top_form.setLabelAlignment(Qt.AlignRight)
        top_form.setFormAlignment(Qt.AlignTop)
        top_form.setHorizontalSpacing(16)
        top_form.setVerticalSpacing(12)
        top_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.collection_claim_id_input = QLineEdit()
        self.collection_claim_id_input.setPlaceholderText("أدخل معرف المطالبة")

        self.collection_amount_input = QLineEdit()
        self.collection_amount_input.setPlaceholderText("قيمة المبلغ المحصل")

        self.collection_payment_method_combo = QComboBox()
        self.collection_payment_method_combo.addItem("تحويل بنكي", "bank_transfer")
        self.collection_payment_method_combo.addItem("نقدي", "cash")
        self.collection_payment_method_combo.addItem("شيك", "check")
        self.collection_payment_method_combo.addItem("أخرى", "other")

        self.collection_shift_id_input = QLineEdit()
        self.collection_shift_id_input.setPlaceholderText("اختياري عند التحصيل غير النقدي")

        self.collection_reference_input = QLineEdit()
        self.collection_reference_input.setPlaceholderText("مرجع التحصيل أو إشعار البنك")

        self.collection_date = QDateEdit()
        self.collection_date.setCalendarPopup(True)
        self.collection_date.setDate(QDate.currentDate())

        self.collection_notes_input = QTextEdit()
        self.collection_notes_input.setPlaceholderText("ملاحظات إضافية")
        self.collection_notes_input.setMinimumHeight(90)
        self.collection_notes_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        top_form.addRow("معرف المطالبة *", self.collection_claim_id_input)
        top_form.addRow("المبلغ *", self.collection_amount_input)
        top_form.addRow("طريقة الدفع", self.collection_payment_method_combo)
        top_form.addRow("معرف الوردية", self.collection_shift_id_input)
        top_form.addRow("مرجع التحصيل", self.collection_reference_input)
        top_form.addRow("تاريخ التحصيل", self.collection_date)
        top_form.addRow("ملاحظات", self.collection_notes_input)

        top_actions = QHBoxLayout()
        top_actions.setContentsMargins(0, 0, 0, 0)
        top_actions.setSpacing(8)

        self.btn_collection_record = QPushButton("تسجيل التحصيل")
        self._style_button(self.btn_collection_record, "primary")

        self.btn_collection_load_summary = QPushButton("تحميل ملخص المطالبة")
        self._style_button(self.btn_collection_load_summary, "muted")

        self.btn_collection_refresh_claims = QPushButton("تحميل المطالبات القابلة للتحصيل")
        self._style_button(self.btn_collection_refresh_claims, "muted")

        self.btn_collection_record.clicked.connect(self.record_collection)
        self.btn_collection_load_summary.clicked.connect(self.load_collection_claim_snapshot)
        self.btn_collection_refresh_claims.clicked.connect(self.load_collectible_claims_table)

        top_actions.addStretch()
        top_actions.addWidget(self.btn_collection_refresh_claims)
        top_actions.addWidget(self.btn_collection_load_summary)
        top_actions.addWidget(self.btn_collection_record)

        claims_group = QGroupBox("المطالبات القابلة للتحصيل")
        claims_layout = QVBoxLayout(claims_group)
        claims_layout.setContentsMargins(12, 12, 12, 12)
        claims_layout.setSpacing(10)

        self.collectible_claims_table = QTableWidget()
        self._configure_table(
            self.collectible_claims_table,
            ["ID", "رقم المطالبة", "المزود", "العميل", "الحالة", "المعتمد", "المحصل", "المتبقي"]
        )
        self.collectible_claims_table.setMinimumHeight(260)
        self.collectible_claims_table.itemSelectionChanged.connect(self.on_collectible_claim_selected)

        claims_layout.addWidget(self.collectible_claims_table)

        summary_group = QGroupBox("ملخص المطالبة والتحصيل")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)

        self.collection_summary_view = self._create_json_viewer(min_height=240)
        summary_layout.addWidget(self.collection_summary_view)

        layout.addWidget(top_group)
        layout.addLayout(top_actions)
        layout.addWidget(claims_group)
        layout.addWidget(summary_group)
        layout.addStretch()

        self._add_tab(tab_content, "التحصيلات", scrollable=True)

    # ==========================================
    # التحميل الأولي
    # ==========================================
    def load_initial_data(self):
        self.load_providers_table()
        self.refresh_provider_combos()
        self.load_policies_table()
        self.load_claims_table()
        self.load_collectible_claims_table()
        self.refresh_claim_items_table()

    # ==========================================
    # عمليات مزودي التأمين
    # ==========================================
    def _provider_form_payload(self) -> Dict[str, Any]:
        return {
            "name": self._safe_text(self.provider_name_input.text()),
            "code": self._safe_text(self.provider_code_input.text()),
            "contact_person": self._safe_text(self.provider_contact_input.text()),
            "phone": self._safe_text(self.provider_phone_input.text()),
            "email": self._safe_text(self.provider_email_input.text()),
            "address": self._safe_text(self.provider_address_input.text()),
            "default_coverage_percent": self._safe_float(
                self.provider_default_coverage_input.text(),
                "نسبة التغطية الافتراضية",
                required=True
            ),
            "notes": self._safe_text(self.provider_notes_input.toPlainText())
        }

    def clear_provider_form(self):
        self.selected_provider_id = None
        self.provider_name_input.clear()
        self.provider_code_input.clear()
        self.provider_contact_input.clear()
        self.provider_phone_input.clear()
        self.provider_email_input.clear()
        self.provider_address_input.clear()
        self.provider_default_coverage_input.setText("80")
        self.provider_notes_input.clear()

    def create_provider(self):
        try:
            payload = self._provider_form_payload()
            if not payload["name"]:
                self._show_error("خطأ", "اسم مزود التأمين حقل إلزامي.")
                return

            result = self._call_first_available(
                self.providers_dao,
                ["create_provider", "create"],
                created_by_user_id=self.user_id,
                **payload
            )
            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تمت إضافة مزود التأمين بنجاح."
                self._show_info("نجاح", message)
                self.clear_provider_form()
                self.load_providers_table()
                self.refresh_provider_combos()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to create provider.")
            self._show_error("خطأ", str(e))

    def update_provider(self):
        if not self.selected_provider_id:
            self._show_error("تنبيه", "الرجاء تحديد مزود من الجدول أولاً.")
            return

        try:
            payload = self._provider_form_payload()
            if not payload["name"]:
                self._show_error("خطأ", "اسم مزود التأمين حقل إلزامي.")
                return

            result = self._call_first_available(
                self.providers_dao,
                ["update_provider", "update"],
                provider_id=self.selected_provider_id,
                updated_by_user_id=self.user_id,
                **payload
            )
            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تم تحديث مزود التأمين بنجاح."
                self._show_info("نجاح", message)
                self.load_providers_table()
                self.refresh_provider_combos()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to update provider.")
            self._show_error("خطأ", str(e))

    def change_provider_status(self, activate: bool):
        if not self.selected_provider_id:
            self._show_error("تنبيه", "الرجاء تحديد مزود من الجدول أولاً.")
            return

        try:
            if activate:
                result = self._call_first_available(
                    self.providers_dao,
                    ["activate_provider", "set_provider_active", "set_status"],
                    provider_id=self.selected_provider_id,
                    updated_by_user_id=self.user_id,
                    is_active=1,
                    new_status=1
                )
            else:
                result = self._call_first_available(
                    self.providers_dao,
                    ["deactivate_provider", "set_provider_inactive", "set_status"],
                    provider_id=self.selected_provider_id,
                    updated_by_user_id=self.user_id,
                    is_active=0,
                    new_status=0
                )

            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تم تحديث حالة المزود بنجاح."
                self._show_info("نجاح", message)
                self.load_providers_table()
                self.refresh_provider_combos()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to change provider status.")
            self._show_error("خطأ", str(e))

    def search_providers(self):
        keyword = self._safe_text(self.provider_search_input.text())
        try:
            if not keyword:
                self.load_providers_table()
                return

            result = self._call_first_available(
                self.providers_dao,
                ["search_providers", "search", "find_providers"],
                keyword=keyword
            )
            success, payload = self._unwrap_result(result)
            rows = payload if success and isinstance(payload, list) else []
            self.populate_providers_table(rows)

        except Exception as e:
            logger.exception("Failed to search providers.")
            self._show_error("خطأ", str(e))

    def load_providers_table(self):
        try:
            rows = self.workflow.get_active_providers(keyword=None)

            dao_result = self._call_first_available(
                self.providers_dao,
                ["get_all_providers", "list_providers", "get_providers"],
                active_only=False
            )
            success, payload = self._unwrap_result(dao_result)

            if success and isinstance(payload, list):
                rows = payload

            self.populate_providers_table(rows)

        except Exception as e:
            logger.exception("Failed to load providers table.")
            self._show_error("خطأ", str(e))

    def populate_providers_table(self, rows: List[Dict[str, Any]]):
        self._provider_cache = [r for r in rows if isinstance(r, dict)]
        self.providers_table.setRowCount(0)

        for row_idx, row in enumerate(self._provider_cache):
            self.providers_table.insertRow(row_idx)

            is_active = int(row.get("is_active", 1)) == 1
            values = [
                row.get("id"),
                row.get("name"),
                row.get("code"),
                row.get("contact_person"),
                row.get("phone"),
                row.get("email"),
                row.get("default_coverage_percent"),
                self._provider_status_label(is_active)
            ]

            for col_idx, value in enumerate(values):
                self._set_center_item(self.providers_table, row_idx, col_idx, value)

                item = self.providers_table.item(row_idx, col_idx)
                if item and not is_active:
                    item.setForeground(QColor("#7F8C8D"))

    def on_provider_selected(self):
        row = self.providers_table.currentRow()
        if row < 0 or row >= len(self._provider_cache):
            return

        data = self._provider_cache[row]
        self.selected_provider_id = data.get("id")

        self.provider_name_input.setText(str(data.get("name") or ""))
        self.provider_code_input.setText(str(data.get("code") or ""))
        self.provider_contact_input.setText(str(data.get("contact_person") or ""))
        self.provider_phone_input.setText(str(data.get("phone") or ""))
        self.provider_email_input.setText(str(data.get("email") or ""))
        self.provider_address_input.setText(str(data.get("address") or ""))
        self.provider_default_coverage_input.setText(str(data.get("default_coverage_percent") or "80"))
        self.provider_notes_input.setPlainText(str(data.get("notes") or ""))

    def refresh_provider_combos(self):
        providers = self.workflow.get_active_providers()

        combos = [
            self.policy_provider_combo,
            self.policy_filter_provider_combo,
            self.claim_provider_combo
        ]

        for combo in combos:
            combo.blockSignals(True)
            combo.clear()

        self.policy_provider_combo.addItem("اختر مزوداً...", None)
        self.claim_provider_combo.addItem("اختياري / استنتاج تلقائي", None)
        self.policy_filter_provider_combo.addItem("الكل", None)

        for provider in providers:
            display = f"{provider.get('name')} [{provider.get('id')}]"
            provider_id = provider.get("id")
            self.policy_provider_combo.addItem(display, provider_id)
            self.policy_filter_provider_combo.addItem(display, provider_id)
            self.claim_provider_combo.addItem(display, provider_id)

        for combo in combos:
            combo.blockSignals(False)

    # ==========================================
    # عمليات الوثائق
    # ==========================================
    def _policy_form_payload(self) -> Dict[str, Any]:
        customer_id = self._safe_int(self.policy_customer_id_input.text(), "معرف العميل", required=True)
        provider_id = self.policy_provider_combo.currentData()
        if not provider_id:
            raise ValueError("الرجاء اختيار مزود تأمين صالح.")

        return {
            "customer_id": customer_id,
            "provider_id": provider_id,
            "policy_number": self._safe_text(self.policy_number_input.text()),
            "member_number": self._safe_text(self.policy_member_number_input.text()),
            "default_coverage_percent": self._safe_float(
                self.policy_default_coverage_input.text(),
                "نسبة التغطية",
                required=True
            ),
            "default_patient_share_percent": self._safe_float(
                self.policy_patient_share_input.text(),
                "حصة المريض",
                required=True
            ),
            "coverage_limit_amount": self._safe_float(
                self.policy_limit_input.text(),
                "حد التغطية",
                required=False
            ),
            "valid_from": self.policy_valid_from.date().toString("yyyy-MM-dd"),
            "valid_to": self.policy_valid_to.date().toString("yyyy-MM-dd"),
            "status": self.policy_status_combo.currentData(),
            "is_default": 1 if self.policy_is_default.isChecked() else 0,
            "notes": self._safe_text(self.policy_notes_input.toPlainText())
        }

    def clear_policy_form(self):
        self.selected_policy_id = None
        self.policy_customer_id_input.clear()
        self.policy_provider_combo.setCurrentIndex(0)
        self.policy_number_input.clear()
        self.policy_member_number_input.clear()
        self.policy_default_coverage_input.setText("80")
        self.policy_patient_share_input.setText("20")
        self.policy_limit_input.clear()
        self.policy_valid_from.setDate(QDate.currentDate())
        self.policy_valid_to.setDate(QDate.currentDate().addYears(1))
        self.policy_status_combo.setCurrentIndex(0)
        self.policy_is_default.setChecked(False)
        self.policy_notes_input.clear()

    def create_policy(self):
        try:
            payload = self._policy_form_payload()
            if not payload["policy_number"]:
                self._show_error("خطأ", "رقم الوثيقة حقل إلزامي.")
                return

            result = self.policies_dao.create_policy(
                created_by_user_id=self.user_id,
                **payload
            )
            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تم إنشاء الوثيقة بنجاح."
                self._show_info("نجاح", message)
                self.clear_policy_form()
                self.load_policies_table()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to create policy.")
            self._show_error("خطأ", str(e))

    def update_policy(self):
        if not self.selected_policy_id:
            self._show_error("تنبيه", "الرجاء تحديد وثيقة من الجدول أولاً.")
            return

        try:
            payload = self._policy_form_payload()
            if not payload["policy_number"]:
                self._show_error("خطأ", "رقم الوثيقة حقل إلزامي.")
                return

            result = self.policies_dao.update_policy(
                policy_id=self.selected_policy_id,
                updated_by_user_id=self.user_id,
                **payload
            )
            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تم تحديث الوثيقة بنجاح."
                self._show_info("نجاح", message)
                self.load_policies_table()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to update policy.")
            self._show_error("خطأ", str(e))

    def change_policy_status(self, action_name: str):
        if not self.selected_policy_id:
            self._show_error("تنبيه", "الرجاء تحديد وثيقة من الجدول أولاً.")
            return

        method_map = {
            "activate": self.policies_dao.activate_policy,
            "suspend": self.policies_dao.suspend_policy,
            "expire": self.policies_dao.expire_policy,
            "cancel": self.policies_dao.cancel_policy
        }

        method = method_map.get(action_name)
        if not method:
            self._show_error("خطأ", "إجراء غير معروف.")
            return

        try:
            result = method(self.selected_policy_id, updated_by_user_id=self.user_id)
            success, msg = self._unwrap_result(result)

            if success:
                message = msg["message"] if isinstance(msg, dict) and "message" in msg else "تم تحديث حالة الوثيقة."
                self._show_info("نجاح", message)
                self.load_policies_table()
            else:
                self._show_error("فشل", str(msg))

        except Exception as e:
            logger.exception("Failed to change policy status.")
            self._show_error("خطأ", str(e))

    def load_policies_table(self):
        try:
            customer_id = self._safe_int(
                self.policy_filter_customer_id_input.text(),
                "معرف العميل",
                required=False
            )
            provider_id = self.policy_filter_provider_combo.currentData()
            status = self.policy_filter_status_combo.currentData()

            rows = self.policies_dao.get_all_policies(
                customer_id=customer_id,
                provider_id=provider_id,
                status=status
            )

            self.populate_policies_table(rows if isinstance(rows, list) else [])

        except Exception as e:
            logger.exception("Failed to load policies table.")
            self._show_error("خطأ", str(e))

    def populate_policies_table(self, rows: List[Dict[str, Any]]):
        self._policy_cache = [r for r in rows if isinstance(r, dict)]
        self.policies_table.setRowCount(0)

        for row_idx, row in enumerate(self._policy_cache):
            self.policies_table.insertRow(row_idx)

            values = [
                row.get("id"),
                row.get("customer_name") or row.get("customer_id"),
                row.get("provider_name") or row.get("provider_id"),
                row.get("policy_number"),
                row.get("member_number"),
                row.get("default_coverage_percent", row.get("coverage_percent")),
                row.get("default_patient_share_percent"),
                row.get("coverage_limit_amount"),
                row.get("valid_from", row.get("start_date")),
                row.get("valid_to", row.get("end_date")),
                "نعم" if int(row.get("is_default", 0)) == 1 else "لا",
                self._policy_status_label(row.get("status"))
            ]

            for col_idx, value in enumerate(values):
                self._set_center_item(self.policies_table, row_idx, col_idx, value)

    def on_policy_selected(self):
        row = self.policies_table.currentRow()
        if row < 0 or row >= len(self._policy_cache):
            return

        data = self._policy_cache[row]
        self.selected_policy_id = data.get("id")

        self.policy_customer_id_input.setText(str(data.get("customer_id") or ""))

        provider_id = data.get("provider_id")
        combo_index = self.policy_provider_combo.findData(provider_id)
        if combo_index >= 0:
            self.policy_provider_combo.setCurrentIndex(combo_index)

        self.policy_number_input.setText(str(data.get("policy_number") or ""))
        self.policy_member_number_input.setText(str(data.get("member_number") or ""))
        self.policy_default_coverage_input.setText(
            str(data.get("default_coverage_percent", data.get("coverage_percent", "80")))
        )
        self.policy_patient_share_input.setText(str(data.get("default_patient_share_percent") or "20"))
        self.policy_limit_input.setText("" if data.get("coverage_limit_amount") is None else str(data.get("coverage_limit_amount")))

        valid_from = data.get("valid_from", data.get("start_date"))
        valid_to = data.get("valid_to", data.get("end_date"))

        self._safe_set_date(self.policy_valid_from, valid_from)
        self._safe_set_date(self.policy_valid_to, valid_to)

        status = str(data.get("status") or "active")
        idx = self.policy_status_combo.findData(status)
        if idx >= 0:
            self.policy_status_combo.setCurrentIndex(idx)

        self.policy_is_default.setChecked(int(data.get("is_default", 0)) == 1)
        self.policy_notes_input.setPlainText(str(data.get("notes") or ""))

    # ==========================================
    # عمليات عناصر المطالبة
    # ==========================================
    def _round_money(self, value: float) -> float:
        return round(float(value), 2)

    def _claim_item_payload_from_form(self) -> Dict[str, Any]:
        sale_item_id = self._safe_int(self.claim_item_sale_item_id_input.text(), "معرف بند البيع", required=False)
        medicine_id = self._safe_int(self.claim_item_medicine_id_input.text(), "معرف الدواء", required=False)

        if sale_item_id is None and medicine_id is None:
            raise ValueError("يجب إدخال معرف بند البيع أو معرف الدواء على الأقل.")

        quantity = float(self.claim_item_quantity_input.value())
        unit_price = float(self.claim_item_unit_price_input.value())
        gross_amount = float(self.claim_item_gross_amount_input.value())
        covered_amount = float(self.claim_item_covered_amount_input.value())
        patient_amount = float(self.claim_item_patient_amount_input.value())

        if quantity <= 0:
            raise ValueError("الكمية يجب أن تكون أكبر من صفر.")

        if gross_amount <= 0:
            if quantity > 0 and unit_price > 0:
                gross_amount = self._round_money(quantity * unit_price)
                self.claim_item_gross_amount_input.setValue(gross_amount)
            else:
                raise ValueError("الإجمالي حقل إلزامي أو يجب توفير الكمية وسعر الوحدة لحسابه تلقائياً.")

        if unit_price <= 0 and quantity > 0 and gross_amount > 0:
            unit_price = self._round_money(gross_amount / quantity)
            self.claim_item_unit_price_input.setValue(unit_price)

        if covered_amount <= 0 and patient_amount > 0:
            covered_amount = self._round_money(gross_amount - patient_amount)
            self.claim_item_covered_amount_input.setValue(max(covered_amount, 0.0))
        elif patient_amount <= 0 and covered_amount > 0:
            patient_amount = self._round_money(gross_amount - covered_amount)
            self.claim_item_patient_amount_input.setValue(max(patient_amount, 0.0))

        covered_amount = self._round_money(covered_amount)
        patient_amount = self._round_money(patient_amount)
        gross_amount = self._round_money(gross_amount)
        unit_price = self._round_money(unit_price)

        if covered_amount < 0 or patient_amount < 0:
            raise ValueError("قيم التغطية أو حصة المريض لا يمكن أن تكون سالبة.")

        if abs((covered_amount + patient_amount) - gross_amount) > 0.01:
            raise ValueError("مجموع حصة المؤمن وحصة المريض يجب أن يساوي إجمالي البند.")

        payload = {
            "quantity": quantity,
            "unit_price": unit_price,
            "gross_amount": gross_amount,
            "covered_amount": covered_amount,
            "patient_amount": patient_amount
        }

        if sale_item_id is not None:
            payload["sale_item_id"] = sale_item_id
        if medicine_id is not None:
            payload["medicine_id"] = medicine_id

        return payload

    def refresh_claim_items_table(self):
        self.claim_items_table.setRowCount(0)

        total_gross = 0.0
        total_covered = 0.0
        total_patient = 0.0

        for row_idx, item in enumerate(self._claim_items_buffer):
            self.claim_items_table.insertRow(row_idx)

            quantity = float(item.get("quantity", 0) or 0)
            unit_price = float(item.get("unit_price", 0) or 0)
            gross = float(item.get("gross_amount", 0) or 0)
            covered = float(item.get("covered_amount", 0) or 0)
            patient = float(item.get("patient_amount", 0) or 0)

            values = [
                row_idx + 1,
                item.get("sale_item_id"),
                item.get("medicine_id"),
                f"{quantity:.2f}",
                f"{unit_price:.2f}",
                f"{gross:.2f}",
                f"{covered:.2f}",
                f"{patient:.2f}"
            ]

            for col_idx, value in enumerate(values):
                self._set_center_item(self.claim_items_table, row_idx, col_idx, value)

            total_gross += gross
            total_covered += covered
            total_patient += patient

        self.claim_items_count_card.value_label.setText(str(len(self._claim_items_buffer)))
        self.claim_items_gross_card.value_label.setText(f"{total_gross:.2f}")
        self.claim_items_covered_card.value_label.setText(f"{total_covered:.2f}")
        self.claim_items_patient_card.value_label.setText(f"{total_patient:.2f}")

    def clear_claim_item_inputs(self):
        self.selected_claim_item_row = None
        self.claim_item_sale_item_id_input.clear()
        self.claim_item_medicine_id_input.clear()
        self.claim_item_quantity_input.setValue(1.0)
        self.claim_item_unit_price_input.setValue(0.0)
        self.claim_item_gross_amount_input.setValue(0.0)
        self.claim_item_covered_amount_input.setValue(0.0)
        self.claim_item_patient_amount_input.setValue(0.0)
        self.claim_items_table.clearSelection()

    def clear_all_claim_items(self):
        if self._claim_items_buffer and not self._confirm("تأكيد", "هل تريد حذف جميع بنود المطالبة الحالية؟"):
            return

        self._claim_items_buffer = []
        self.clear_claim_item_inputs()
        self.refresh_claim_items_table()

    def add_claim_item(self):
        try:
            payload = self._claim_item_payload_from_form()
            self._claim_items_buffer.append(payload)
            self.refresh_claim_items_table()
            self.clear_claim_item_inputs()
            self._show_info("نجاح", "تمت إضافة بند المطالبة بنجاح.")
        except Exception as e:
            logger.exception("Failed to add claim item.")
            self._show_error("خطأ", str(e))

    def on_claim_item_selected(self):
        row = self.claim_items_table.currentRow()
        if row < 0 or row >= len(self._claim_items_buffer):
            return

        self.selected_claim_item_row = row
        item = self._claim_items_buffer[row]

        self.claim_item_sale_item_id_input.setText(str(item.get("sale_item_id") or ""))
        self.claim_item_medicine_id_input.setText(str(item.get("medicine_id") or ""))
        self.claim_item_quantity_input.setValue(float(item.get("quantity", 1.0) or 1.0))
        self.claim_item_unit_price_input.setValue(float(item.get("unit_price", 0.0) or 0.0))
        self.claim_item_gross_amount_input.setValue(float(item.get("gross_amount", 0.0) or 0.0))
        self.claim_item_covered_amount_input.setValue(float(item.get("covered_amount", 0.0) or 0.0))
        self.claim_item_patient_amount_input.setValue(float(item.get("patient_amount", 0.0) or 0.0))

    def update_selected_claim_item(self):
        if self.selected_claim_item_row is None or self.selected_claim_item_row >= len(self._claim_items_buffer):
            self._show_error("تنبيه", "الرجاء تحديد بند من جدول العناصر أولاً.")
            return

        try:
            payload = self._claim_item_payload_from_form()
            self._claim_items_buffer[self.selected_claim_item_row] = payload
            self.refresh_claim_items_table()
            self.clear_claim_item_inputs()
            self._show_info("نجاح", "تم تحديث البند المحدد بنجاح.")
        except Exception as e:
            logger.exception("Failed to update claim item.")
            self._show_error("خطأ", str(e))

    def remove_selected_claim_item(self):
        if self.selected_claim_item_row is None or self.selected_claim_item_row >= len(self._claim_items_buffer):
            self._show_error("تنبيه", "الرجاء تحديد بند من جدول العناصر أولاً.")
            return

        if not self._confirm("تأكيد", "هل أنت متأكد من حذف البند المحدد؟"):
            return

        try:
            del self._claim_items_buffer[self.selected_claim_item_row]
            self.clear_claim_item_inputs()
            self.refresh_claim_items_table()
            self._show_info("نجاح", "تم حذف البند المحدد بنجاح.")
        except Exception as e:
            logger.exception("Failed to remove claim item.")
            self._show_error("خطأ", str(e))

    def _claim_items_payload(self) -> List[Dict[str, Any]]:
        if not self._claim_items_buffer:
            raise ValueError("يجب إضافة بند واحد على الأقل قبل إنشاء المطالبة.")
        return [dict(item) for item in self._claim_items_buffer]

    # ==========================================
    # عمليات المطالبات
    # ==========================================
    def clear_claim_form(self):
        self.claim_customer_id_input.clear()
        self.claim_provider_combo.setCurrentIndex(0)
        self.claim_policy_id_input.clear()
        self.claim_sale_id_input.clear()
        self.claim_prescription_id_input.clear()
        self.claim_service_date.setDate(QDate.currentDate())
        self.claim_external_number_input.clear()
        self.claim_submission_notes_input.clear()
        self.claim_auto_submit_checkbox.setChecked(False)
        self.clear_all_claim_items()

    def create_claim(self):
        try:
            customer_id = self._safe_int(self.claim_customer_id_input.text(), "معرف العميل", required=True)
            policy_id = self._safe_int(self.claim_policy_id_input.text(), "معرف الوثيقة", required=False)
            provider_id = self.claim_provider_combo.currentData()
            sale_id = self._safe_int(self.claim_sale_id_input.text(), "معرف البيع", required=False)
            prescription_id = self._safe_int(self.claim_prescription_id_input.text(), "معرف الوصفة", required=False)
            claim_items = self._claim_items_payload()

            result = self.workflow.create_claim_and_optionally_submit(
                customer_id=customer_id,
                created_by_user_id=self.user_id,
                claim_items=claim_items,
                policy_id=policy_id,
                provider_id=provider_id,
                prescription_id=prescription_id,
                sale_id=sale_id,
                service_date=self.claim_service_date.date().toString("yyyy-MM-dd"),
                submission_notes=self._safe_text(self.claim_submission_notes_input.toPlainText()),
                external_claim_number=self._safe_text(self.claim_external_number_input.text()),
                auto_submit=self.claim_auto_submit_checkbox.isChecked()
            )

            success, payload = self._unwrap_result(result)
            if success:
                message = payload.get("message", "تم إنشاء المطالبة بنجاح.") if isinstance(payload, dict) else "تم إنشاء المطالبة بنجاح."
                self._show_info("نجاح", message)
                self.clear_claim_form()
                self.load_claims_table()
            else:
                self._show_error("فشل", str(payload))

        except Exception as e:
            logger.exception("Failed to create claim.")
            self._show_error("خطأ", str(e))

    def load_claims_table(self):
        try:
            customer_id = self._safe_int(self.claim_filter_customer_id_input.text(), "معرف العميل", required=False)

            if customer_id:
                rows = self.workflow.get_claims_for_customer(customer_id)
            else:
                result = self._call_first_available(
                    self.workflow.claims_dao,
                    ["get_all_claims", "list_claims", "get_claims"]
                )
                success, payload = self._unwrap_result(result)
                rows = payload if success and isinstance(payload, list) else []

            self._claim_cache = [r for r in rows if isinstance(r, dict)]
            self.claims_table.setRowCount(0)

            for row_idx, row in enumerate(self._claim_cache):
                self.claims_table.insertRow(row_idx)

                values = [
                    row.get("id"),
                    row.get("claim_number"),
                    row.get("provider_name") or row.get("provider_id"),
                    row.get("customer_name") or row.get("customer_id"),
                    self._claim_status_label(row.get("status")),
                    row.get("service_date"),
                    row.get("gross_amount"),
                    row.get("insurer_amount"),
                    row.get("approved_amount"),
                    row.get("collected_amount")
                ]

                for col_idx, value in enumerate(values):
                    self._set_center_item(self.claims_table, row_idx, col_idx, value)

        except Exception as e:
            logger.exception("Failed to load claims table.")
            self._show_error("خطأ", str(e))

    def on_claim_selected(self):
        row = self.claims_table.currentRow()
        if row < 0 or row >= len(self._claim_cache):
            return

        data = self._claim_cache[row]
        self.selected_claim_id = data.get("id")
        self.claim_selected_id_label.setText(str(self.selected_claim_id or "-"))
        self.collection_claim_id_input.setText(str(self.selected_claim_id or ""))

        self.show_claim_snapshot(silent=True)

    def show_claim_snapshot(self, silent: bool = False):
        if not self.selected_claim_id:
            if not silent:
                self._show_error("تنبيه", "الرجاء تحديد مطالبة أولاً.")
            return

        try:
            success, payload = self.workflow.get_claim_full_snapshot(self.selected_claim_id)
            if success:
                self._set_json_content(self.claim_details_view, payload)
            else:
                if not silent:
                    self._show_error("فشل", str(payload))
        except Exception as e:
            logger.exception("Failed to show claim snapshot.")
            if not silent:
                self._show_error("خطأ", str(e))

    def submit_selected_claim(self):
        if not self.selected_claim_id:
            self._show_error("تنبيه", "الرجاء تحديد مطالبة أولاً.")
            return

        try:
            success, payload = self.workflow.submit_claim(
                claim_id=self.selected_claim_id,
                updated_by_user_id=self.user_id,
                submission_notes=self._safe_text(self.claim_decision_notes_input.toPlainText())
            )
            if success:
                message = payload.get("message", "تم إرسال المطالبة.") if isinstance(payload, dict) else "تم إرسال المطالبة."
                self._show_info("نجاح", message)
                self.load_claims_table()
                self.show_claim_snapshot(silent=True)
            else:
                self._show_error("فشل", str(payload))
        except Exception as e:
            logger.exception("Failed to submit selected claim.")
            self._show_error("خطأ", str(e))

    def approve_selected_claim(self):
        if not self.selected_claim_id:
            self._show_error("تنبيه", "الرجاء تحديد مطالبة أولاً.")
            return

        try:
            approved_amount = self._safe_float(
                self.claim_approved_amount_input.text(),
                "المبلغ المعتمد",
                required=False
            )
            success, payload = self.workflow.approve_claim(
                claim_id=self.selected_claim_id,
                updated_by_user_id=self.user_id,
                approved_amount=approved_amount,
                decision_notes=self._safe_text(self.claim_decision_notes_input.toPlainText()),
                approved_items=None
            )
            if success:
                message = payload.get("message", "تم اعتماد المطالبة.") if isinstance(payload, dict) else "تم اعتماد المطالبة."
                self._show_info("نجاح", message)
                self.load_claims_table()
                self.show_claim_snapshot(silent=True)
            else:
                self._show_error("فشل", str(payload))
        except Exception as e:
            logger.exception("Failed to approve selected claim.")
            self._show_error("خطأ", str(e))

    def reject_selected_claim(self):
        if not self.selected_claim_id:
            self._show_error("تنبيه", "الرجاء تحديد مطالبة أولاً.")
            return

        rejection_reason = self._safe_text(self.claim_rejection_reason_input.text())
        if not rejection_reason:
            self._show_error("تنبيه", "سبب الرفض إلزامي.")
            return

        try:
            success, payload = self.workflow.reject_claim(
                claim_id=self.selected_claim_id,
                updated_by_user_id=self.user_id,
                rejection_reason=rejection_reason,
                decision_notes=self._safe_text(self.claim_decision_notes_input.toPlainText())
            )
            if success:
                message = payload.get("message", "تم رفض المطالبة.") if isinstance(payload, dict) else "تم رفض المطالبة."
                self._show_info("نجاح", message)
                self.load_claims_table()
                self.show_claim_snapshot(silent=True)
            else:
                self._show_error("فشل", str(payload))
        except Exception as e:
            logger.exception("Failed to reject selected claim.")
            self._show_error("خطأ", str(e))

    def cancel_selected_claim(self):
        if not self.selected_claim_id:
            self._show_error("تنبيه", "الرجاء تحديد مطالبة أولاً.")
            return

        if not self._confirm("تأكيد", "هل أنت متأكد من إلغاء المطالبة المحددة؟"):
            return

        try:
            success, payload = self.workflow.cancel_claim(
                claim_id=self.selected_claim_id,
                updated_by_user_id=self.user_id,
                reason=self._safe_text(self.claim_decision_notes_input.toPlainText())
            )
            if success:
                message = payload.get("message", "تم إلغاء المطالبة.") if isinstance(payload, dict) else "تم إلغاء المطالبة."
                self._show_info("نجاح", message)
                self.load_claims_table()
                self.show_claim_snapshot(silent=True)
            else:
                self._show_error("فشل", str(payload))
        except Exception as e:
            logger.exception("Failed to cancel selected claim.")
            self._show_error("خطأ", str(e))

    # ==========================================
    # عمليات التحصيلات
    # ==========================================
    def load_collectible_claims_table(self):
        try:
            rows = self.workflow.get_collectible_claims()
            self._collectible_claims_cache = [r for r in rows if isinstance(r, dict)]
            self.collectible_claims_table.setRowCount(0)

            for row_idx, row in enumerate(self._collectible_claims_cache):
                self.collectible_claims_table.insertRow(row_idx)

                approved = float(row.get("approved_amount", 0) or 0)
                collected = float(row.get("collected_amount", 0) or 0)
                remaining = round(max(approved - collected, 0.0), 2)

                values = [
                    row.get("id"),
                    row.get("claim_number"),
                    row.get("provider_name") or row.get("provider_id"),
                    row.get("customer_name") or row.get("customer_id"),
                    self._claim_status_label(row.get("status")),
                    approved,
                    collected,
                    remaining
                ]

                for col_idx, value in enumerate(values):
                    self._set_center_item(self.collectible_claims_table, row_idx, col_idx, value)

        except Exception as e:
            logger.exception("Failed to load collectible claims.")
            self._show_error("خطأ", str(e))

    def on_collectible_claim_selected(self):
        row = self.collectible_claims_table.currentRow()
        if row < 0 or row >= len(self._collectible_claims_cache):
            return

        data = self._collectible_claims_cache[row]
        claim_id = data.get("id")
        self.collection_claim_id_input.setText(str(claim_id or ""))

        self.load_collection_claim_snapshot(silent=True)

    def record_collection(self):
        try:
            claim_id = self._safe_int(self.collection_claim_id_input.text(), "معرف المطالبة", required=True)
            amount = self._safe_float(self.collection_amount_input.text(), "المبلغ", required=True)
            shift_id = self._safe_int(self.collection_shift_id_input.text(), "معرف الوردية", required=False)

            success, payload = self.workflow.record_collection(
                claim_id=claim_id,
                amount=amount,
                user_id=self.user_id,
                payment_method=self.collection_payment_method_combo.currentData(),
                shift_id=shift_id,
                collection_reference=self._safe_text(self.collection_reference_input.text()),
                collection_date=self.collection_date.date().toString("yyyy-MM-dd"),
                notes=self._safe_text(self.collection_notes_input.toPlainText())
            )

            if success:
                message = payload.get("message", "تم تسجيل التحصيل بنجاح.") if isinstance(payload, dict) else "تم تسجيل التحصيل بنجاح."
                self._show_info("نجاح", message)
                self.load_collectible_claims_table()
                self.load_collection_claim_snapshot(silent=True)
            else:
                self._show_error("فشل", str(payload))

        except Exception as e:
            logger.exception("Failed to record collection.")
            self._show_error("خطأ", str(e))

    def load_collection_claim_snapshot(self, silent: bool = False):
        try:
            claim_id = self._safe_int(self.collection_claim_id_input.text(), "معرف المطالبة", required=True)
            success, payload = self.workflow.get_claim_full_snapshot(claim_id)

            if success:
                self._set_json_content(self.collection_summary_view, payload)
            else:
                if not silent:
                    self._show_error("فشل", str(payload))

        except Exception as e:
            logger.exception("Failed to load collection claim snapshot.")
            if not silent:
                self._show_error("خطأ", str(e))