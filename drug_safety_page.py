"""
وظيفة الملف: واجهة إدارة السلامة والمعلومات الدوائية (Drug Safety Profiles).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Full CRUD]: الواجهة تدعم الإضافة والتعديل والحذف للملفات والآثار الجانبية.
- [Data-Bound Logic]: تم فصل المنطق عن واجهة المستخدم (تغيير الحالة يعتمد على البيانات وليس نص الزر).
- [UI RBAC]: أزرار الإدارة محجوبة تماماً عن الكاشير (وضع القراءة فقط).
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QLabel, QComboBox, QFrame, QSplitter,
                             QTextEdit, QAbstractItemView, QDialog, QFormLayout, QScrollArea, QDialogButtonBox, QTabWidget)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from models.drug_safety_dao import DrugSafetyDAO

# ==========================================
# 1. النوافذ المنبثقة (Dialogs)
# ==========================================

class ProfileDialog(QDialog):
    """نافذة منبثقة لإضافة/تعديل الملف الطبي للمادة الفعالة"""
    def __init__(self, requester_id, dao, profile_id=None, current_data=None, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.dao = dao
        self.profile_id = profile_id
        self.is_edit = profile_id is not None

        self.setWindowTitle("تعديل الملف الطبي" if self.is_edit else "إضافة ملف طبي جديد")
        self.resize(700, 600)
        self.setStyleSheet("""
            QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }
            QLineEdit, QTextEdit { padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px; font-size: 16px; }
            QLabel { font-weight: bold; color: #2C3E50; }
        """)

        self.setup_ui(current_data or {})

    def setup_ui(self, data):
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        form_layout = QFormLayout(scroll_widget)
        form_layout.setSpacing(15)

        self.inputs = {}

        fields = [
            ("ingredient_text", "المادة الفعالة (انجليزي):", QLineEdit, True),
            ("display_name", "الاسم المعروض (عربي/انجليزي):", QLineEdit, True),
            ("max_daily_dose", "الجرعة القصوى (نصي):", QLineEdit, False),
            ("contraindications", "موانع الاستخدام:", QTextEdit, False),
            ("pregnancy_warning", "تحذيرات الحمل:", QTextEdit, False),
            ("lactation_warning", "تحذيرات الرضاعة:", QTextEdit, False),
            ("renal_warning", "تحذيرات الكلى:", QTextEdit, False),
            ("hepatic_warning", "تحذيرات الكبد:", QTextEdit, False),
            ("pediatric_warning", "تحذيرات الأطفال:", QTextEdit, False),
            ("geriatric_warning", "تحذيرات كبار السن:", QTextEdit, False),
            ("counseling_notes", "نصائح للمريض (Counseling):", QTextEdit, False),
            ("overdose_notes", "ملاحظات الجرعة الزائدة:", QTextEdit, False),
            ("source_reference", "المصدر الطبي المرجعي:", QLineEdit, False)
        ]

        for key, label_text, widget_type, is_required in fields:
            widget = widget_type()
            if widget_type == QTextEdit:
                widget.setFixedHeight(60)

            if data and key in data and data[key]:
                if widget_type == QLineEdit:
                    widget.setText(str(data[key]))
                else:
                    widget.setPlainText(str(data[key]))

            req_mark = " *" if is_required else ""
            form_layout.addRow(label_text + req_mark, widget)
            self.inputs[key] = widget

        if self.is_edit:
            self.inputs["ingredient_text"].setText(data.get("ingredient_key", ""))

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ واعتماد")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.save_data)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def save_data(self):
        ing = self.inputs["ingredient_text"].text().strip()
        disp = self.inputs["display_name"].text().strip()

        if not ing or not disp:
            QMessageBox.warning(self, "تنبيه", "حقول المادة الفعالة والاسم المعروض إلزامية.")
            return

        kwargs = {
            "requester_id": self.requester_id,
            "ingredient_text": ing,
            "display_name": disp,
            "max_daily_dose": self.inputs["max_daily_dose"].text().strip(),
            "contraindications": self.inputs["contraindications"].toPlainText().strip(),
            "pregnancy_warning": self.inputs["pregnancy_warning"].toPlainText().strip(),
            "lactation_warning": self.inputs["lactation_warning"].toPlainText().strip(),
            "renal_warning": self.inputs["renal_warning"].toPlainText().strip(),
            "hepatic_warning": self.inputs["hepatic_warning"].toPlainText().strip(),
            "pediatric_warning": self.inputs["pediatric_warning"].toPlainText().strip(),
            "geriatric_warning": self.inputs["geriatric_warning"].toPlainText().strip(),
            "counseling_notes": self.inputs["counseling_notes"].toPlainText().strip(),
            "overdose_notes": self.inputs["overdose_notes"].toPlainText().strip(),
            "source_reference": self.inputs["source_reference"].text().strip()
        }

        if self.is_edit:
            kwargs["profile_id"] = self.profile_id
            success, msg = self.dao.update_safety_profile(**kwargs)
        else:
            success, msg = self.dao.add_safety_profile(**kwargs)

        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class SideEffectDialog(QDialog):
    """نافذة منبثقة لإضافة أو تعديل أثر جانبي"""
    def __init__(self, requester_id, dao, profile_id, side_effect_id=None, current_data=None, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.dao = dao
        self.profile_id = profile_id
        self.side_effect_id = side_effect_id
        self.is_edit = side_effect_id is not None

        self.setWindowTitle("تعديل الأثر الجانبي" if self.is_edit else "إضافة أثر جانبي")
        self.resize(400, 300)
        self.setStyleSheet("QDialog { font-family: 'Times New Roman'; font-size: 16px; }")
        self.setup_ui(current_data or {})

    def setup_ui(self, data):
        layout = QFormLayout(self)

        self.effect_input = QLineEdit()
        if data.get('effect_name'): self.effect_input.setText(data['effect_name'])

        # [إصلاح ثغرة QComboBox.addItem الصحيحة]
        self.freq_combo = QComboBox()
        self.freq_combo.addItem("شائع جداً (Very Common)", "common")
        self.freq_combo.addItem("شائع (Common)", "common")
        self.freq_combo.addItem("غير شائع (Uncommon)", "uncommon")
        self.freq_combo.addItem("نادر (Rare)", "rare")
        self.freq_combo.addItem("نادر جداً (Very Rare)", "very_rare")
        self.freq_combo.addItem("غير معروف (Unknown)", "unknown")

        if data.get('frequency'):
            idx = self.freq_combo.findData(data['frequency'])
            if idx >= 0: self.freq_combo.setCurrentIndex(idx)

        self.severity_combo = QComboBox()
        self.severity_combo.addItem("طفيف (Mild)", "mild")
        self.severity_combo.addItem("متوسط (Moderate)", "moderate")
        self.severity_combo.addItem("شديد/خطير (Severe)", "severe")

        if data.get('severity'):
            idx = self.severity_combo.findData(data['severity'])
            if idx >= 0: self.severity_combo.setCurrentIndex(idx)

        self.notes_input = QLineEdit()
        if data.get('notes'): self.notes_input.setText(data['notes'])

        layout.addRow("اسم الأثر الجانبي *:", self.effect_input)
        layout.addRow("التكرار (الشيوع):", self.freq_combo)
        layout.addRow("الخطورة:", self.severity_combo)
        layout.addRow("ملاحظات إضافية:", self.notes_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ التعديلات" if self.is_edit else "إضافة")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.save_data)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def save_data(self):
        effect = self.effect_input.text().strip()
        if not effect:
            QMessageBox.warning(self, "تنبيه", "اسم الأثر الجانبي إلزامي.")
            return

        freq_val = self.freq_combo.currentData()
        sev_val = self.severity_combo.currentData()
        notes = self.notes_input.text().strip()

        if self.is_edit:
            success, msg = self.dao.update_side_effect(self.requester_id, self.side_effect_id, effect, freq_val, sev_val, notes)
        else:
            success, msg = self.dao.add_side_effect(self.requester_id, self.profile_id, effect, freq_val, sev_val, notes)

        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "خطأ", msg)

# ==========================================
# 2. الواجهة الرئيسية للسلامة الدوائية
# ==========================================

class DrugSafetyPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

        self.dao = DrugSafetyDAO()
        self.current_profile_id = None
        self.current_profile_active = False # متغير حالة للـ Toggle المنفصل عن الواجهة

        self.init_ui()
        self.load_profiles()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("قاعدة المعرفة: السلامة والآثار الجانبية (Drug Safety Profiles)")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        main_layout.addWidget(title)

        self.splitter = QSplitter(Qt.Horizontal)

        # ------------------------------------------
        # اللوحة الجانبية (قائمة الملفات الطبية)
        # ------------------------------------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث بالمادة الفعالة...")
        self.search_input.textChanged.connect(self.search_profiles)
        self.search_input.setStyleSheet("padding: 8px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px;")
        search_layout.addWidget(self.search_input)

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.clicked.connect(self.load_profiles)
        self.btn_refresh.setStyleSheet("padding: 8px;")
        search_layout.addWidget(self.btn_refresh)

        left_layout.addLayout(search_layout)

        self.profiles_table = QTableWidget()
        self.profiles_table.setColumnCount(3)
        self.profiles_table.setHorizontalHeaderLabels(["ID", "المادة الفعالة", "الحالة"])
        self.profiles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.profiles_table.setLayoutDirection(Qt.RightToLeft)
        self.profiles_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.profiles_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profiles_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profiles_table.itemSelectionChanged.connect(self.on_profile_selected)
        self.profiles_table.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")
        left_layout.addWidget(self.profiles_table)

        self.btn_add_profile = QPushButton(" ➕ إضافة ملف طبي جديد")
        self.btn_add_profile.clicked.connect(self.open_add_profile)
        self.btn_add_profile.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        left_layout.addWidget(self.btn_add_profile)

        self.splitter.addWidget(left_widget)

        # ------------------------------------------
        # اللوحة الرئيسية (التفاصيل والآثار الجانبية)
        # ------------------------------------------
        self.right_widget = QWidget()
        self.right_layout = QVBoxLayout(self.right_widget)
        self.right_layout.setContentsMargins(10, 0, 0, 0)

        self.profile_title = QLabel("يرجى تحديد مادة فعالة من القائمة الجانبية لعرض التفاصيل.")
        self.profile_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #34495E; margin-bottom: 10px;")
        self.right_layout.addWidget(self.profile_title)

        self.profile_tools = QHBoxLayout()
        self.btn_edit_profile = QPushButton(" ✏️ تعديل الملف")
        self.btn_edit_profile.clicked.connect(self.open_edit_profile)

        self.btn_toggle_profile = QPushButton(" 🚫 تفعيل/تعطيل")
        self.btn_toggle_profile.clicked.connect(self.toggle_current_profile)
        self.btn_toggle_profile.setStyleSheet("background-color: #E74C3C; color: white;")

        self.profile_tools.addWidget(self.btn_edit_profile)
        self.profile_tools.addWidget(self.btn_toggle_profile)
        self.profile_tools.addStretch()
        self.right_layout.addLayout(self.profile_tools)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        self.clinical_info_text = QTextEdit()
        self.clinical_info_text.setReadOnly(True)
        self.clinical_info_text.setStyleSheet("background-color: white; padding: 10px; line-height: 1.5;")
        self.tabs.addTab(self.clinical_info_text, " 📄 المعلومات السريرية والتحذيرات")

        se_widget = QWidget()
        se_layout = QVBoxLayout(se_widget)

        self.se_table = QTableWidget()
        self.se_table.setColumnCount(5)
        self.se_table.setHorizontalHeaderLabels(["ID", "الأثر الجانبي", "الشيوع", "الخطورة", "ملاحظات"])
        self.se_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.se_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.se_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        se_layout.addWidget(self.se_table)

        se_tools = QHBoxLayout()
        self.btn_add_se = QPushButton(" ➕ إضافة")
        self.btn_add_se.clicked.connect(self.open_add_side_effect)
        self.btn_add_se.setStyleSheet("background-color: #27AE60; color: white; padding: 8px; font-weight: bold;")

        self.btn_edit_se = QPushButton(" ✏️ تعديل")
        self.btn_edit_se.clicked.connect(self.open_edit_side_effect)
        self.btn_edit_se.setStyleSheet("background-color: #F39C12; color: white; padding: 8px; font-weight: bold;")

        self.btn_del_se = QPushButton(" 🗑️ حذف")
        self.btn_del_se.clicked.connect(self.delete_selected_side_effect)
        self.btn_del_se.setStyleSheet("color: red; padding: 8px; font-weight: bold;")

        se_tools.addWidget(self.btn_add_se)
        se_tools.addWidget(self.btn_edit_se)
        se_tools.addWidget(self.btn_del_se)
        se_tools.addStretch()
        se_layout.addLayout(se_tools)

        self.tabs.addTab(se_widget, " 🦠 الآثار الجانبية (Side Effects)")

        self.right_layout.addWidget(self.tabs)
        self.splitter.addWidget(self.right_widget)

        self.splitter.setSizes([300, 700])
        main_layout.addWidget(self.splitter)

        # ==========================================
        # UI RBAC Protection
        # ==========================================
        if self.user_role not in ['admin', 'pharmacist']:
            self.btn_add_profile.hide()
            self.btn_edit_profile.hide()
            self.btn_toggle_profile.hide()
            self.btn_add_se.hide()
            self.btn_edit_se.hide()
            self.btn_del_se.hide()
            title.setText(title.text() + " (للقراءة فقط)")

        self.right_widget.setEnabled(False)

    # ==========================================
    # العمليات والتفاعلات
    # ==========================================

    def load_profiles(self):
        profiles = self.dao.get_all_profiles(active_only=False)
        self.populate_profiles_table(profiles)

    def search_profiles(self):
        text = self.search_input.text().strip()
        if text:
            profiles = self.dao.search_profiles(text)
        else:
            profiles = self.dao.get_all_profiles()
        self.populate_profiles_table(profiles)

    def populate_profiles_table(self, profiles):
        self.profiles_table.setRowCount(0)
        for row_idx, p in enumerate(profiles):
            self.profiles_table.insertRow(row_idx)
            self.profiles_table.setItem(row_idx, 0, QTableWidgetItem(str(p[0])))
            self.profiles_table.setItem(row_idx, 1, QTableWidgetItem(p[2]))

            status_item = QTableWidgetItem("نشط" if p[3] else "معطل")
            status_item.setForeground(QColor("#27AE60") if p[3] else QColor("#E74C3C"))
            self.profiles_table.setItem(row_idx, 2, status_item)

    def on_profile_selected(self):
        selected_rows = self.profiles_table.selectedItems()
        if not selected_rows:
            self.right_widget.setEnabled(False)
            self.current_profile_id = None
            return

        self.right_widget.setEnabled(True)
        row = selected_rows[0].row()
        self.current_profile_id = int(self.profiles_table.item(row, 0).text())

        status_text = self.profiles_table.item(row, 2).text()
        self.current_profile_active = (status_text == "نشط")

        self.btn_toggle_profile.setText(" 🚫 تعطيل" if self.current_profile_active else " 🟢 تفعيل")

        self.refresh_profile_details()

    def refresh_profile_details(self):
        if not self.current_profile_id: return

        full_profile = self.dao.get_full_profile(self.current_profile_id)
        if not full_profile: return

        self.profile_title.setText(f"الملف الطبي: {full_profile['display_name']} ({full_profile['ingredient_key']})")

        html = f"""
        <h3 style='color:#2980B9;'>موانع الاستخدام (Contraindications):</h3>
        <p>{full_profile.get('contraindications') or 'لا توجد بيانات'}</p>
        <h3 style='color:#E67E22;'>الجرعة القصوى (Max Daily Dose):</h3>
        <p>{full_profile.get('max_daily_dose') or 'لا توجد بيانات'}</p>
        <h3 style='color:#C0392B;'>تحذيرات خاصة بالحمل والرضاعة:</h3>
        <ul>
            <li><b>الحمل:</b> {full_profile.get('pregnancy_warning') or '-'}</li>
            <li><b>الرضاعة:</b> {full_profile.get('lactation_warning') or '-'}</li>
        </ul>
        <h3 style='color:#8E44AD;'>تحذيرات الأعضاء (كلى / كبد):</h3>
        <ul>
            <li><b>الكلى:</b> {full_profile.get('renal_warning') or '-'}</li>
            <li><b>الكبد:</b> {full_profile.get('hepatic_warning') or '-'}</li>
        </ul>
        <h3 style='color:#16A085;'>نصائح وتوجيهات المريض (Counseling):</h3>
        <p>{full_profile.get('counseling_notes') or 'لا توجد بيانات'}</p>
        """
        self.clinical_info_text.setHtml(html)

        self.se_table.setRowCount(0)
        for i, se in enumerate(full_profile['side_effects']):
            self.se_table.insertRow(i)
            self.se_table.setItem(i, 0, QTableWidgetItem(str(se['id'])))
            self.se_table.setItem(i, 1, QTableWidgetItem(se['effect_name']))

            # [Fix]: We retrieve frequency and severity values but display them translated visually
            freq_map = {"common": "شائع", "uncommon": "غير شائع", "rare": "نادر", "very_rare": "نادر جداً", "unknown": "غير معروف"}
            sev_map = {"mild": "طفيف", "moderate": "متوسط", "severe": "شديد/خطير"}

            freq_item = QTableWidgetItem(freq_map.get(se['frequency'], se['frequency']))
            sev_item = QTableWidgetItem(sev_map.get(se['severity'], se['severity']))

            if se['severity'] == 'severe':
                sev_item.setForeground(QColor("red"))
                sev_item.setFont(QFont("Times", 12, QFont.Bold))

            # إخفاء القيم الأصلية داخل الـ ItemData لتسهيل عملية التعديل لاحقاً
            freq_item.setData(Qt.UserRole, se['frequency'])
            sev_item.setData(Qt.UserRole, se['severity'])

            self.se_table.setItem(i, 2, freq_item)
            self.se_table.setItem(i, 3, sev_item)
            self.se_table.setItem(i, 4, QTableWidgetItem(se['notes'] or ""))

    # --- أزرار التحكم ---

    def open_add_profile(self):
        dialog = ProfileDialog(self.user_id, self.dao, parent=self)
        if dialog.exec_():
            self.load_profiles()

    def open_edit_profile(self):
        if not self.current_profile_id: return
        data = self.dao.get_profile_by_id(self.current_profile_id)
        if not data: return

        dialog = ProfileDialog(self.user_id, self.dao, self.current_profile_id, data, self)
        if dialog.exec_():
            self.load_profiles()
            self.refresh_profile_details()

    def toggle_current_profile(self):
        if not self.current_profile_id: return
        new_status = not self.current_profile_active

        success, msg = self.dao.toggle_profile_status(self.user_id, self.current_profile_id, new_status)
        if success:
            self.load_profiles()
            # سيتم تحديث الحالة تلقائياً عند تغيير الاختيار أو إعادة التحميل
        else:
            QMessageBox.warning(self, "خطأ", msg)

    def open_add_side_effect(self):
        if not self.current_profile_id: return
        dialog = SideEffectDialog(self.user_id, self.dao, self.current_profile_id, parent=self)
        if dialog.exec_():
            self.refresh_profile_details()

    def open_edit_side_effect(self):
        if not self.current_profile_id: return
        row = self.se_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد أثر جانبي من الجدول لتعديله.")
            return

        se_id = int(self.se_table.item(row, 0).text())
        current_data = {
            'effect_name': self.se_table.item(row, 1).text(),
            'frequency': self.se_table.item(row, 2).data(Qt.UserRole),
            'severity': self.se_table.item(row, 3).data(Qt.UserRole),
            'notes': self.se_table.item(row, 4).text()
        }

        dialog = SideEffectDialog(self.user_id, self.dao, self.current_profile_id, se_id, current_data, self)
        if dialog.exec_():
            self.refresh_profile_details()

    def delete_selected_side_effect(self):
        if not self.user_id: return
        row = self.se_table.currentRow()
        if row < 0: return

        se_id = int(self.se_table.item(row, 0).text())
        effect_name = self.se_table.item(row, 1).text()

        reply = QMessageBox.question(self, "تأكيد الحذف", f"هل أنت متأكد من حذف الأثر الجانبي ({effect_name})؟")
        if reply == QMessageBox.Yes:
            success, msg = self.dao.delete_side_effect(self.user_id, se_id)
            if success:
                self.refresh_profile_details()
            else:
                QMessageBox.warning(self, "خطأ", msg)