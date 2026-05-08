"""
وظيفة الملف: لوحة التحكم الرئيسية (Dashboard UI) - النسخة التفاعلية الفخمة والمحسّنة.
الطبقة: Presentation Layer

المميزات:
- [Premium UI/UX]: مساحات بيضاء مدروسة، ظلال ناعمة (Soft Shadows)، وحواف دائرية (Rounded Corners) تعكس تصميم حديث (Modern SaaS).
- [Interactive Navigation]: البطاقات قابلة للضغط وتوجه المستخدم مباشرة إلى الصفحة المرتبطة بالمؤشر (تطبيق قانون فيتس).
- [Rich Hover Feedback]: استجابة بصرية ديناميكية تتضمن تعميق الظل وتغيير لون الخلفية بمهارة عند المرور.
- [Operational Dashboard]: عرض المؤشرات التشغيلية والمالية بتسلسل هرمي بصري يبرز الأرقام بوضوح.
- [Safe Refresh]: إعادة تحميل الإحصائيات من DashboardDAO بشكل آمن مع تحديث وقت القراءة.
- [Thin Client]: الواجهة لا تحتوي أي SQL وتعتمد بالكامل على DashboardDAO.
"""

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QGridLayout,
    QScrollArea,
    QGraphicsDropShadowEffect,
    QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime
from PyQt5.QtGui import QColor, QCursor
from models.dashboard_dao import DashboardDAO


