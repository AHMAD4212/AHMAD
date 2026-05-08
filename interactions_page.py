"""
وظيفة الملف: واجهة إدارة قاعدة بيانات التداخلات الدوائية (Drug Interactions KB).
الطبقة: Presentation Layer

ملاحظات معمارية وأمنية:
- [UI RBAC]&#58; صلاحيات الإدارة (إضافة/تعديل/تفعيل/تعطيل/حذف) محصورة بـ (admin, pharmacist).
- [Read-Only for Cashier]&#58; الكاشير يمكنه البحث والقراءة فقط لفهم التحذيرات.
- [Dumb Client]&#58; الواجهة لا تقوم بالتنظيف canonicalization ولا بفحص المنطق الطبي؛
  بل تمرر البيانات للنواة وتعرض رسائلها كما هي.
- [DAO Contract V2]&#58;   الواجهة متوافقة مع InteractionsDAO الجديد الذي يدعم:
    1) add_interaction
    2) update_interaction
    3) toggle_interaction_status
    4) delete_interaction
    5) get_interaction_by_id
    6) get_all_interactions
    7) search_interactions
- [Clinical Separation]&#58;   تم فصل:
    - الأثر السريري
    - التوصية
    - خطة الإدارة
    - المصدر المرجعي
  بدلاً من خلطها في حقل واحد.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QLabel, QComboBox, QFrame, QSplitter,
    QTextEdit, QAbstractItemView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from models.interactions_dao import InteractionsDAO


class InteractionsPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = InteractionsDAO()

        self.current_interaction_id = None
        self.current_is_active = None
        self.current_mode = "view"   # view | add | edit

        self.severity_map = {
            "contraindicated": "ممنوع الاستخدام المطلق",
            "major": "خطير (Major)",
            "moderate": "متوسط (Moderate)",
            "minor": "طفيف (Minor)"
        }

        self.init_ui()
        self.load_data()
        self.reset_form()

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title = QLabel("قاعدة المعرفة الطبية: التداخلات الدوائية (Drug Interactions)")
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #2C3E50;
            font-family: 'Times New Roman';
        """)
        main_layout.addWidget(title)

        subtitle = QLabel(
            "إدارة التداخلات بين المواد الفعالة مع فصل الأثر السريري عن التوصية وخطة الإدارة "
            "والمصدر المرجعي، وربط حالة التفعيل/التعطيل بالنواة مباشرة."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("""
            font-size: 14px;
            color: #5D6D7E;
            font-family: 'Times New Roman';
        """)
        main_layout.addWidget(subtitle)

        main_splitter = QSplitter(Qt.Vertical)

        # ==========================================
        # القسم العلوي: النموذج
        # ==========================================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        self.form_frame = QFrame()
        self.form_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #D5DBDB;
            }
        """)
        form_layout = QVBoxLayout(self.form_frame)
        form_layout.setContentsMargins(15, 15, 15, 15)
        form_layout.setSpacing(12)

        self.lbl_form_title = QLabel("إضافة قاعدة تداخل دوائي جديدة")
        self.lbl_form_title.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #34495E;
            font-family: 'Times New Roman';
        """)
        form_layout.addWidget(self.lbl_form_title)

        # الصف 1
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("المادة الأولى:"), 1)
        self.ing1_input = QLineEdit()
        self.ing1_input.setPlaceholderText("مثال: aspirin")
        self.ing1_input.setStyleSheet("font-size: 16px; padding: 8px;")
        row1.addWidget(self.ing1_input, 3)

        row1.addWidget(QLabel("المادة الثانية:"), 1)
        self.ing2_input = QLineEdit()
        self.ing2_input.setPlaceholderText("مثال: warfarin")
        self.ing2_input.setStyleSheet("font-size: 16px; padding: 8px;")
        row1.addWidget(self.ing2_input, 3)

        row1.addWidget(QLabel("الخطورة:"), 1)
        self.severity_combo = QComboBox()
        self.severity_combo.addItem("ممنوع الاستخدام المطلق (Contraindicated)", "contraindicated")
        self.severity_combo.addItem("خطير (Major)", "major")
        self.severity_combo.addItem("متوسط (Moderate)", "moderate")
        self.severity_combo.addItem("طفيف (Minor)", "minor")
        self.severity_combo.setStyleSheet("font-size: 16px; padding: 8px;")
        row1.addWidget(self.severity_combo, 2)

        form_layout.addLayout(row1)

        # الصف 2
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        row2.addWidget(QLabel("الأثر السريري *:"), 1)
        self.clinical_effect_input = QTextEdit()
        self.clinical_effect_input.setPlaceholderText("ما هو الخطر السريري المتوقع؟")
        self.clinical_effect_input.setFixedHeight(75)
        self.clinical_effect_input.setStyleSheet("""
            font-size: 16px;
            padding: 8px;
            border: 1px solid #BDC3C7;
            border-radius: 4px;
        """)
        row2.addWidget(self.clinical_effect_input, 7)

        form_layout.addLayout(row2)

        # الصف 3
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        row3.addWidget(QLabel("التوصية:"), 1)
        self.recommendation_input = QTextEdit()
        self.recommendation_input.setPlaceholderText("مثال: تجنب المشاركة أو خفض الجرعة أو المراقبة الدقيقة")
        self.recommendation_input.setFixedHeight(65)
        self.recommendation_input.setStyleSheet("""
            font-size: 16px;
            padding: 8px;
            border: 1px solid #BDC3C7;
            border-radius: 4px;
        """)
        row3.addWidget(self.recommendation_input, 3)

        row3.addWidget(QLabel("خطة الإدارة:"), 1)
        self.management_plan_input = QTextEdit()
        self.management_plan_input.setPlaceholderText("مثال: مراقبة INR أو ضغط الدم أو وظائف الكلى")
        self.management_plan_input.setFixedHeight(65)
        self.management_plan_input.setStyleSheet("""
            font-size: 16px;
            padding: 8px;
            border: 1px solid #BDC3C7;
            border-radius: 4px;
        """)
        row3.addWidget(self.management_plan_input, 3)

        form_layout.addLayout(row3)

        # الصف 4
        row4 = QHBoxLayout()
        row4.setSpacing(10)

        row4.addWidget(QLabel("المصدر المرجعي:"), 1)
        self.source_reference_input = QLineEdit()
        self.source_reference_input.setPlaceholderText("مصدر علمي/مرجع دوائي")
        self.source_reference_input.setStyleSheet("font-size: 16px; padding: 8px;")
        row4.addWidget(self.source_reference_input, 7)

        form_layout.addLayout(row4)

        # صف الأزرار
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_new = QPushButton("➕ جديد")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self.prepare_add_mode)
        self.btn_new.setStyleSheet("""
            background-color: #2980B9;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        self.btn_save = QPushButton("💾 حفظ")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_interaction)
        self.btn_save.setStyleSheet("""
            background-color: #27AE60;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        self.btn_cancel = QPushButton("إلغاء")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reset_form)
        self.btn_cancel.setStyleSheet("""
            background-color: #7F8C8D;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        self.btn_edit = QPushButton("✏️ تعديل المحدد")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self.enable_edit_mode)
        self.btn_edit.setStyleSheet("""
            background-color: #F39C12;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        self.btn_toggle = QPushButton("🚫 تعطيل / تفعيل")
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle_selected_interaction)
        self.btn_toggle.setStyleSheet("""
            background-color: #8E44AD;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        self.btn_delete = QPushButton("🗑️ حذف نهائي")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet("""
            background-color: #E74C3C;
            color: white;
            font-weight: bold;
            font-size: 15px;
            padding: 10px 18px;
            border-radius: 5px;
        """)

        actions_row.addWidget(self.btn_new)
        actions_row.addWidget(self.btn_save)
        actions_row.addWidget(self.btn_cancel)
        actions_row.addStretch()
        actions_row.addWidget(self.btn_edit)
        actions_row.addWidget(self.btn_toggle)
        actions_row.addWidget(self.btn_delete)

        form_layout.addLayout(actions_row)
        top_layout.addWidget(self.form_frame)

        # ==========================================
        # القسم السفلي: البحث + الجدول + التفاصيل
        # ==========================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(12)

        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث بالمادة الفعالة أو الخطورة أو الأثر السريري...")
        self.search_input.setFixedHeight(42)
        self.search_input.setStyleSheet("""
            font-size: 16px;
            padding: 6px;
            border: 1px solid #BDC3C7;
            border-radius: 4px;
        """)
        self.search_input.textChanged.connect(self.search_data)

        self.status_filter = QComboBox()
        self.status_filter.addItem("الكل", "all")
        self.status_filter.addItem("النشط فقط", "active")
        self.status_filter.addItem("المعطل فقط", "inactive")
        self.status_filter.setFixedHeight(42)
        self.status_filter.currentIndexChanged.connect(self.search_data)
        self.status_filter.setStyleSheet("font-size: 15px; padding: 6px;")

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.setFixedHeight(42)
        self.btn_refresh.clicked.connect(self.load_data)

        tools_layout.addWidget(self.search_input, 5)
        tools_layout.addWidget(self.status_filter, 2)
        tools_layout.addWidget(self.btn_refresh, 1)

        bottom_layout.addLayout(tools_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "المادة (أ)",
            "المادة (ب)",
            "الخطورة",
            "الحالة",
            "الأثر السريري",
            "أضيفت بواسطة",
            "تاريخ الإنشاء"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet("""
            font-size: 16px;
            font-family: 'Times New Roman';
        """)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)

        bottom_layout.addWidget(self.table)

        self.details_frame = QFrame()
        self.details_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D5DBDB;
                border-radius: 8px;
            }
        """)
        details_layout = QVBoxLayout(self.details_frame)
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(10)

        self.lbl_details_title = QLabel("تفاصيل القاعدة المحددة")
        self.lbl_details_title.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #2C3E50;
            font-family: 'Times New Roman';
        """)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            background-color: white;
            font-size: 15px;
            font-family: 'Times New Roman';
            padding: 10px;
        """)

        details_layout.addWidget(self.lbl_details_title)
        details_layout.addWidget(self.details_text)
        bottom_layout.addWidget(self.details_frame)

        main_splitter.addWidget(top_widget)
        main_splitter.addWidget(bottom_widget)
        main_splitter.setSizes([280, 450])

        main_layout.addWidget(main_splitter)

        # ==========================================
        # UI RBAC
        # ==========================================
        if self.user_role not in ["admin", "pharmacist"]:
            self.form_frame.hide()
            self.btn_edit.hide()
            self.btn_toggle.hide()
            self.btn_delete.hide()
            title.setText("قاعدة المعرفة الطبية: التداخلات الدوائية (للقراءة فقط)")

    # ==========================================
    # Helpers
    # ==========================================
    def _severity_display(self, severity):
        return self.severity_map.get(severity, severity)

    def _status_display(self, is_active):
        return "نشط" if int(is_active) == 1 else "معطل"

    def _status_color(self, is_active):
        return QColor("#27AE60") if int(is_active) == 1 else QColor("#7F8C8D")

    def _severity_style_item(self, item, raw_severity):
        item.setFont(QFont("Times New Roman", 14, QFont.Bold))

        if raw_severity == "contraindicated":
            item.setForeground(QColor("white"))
            item.setBackground(QColor("#800000"))
        elif raw_severity == "major":
            item.setForeground(QColor("white"))
            item.setBackground(QColor("#E74C3C"))
        elif raw_severity == "moderate":
            item.setForeground(QColor("black"))
            item.setBackground(QColor("#F39C12"))
        elif raw_severity == "minor":
            item.setForeground(QColor("black"))
            item.setBackground(QColor("#F1C40F"))

    def _get_selected_status_filter(self):
        val = self.status_filter.currentData()
        if val == "active":
            return True
        if val == "inactive":
            return False
        return None

    def _clear_inputs(self):
        self.ing1_input.clear()
        self.ing2_input.clear()
        self.severity_combo.setCurrentIndex(0)
        self.clinical_effect_input.clear()
        self.recommendation_input.clear()
        self.management_plan_input.clear()
        self.source_reference_input.clear()

    def _set_form_enabled(self, enabled):
        self.ing1_input.setEnabled(enabled)
        self.ing2_input.setEnabled(enabled)
        self.severity_combo.setEnabled(enabled)
        self.clinical_effect_input.setEnabled(enabled)
        self.recommendation_input.setEnabled(enabled)
        self.management_plan_input.setEnabled(enabled)
        self.source_reference_input.setEnabled(enabled)
        self.btn_save.setVisible(enabled)
        self.btn_cancel.setVisible(enabled)

    def _selected_interaction_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        try:
            return int(self.table.item(row, 0).text())
        except Exception:
            return None

    # ==========================================
    # إدارة الحالة
    # ==========================================
    def reset_form(self):
        self.current_interaction_id = None
        self.current_is_active = None
        self.current_mode = "view"

        self._clear_inputs()
        self._set_form_enabled(False)

        self.lbl_form_title.setText("إضافة قاعدة تداخل دوائي جديدة")
        self.btn_new.setVisible(True)
        self.btn_edit.setVisible(True)
        self.btn_toggle.setVisible(True)
        self.btn_delete.setVisible(True)
        self.btn_toggle.setText("🚫 تعطيل / تفعيل")

    def prepare_add_mode(self):
        self.current_interaction_id = None
        self.current_is_active = 1
        self.current_mode = "add"

        self._clear_inputs()
        self._set_form_enabled(True)
        self.lbl_form_title.setText("إضافة قاعدة تداخل دوائي جديدة")

    def enable_edit_mode(self):
        if self.user_role not in ["admin", "pharmacist"]:
            return

        interaction_id = self._selected_interaction_id()
        if not interaction_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد قاعدة من الجدول أولاً.")
            return

        data = self.dao.get_interaction_by_id(interaction_id)
        if not data:
            QMessageBox.warning(self, "تنبيه", "تعذر جلب بيانات القاعدة المحددة.")
            return

        self.current_interaction_id = interaction_id
        self.current_is_active = int(data.get("is_active", 0))
        self.current_mode = "edit"

        self.ing1_input.setText(data.get("ingredient_1", ""))
        self.ing2_input.setText(data.get("ingredient_2", ""))

        idx = self.severity_combo.findData(data.get("severity"))
        if idx >= 0:
            self.severity_combo.setCurrentIndex(idx)

        self.clinical_effect_input.setPlainText(data.get("clinical_effect", "") or "")
        self.recommendation_input.setPlainText(data.get("recommendation", "") or "")
        self.management_plan_input.setPlainText(data.get("management_plan", "") or "")
        self.source_reference_input.setText(data.get("source_reference", "") or "")

        self._set_form_enabled(True)
        self.lbl_form_title.setText(f"تعديل قاعدة التداخل رقم ({interaction_id})")

    # ==========================================
    # العمليات
    # ==========================================
    def load_data(self):
        active_filter = self._get_selected_status_filter()

        if active_filter is True:
            data = self.dao.get_all_interactions(active_only=True)
        else:
            data = self.dao.get_all_interactions(active_only=False)

        if active_filter is False:
            data = [row for row in data if int(row[8]) == 0]

        self.fill_table(data)

    def search_data(self):
        text = self.search_input.text().strip()
        active_filter = self._get_selected_status_filter()

        if text:
            data = self.dao.search_interactions(text, active_only=(active_filter is True))
        else:
            data = self.dao.get_all_interactions(active_only=(active_filter is True))

        if active_filter is False:
            if text:
                data = self.dao.search_interactions(text, active_only=False)
            else:
                data = self.dao.get_all_interactions(active_only=False)
            data = [row for row in data if int(row[8]) == 0]

        self.fill_table(data)

    def fill_table(self, data):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            # row_data expected:
            # (id, ing1, ing2, severity, clinical_effect, recommendation,
            #  management_plan, source_reference, is_active, username, created_at, updated_at)
            interaction_id = row_data[0]
            ing1 = row_data[1]
            ing2 = row_data[2]
            raw_severity = row_data[3]
            clinical_effect = row_data[4]
            is_active = row_data[8]
            username = row_data[9] or "نظام"
            created_at = row_data[10] or ""

            items = [
                str(interaction_id),
                (ing1 or "").title(),
                (ing2 or "").title(),
                self._severity_display(raw_severity),
                self._status_display(is_active),
                clinical_effect or "",
                username,
                str(created_at)[:16]
            ]

            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)

                if col_idx != 5:
                    item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 3:
                    self._severity_style_item(item, raw_severity)

                if col_idx == 4:
                    item.setForeground(self._status_color(is_active))
                    item.setFont(QFont("Times New Roman", 13, QFont.Bold))

                if int(is_active) == 0:
                    if col_idx != 3:
                        item.setForeground(QColor("#7F8C8D"))

                self.table.setItem(row_idx, col_idx, item)

    def on_table_selection_changed(self):
        interaction_id = self._selected_interaction_id()

        if not interaction_id:
            self.details_text.clear()
            return

        data = self.dao.get_interaction_by_id(interaction_id)
        if not data:
            self.details_text.clear()
            return

        self.current_interaction_id = interaction_id
        self.current_is_active = int(data.get("is_active", 0))

        self.btn_toggle.setText("🚫 تعطيل القاعدة" if self.current_is_active == 1 else "🟢 تفعيل القاعدة")

        html = f"""
        <h3 style='color:#2C3E50;'>التداخل بين: {data.get("ingredient_1", "").title()} ↔ {data.get("ingredient_2", "").title()}</h3>
        <p><b>الخطورة:</b> {self._severity_display(data.get("severity", ""))}</p>
        <p><b>الحالة:</b> {self._status_display(data.get("is_active", 0))}</p>
        <hr>
        <p><b>الأثر السريري:</b><br>{data.get("clinical_effect", "") or "-"}</p>
        <p><b>التوصية:</b><br>{data.get("recommendation", "") or "-"}</p>
        <p><b>خطة الإدارة:</b><br>{data.get("management_plan", "") or "-"}</p>
        <p><b>المصدر المرجعي:</b><br>{data.get("source_reference", "") or "-"}</p>
        <hr>
        <p><b>تاريخ الإنشاء:</b> {data.get("created_at", "") or "-"}</p>
        <p><b>آخر تحديث:</b> {data.get("updated_at", "") or "-"}</p>
        """
        self.details_text.setHtml(html)

    def save_interaction(self):
        if self.user_role not in ["admin", "pharmacist"]:
            return

        ing1 = self.ing1_input.text().strip()
        ing2 = self.ing2_input.text().strip()
        severity = self.severity_combo.currentData()
        clinical_effect = self.clinical_effect_input.toPlainText().strip()
        recommendation = self.recommendation_input.toPlainText().strip()
        management_plan = self.management_plan_input.toPlainText().strip()
        source_reference = self.source_reference_input.text().strip()

        if not ing1 or not ing2 or not clinical_effect:
            QMessageBox.warning(
                self,
                "تنبيه",
                "حقول المادة الأولى والمادة الثانية والأثر السريري إلزامية."
            )
            return

        if self.current_mode == "edit" and self.current_interaction_id:
            success, msg = self.dao.update_interaction(
                requester_id=self.user_id,
                interaction_id=self.current_interaction_id,
                ingredient_1=ing1,
                ingredient_2=ing2,
                severity=severity,
                clinical_effect=clinical_effect,
                recommendation=recommendation,
                management_plan=management_plan,
                source_reference=source_reference
            )
        else:
            success, msg = self.dao.add_interaction(
                requester_id=self.user_id,
                ingredient_1=ing1,
                ingredient_2=ing2,
                severity=severity,
                clinical_effect=clinical_effect,
                recommendation=recommendation,
                management_plan=management_plan,
                source_reference=source_reference
            )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.search_data()
            self.reset_form()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)

    def toggle_selected_interaction(self):
        if self.user_role not in ["admin", "pharmacist"]:
            return

        interaction_id = self._selected_interaction_id()
        if not interaction_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد قاعدة من الجدول أولاً.")
            return

        data = self.dao.get_interaction_by_id(interaction_id)
        if not data:
            QMessageBox.warning(self, "تنبيه", "تعذر جلب بيانات القاعدة المحددة.")
            return

        current_status = int(data.get("is_active", 0))
        action_text = "تعطيل" if current_status == 1 else "تفعيل"

        reply = QMessageBox.question(
            self,
            f"تأكيد {action_text}",
            f"هل أنت متأكد من {action_text} قاعدة التداخل المحددة؟",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        success, msg = self.dao.toggle_interaction_status(
            requester_id=self.user_id,
            interaction_id=interaction_id,
            new_status=(0 if current_status == 1 else 1)
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.search_data()
            self.on_table_selection_changed()
        else:
            QMessageBox.critical(self, "فشل العملية", msg)

    def delete_selected(self):
        if self.user_role not in ["admin", "pharmacist"]:
            return

        interaction_id = self._selected_interaction_id()
        if not interaction_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد قاعدة من الجدول لحذفها.")
            return

        data = self.dao.get_interaction_by_id(interaction_id)
        if not data:
            QMessageBox.warning(self, "تنبيه", "تعذر جلب بيانات القاعدة المحددة.")
            return

        ing1 = (data.get("ingredient_1", "") or "").title()
        ing2 = (data.get("ingredient_2", "") or "").title()

        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف النهائي",
            f"هل أنت متأكد من حذف قاعدة التداخل بين:\n[{ing1}] و [{ing2}] ؟\n\n"
            "هذا حذف جذري من قاعدة المعرفة.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_interaction(self.user_id, interaction_id)
            if success:
                QMessageBox.information(self, "نجاح", msg)
                self.search_data()
                self.reset_form()
                self.details_text.clear()
            else:
                QMessageBox.critical(self, "فشل الحذف", msg)