class DashboardCard(QFrame):
    """
    بطاقة إحصائية تفاعلية.
    عند الضغط عليها ترسل index الصفحة المستهدفة إذا كانت البطاقة مرتبطة بصفحة.
    """
    clicked = pyqtSignal(int)

    def __init__(self, title, value, accent_color, target_page_index=None, icon_text="•", hint_text=""):
        super().__init__()

        self.title = title
        self.accent_color = accent_color
        self.target_page_index = target_page_index
        self.icon_text = icon_text
        self.hint_text = hint_text or "اضغط لفتح الصفحة المرتبطة" if target_page_index is not None else "مؤشر معلوماتي"
        self.is_clickable = target_page_index is not None

        self.setObjectName("DashboardCard")
        self.setMinimumHeight(180) # زيادة الارتفاع لزيادة المساحة البيضاء الفخمة
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(QCursor(Qt.PointingHandCursor) if self.is_clickable else QCursor(Qt.ArrowCursor))

        self._setup_shadow()
        self._build_ui()
        self._apply_style(hovered=False)
        self.update_value(value)

    def _setup_shadow(self):
        # ظلال ناعمة جداً لمحاكاة الإضاءة الطبيعية
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(30)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(8)
        self.shadow.setColor(QColor(0, 0, 0, 15)) # شفافية عالية لظل أنيق
        self.setGraphicsEffect(self.shadow)

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(24, 24, 24, 24) # حواف داخلية مريحة للعين
        self.main_layout.setSpacing(12)

        # الصف العلوي: أيقونة + عنوان
        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        # تحسين شكل الأيقونة لتصبح دائرة مكتملة بألوان واضحة
        self.icon_badge = QLabel(self.icon_text)
        self.icon_badge.setFixedSize(44, 44)
        self.icon_badge.setAlignment(Qt.AlignCenter)
        self.icon_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {self.accent_color};
                color: white;
                border-radius: 22px;
                font-size: 18px;
                font-weight: bold;
                font-family: 'Segoe UI', 'Arial';
            }}
        """)

        self.title_label = QLabel(self.title)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #475569; /* لون رمادي مزرق حديث */
                font-size: 16px;
                font-weight: 600;
                font-family: 'Segoe UI', 'Arial', 'Tahoma';
            }
        """)

        top_row.addWidget(self.icon_badge, 0, Qt.AlignTop)
        top_row.addWidget(self.title_label, 1)

        # القيمة (التركيز البصري الأكبر)
        self.value_label = QLabel("0")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setStyleSheet(f"""
            QLabel {{
                color: #0F172A; /* لون داكن جداً للقيمة لإبرازها */
                font-size: 34px;
                font-weight: 900;
                font-family: 'Segoe UI', 'Arial', 'Tahoma';
                margin-top: 5px;
            }}
        """)

        # سطر التلميح (التركيز البصري الأقل)
        self.hint_label = QLabel(self.hint_text)
        self.hint_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-weight: 400;
                font-family: 'Segoe UI', 'Arial', 'Tahoma';
            }
        """)

        self.main_layout.addLayout(top_row)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.value_label)
        self.main_layout.addWidget(self.hint_label)

    def _apply_style(self, hovered=False):
        # استخدام تدرجات لونية خفيفة جداً لتعزيز الشعور بالعمق
        bg_color = "#F8FAFC" if hovered else "#FFFFFF"
        border_color = self.accent_color if hovered else "#E2E8F0"

        # مؤشر لون جانبي أنيق يدل على هوية البطاقة
        self.setStyleSheet(f"""
            QFrame#DashboardCard {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-right: 6px solid {self.accent_color};
                border-radius: 16px;
            }}
        """)

        # تأثير طفو ديناميكي عند المرور (Hover)
        if hovered:
            self.shadow.setBlurRadius(40)
            self.shadow.setYOffset(12)
            self.shadow.setColor(QColor(0, 0, 0, 25))
        else:
            self.shadow.setBlurRadius(30)
            self.shadow.setYOffset(8)
            self.shadow.setColor(QColor(0, 0, 0, 15))

    def enterEvent(self, event):
        if self.is_clickable:
            self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_clickable and event.button() == Qt.LeftButton:
            self.clicked.emit(self.target_page_index)
        super().mouseReleaseEvent(event)

    def update_value(self, new_value):
        self.value_label.setText(str(new_value))


class HomePage(QWidget):
    """
    الصفحة الرئيسية ولوحة التحكم.
    تطلق إشارة request_navigation عندما يضغط المستخدم على بطاقة مرتبطة بصفحة أخرى.
    """
    request_navigation = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.dao = DashboardDAO()
        self.cards = {}
        self._build_ui()
        self.load_stats()

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def _build_ui(self):
        self.setLayoutDirection(Qt.RightToLeft)
        # خلفية عامة محايدة تبرز البطاقات البيضاء (تأثير تباين إيجابي)
        self.setStyleSheet("""
            QWidget {
                background-color: #F1F5F9; 
                color: #0F172A;
                font-family: 'Segoe UI', 'Arial', 'Tahoma';
            }
        """)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #F1F5F9;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #CBD5E1;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
        """)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(26)

        # --------------------------------------
        # رأس الصفحة (Header) - تصميم بانر فخم
        # --------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFFFFF, stop:1 #F8FAFC);
                border: 1px solid #E2E8F0;
                border-radius: 20px;
            }
        """)
        header_shadow = QGraphicsDropShadowEffect(header_card)
        header_shadow.setBlurRadius(25)
        header_shadow.setXOffset(0)
        header_shadow.setYOffset(6)
        header_shadow.setColor(QColor(0, 0, 0, 10))
        header_card.setGraphicsEffect(header_shadow)

        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(30, 26, 30, 26)
        header_layout.setSpacing(20)

        title_column = QVBoxLayout()
        title_column.setSpacing(6)

        title_label = QLabel("لوحة المؤشرات التشغيلية والمالية")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 30px;
                font-weight: 900;
                color: #1E293B;
                background: transparent;
                border: none;
            }
        """)

        subtitle_label = QLabel(
            "نظرة شاملة وسريعة على الأداء اليومي للصيدلية. "
            "يمكن الضغط على أي بطاقة للانتقال مباشرة إلى القسم المرتبط بها."
        )
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet("""
            QLabel {
                font-size: 15px;
                color: #64748B;
                background: transparent;
                border: none;
            }
        """)

        self.last_update_label = QLabel("آخر تحديث: —")
        self.last_update_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #475569;
                font-weight: 600;
                background: transparent;
                border: none;
                margin-top: 8px;
            }
        """)

        title_column.addWidget(title_label)
        title_column.addWidget(subtitle_label)
        title_column.addWidget(self.last_update_label)

        # زر التحديث بتصميم Modern Button
        self.btn_refresh = QPushButton("🔄 تحديث البيانات")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setMinimumHeight(52)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #2563EB; /* أزرق ملكي حديث */
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 24px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """)
        self.btn_refresh.clicked.connect(self.load_stats)

        header_layout.addLayout(title_column, 1)
        header_layout.addWidget(self.btn_refresh, 0, Qt.AlignLeft | Qt.AlignVCenter)

        content_layout.addWidget(header_card)

        # --------------------------------------
        # شريط إرشادي (Alert Box) - تصميم ناعم
        # --------------------------------------
        hint_card = QFrame()
        hint_card.setStyleSheet("""
            QFrame {
                background-color: #EFF6FF; /* أزرق فاتح جداً */
                border: 1px solid #BFDBFE;
                border-radius: 12px;
            }
        """)
        hint_layout = QHBoxLayout(hint_card)
        hint_layout.setContentsMargins(20, 14, 20, 14)
        hint_layout.setSpacing(12)

        hint_icon = QLabel("ℹ️")
        hint_icon.setStyleSheet("""
            QLabel {
                font-size: 18px;
                background: transparent;
                border: none;
            }
        """)

        hint_text = QLabel(
            "المؤشرات الملونة قابلة للنقر. الهدف منها تحويل الصفحة الرئيسية إلى مركز قيادة سريع وليس مجرد شاشة أرقام."
        )
        hint_text.setWordWrap(True)
        hint_text.setStyleSheet("""
            QLabel {
                color: #1E40AF;
                font-size: 14px;
                font-weight: 500;
                background: transparent;
                border: none;
            }
        """)

        hint_layout.addWidget(hint_icon)
        hint_layout.addWidget(hint_text, 1)

        content_layout.addWidget(hint_card)

        # --------------------------------------
        # شبكة البطاقات
        # --------------------------------------
        cards_frame = QFrame()
        cards_frame.setStyleSheet("background: transparent; border: none;")

        self.cards_layout = QGridLayout(cards_frame)
        self.cards_layout.setHorizontalSpacing(24) # مساحات بصرية أوسع
        self.cards_layout.setVerticalSpacing(24)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)

        # تعريف البطاقات
        # تم استخدام ألوان Hex حديثة (Tailwind Colors Palette) لضمان التناسق والفخامة.
        card_definitions = [
            # الصف 1
            {
                "title": "إجمالي المبيعات",
                "key": "today_gross_sales",
                "color": "#3B82F6", # Blue
                "target": 17,
                "icon": "₺",
                "hint": "فتح صفحة التقارير",
                "row": 0, "col": 0, "row_span": 1, "col_span": 1
            },
            {
                "title": "إجمالي المرتجعات",
                "key": "today_total_returns",
                "color": "#EF4444", # Red
                "target": 12,
                "icon": "↩",
                "hint": "فتح صفحة المرتجعات",
                "row": 0, "col": 1, "row_span": 1, "col_span": 1
            },
            {
                "title": "صافي المبيعات",
                "key": "today_net_sales",
                "color": "#10B981", # Emerald
                "target": 17,
                "icon": "Σ",
                "hint": "عرض صافي الأداء اليومي",
                "row": 0, "col": 2, "row_span": 1, "col_span": 1
            },

            # الصف 2
            {
                "title": "الداخل النقدي",
                "key": "today_cash_in",
                "color": "#059669", # Dark Emerald
                "target": 17,
                "icon": "↓",
                "hint": "تفاصيل التدفق النقدي",
                "row": 1, "col": 0, "row_span": 1, "col_span": 1
            },
            {
                "title": "الخارج النقدي",
                "key": "today_cash_out",
                "color": "#F97316", # Orange
                "target": 13,
                "icon": "↑",
                "hint": "فتح صفحة المصروفات",
                "row": 1, "col": 1, "row_span": 1, "col_span": 1
            },
            {
                "title": "هامش الربح الإجمالي",
                "key": "today_gross_profit",
                "color": "#8B5CF6", # Violet
                "target": 17,
                "icon": "%",
                "hint": "مراجعة الربحية الإجمالية",
                "row": 1, "col": 2, "row_span": 1, "col_span": 1
            },

            # الصف 3
            {
                "title": "المصروفات التشغيلية",
                "key": "today_expenses",
                "color": "#F59E0B", # Amber
                "target": 13,
                "icon": "¤",
                "hint": "فتح صفحة المصروفات",
                "row": 2, "col": 0, "row_span": 1, "col_span": 1
            },
            {
                "title": "خسائر الإتلاف",
                "key": "today_disposal_losses",
                "color": "#DC2626", # Red Dark
                "target": 15,
                "icon": "✖",
                "hint": "فتح صفحة الإتلاف",
                "row": 2, "col": 1, "row_span": 1, "col_span": 1
            },
            {
                "title": "صافي الربح الفعلي",
                "key": "today_net_profit",
                "color": "#0F766E", # Teal
                "target": 17,
                "icon": "◎",
                "hint": "قراءة الربح الفعلي اليومي",
                "row": 2, "col": 2, "row_span": 1, "col_span": 1
            },

            # الصف 4
            {
                "title": "نواقص المخزون",
                "key": "low_stock_count",
                "color": "#E11D48", # Rose
                "target": 1,
                "icon": "!",
                "hint": "فتح المخزون مع متابعة النواقص",
                "row": 3, "col": 0, "row_span": 1, "col_span": 1
            },
            {
                "title": "صلاحية وشيكة (90 يوم)",
                "key": "expiring_soon_count",
                "color": "#D97706", # Amber Dark
                "target": 1,
                "icon": "⏳",
                "hint": "الأدوية القريبة من الانتهاء",
                "row": 3, "col": 1, "row_span": 1, "col_span": 1
            },
            {
                "title": "منتهية الصلاحية",
                "key": "expired_count",
                "color": "#475569",
                "target": 15,
                "icon": "⌛",
                "hint": "فتح صفحة الإتلاف للرزم المنتهية",
                "row": 3, "col": 2, "row_span": 1, "col_span": 1
            },

            # الصف 5
            {
                "title": "إجمالي أصناف الأدوية",
                "key": "total_medicines",
                "color": "#0284C7", # Light Blue
                "target": 1,
                "icon": "☰",
                "hint": "فتح صفحة المخزون والأدوية",
                "row": 4, "col": 0, "row_span": 1, "col_span": 2
            },
            {
                "title": "المستخدمون النشطون",
                "key": "users_count",
                "color": "#334155", # Slate Dark
                "target": 18,
                "icon": "👤",
                "hint": "فتح صفحة المستخدمين",
                "row": 4, "col": 2, "row_span": 1, "col_span": 1
            }
        ]

        for card_info in card_definitions:
            card = DashboardCard(
                title=card_info["title"],
                value="0",
                accent_color=card_info["color"],
                target_page_index=card_info["target"],
                icon_text=card_info["icon"],
                hint_text=card_info["hint"]
            )
            card.clicked.connect(self.request_navigation.emit)

            self.cards_layout.addWidget(
                card,
                card_info["row"],
                card_info["col"],
                card_info["row_span"],
                card_info["col_span"]
            )
            self.cards[card_info["key"]] = card

        content_layout.addWidget(cards_frame)
        content_layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    # ==========================================
    # تنسيق القيم
    # ==========================================
    def _format_money(self, value):
        try:
            return f"{float(value):,.2f}"
        except Exception:
            return "0.00"

    def _format_count(self, value):
        try:
            return f"{int(value)}"
        except Exception:
            return "0"

    # ==========================================
    # تحميل الإحصائيات
    # ==========================================
    def load_stats(self):
        try:
            kpis = self.dao.get_dashboard_kpis() or {}
        except Exception:
            kpis = {}

        financial_keys = [
            "today_gross_sales",
            "today_total_returns",
            "today_net_sales",
            "today_cash_in",
            "today_cash_out",
            "today_gross_profit",
            "today_expenses",
            "today_disposal_losses",
            "today_net_profit"
        ]

        count_keys = [
            "low_stock_count",
            "expiring_soon_count",
            "expired_count",
            "total_medicines",
            "users_count"
        ]

        for key in financial_keys:
            if key in self.cards:
                self.cards[key].update_value(self._format_money(kpis.get(key, 0.0)))

        for key in count_keys:
            if key in self.cards:
                self.cards[key].update_value(self._format_count(kpis.get(key, 0)))

        now_text = QDateTime.currentDateTime().toString("yyyy-MM-dd  hh:mm:ss")
        self.last_update_label.setText(f"آخر تحديث: {now_text}")