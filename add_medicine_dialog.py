"""
وظيفة الملف: نوافذ الإضافة والتعديل الأساسي للأدوية.
الطبقة: Presentation Layer
ملاحظة معمارية وسريرية:
- [Data Integrity]&#58; إجبار المستخدم على اختيار الشكل الصيدلاني لمنع تلوث البيانات القديمة.
- [Canonical Guidance]&#58; توجيه بصري للمستخدمين لإدخال المادة الفعالة والتركيز بصيغة قياسية.
- [V11 Update]&#58; دمج حقول (الأدوية المخدرة والرقابية) مع تفعيل/تعطيل بصري وشرط إلزامي.
- [V13 Update]&#58; دمج حقول (المواد الخطرة ☣️) مع تفعيل/تعطيل بصري وإلزام المستخدم بفئة الخطورة للتحذير التشغيلي.
- [UI Hardening]&#58; دعم التمرير العمودي، وإظهار الحقول الإلزامية بعلامة حمراء، وتمييز الحقول الناقصة بصرياً.
- يمرر (user_id) لفرض الـ Deep RBAC في النواة.
"""

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from models.medicine_dao import MedicineDAO


def build_required_label(text: str) -> QLabel:
    label = QLabel(f"{text} <span style='color:#E74C3C;'>*</span>:")
    label.setTextFormat(Qt.RichText)
    return label


def default_field_style() -> str:
    return """
        QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {
            height: 40px;
            font-size: 16px;
            padding: 5px;
            border-radius: 5px;
            border: 1px solid #BDC3C7;
            background-color: white;
        }
    """


def invalid_field_style() -> str:
    return """
        QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {
            height: 40px;
            font-size: 16px;
            padding: 5px;
            border-radius: 5px;
            border: 2px solid #E74C3C;
            background-color: #FDEDEC;
        }
    """


class AddMedicineDialog(QDialog):
    def __init__(self, session_data, parent=None):
        super().__init__(parent)
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.dao = MedicineDAO()

        self.setWindowTitle("إضافة دواء جديد")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(620, screen.width() - 120), min(780, screen.height() - 120))
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setSizeGripEnabled(True)
        self.setStyleSheet("""
            QDialog {
                font-family: 'Times New Roman';
                font-size: 16px;
                background-color: #F5F6FA;
            }
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2C3E50;
            }
            QPushButton {
                height: 40px;
                font-size: 16px;
                font-weight: bold;
            }
        """)

        self.setup_ui()
        self.load_suppliers()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("امسح الباركود...")
        self.barcode_input.setStyleSheet(default_field_style())

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم الدواء (التجاري)")
        self.name_input.setStyleSheet(default_field_style())

        self.active_ing_input = QLineEdit()
        self.active_ing_input.setPlaceholderText("مثال: Paracetamol (بدون إضافات لتطابق دقيق)")
        self.active_ing_input.setStyleSheet(default_field_style())

        self.dosage_form_combo = QComboBox()
        self.dosage_form_combo.setStyleSheet(default_field_style())
        self.dosage_form_combo.addItem("-- اختر الشكل الصيدلاني --", "")
        forms = [
            "Tablet", "Capsule", "Syrup", "Suspension", "Injection",
            "Cream", "Ointment", "Drops", "Suppository", "Inhaler",
            "Powder", "Other"
        ]
        for item in forms:
            self.dosage_form_combo.addItem(item, item)

        self.strength_input = QLineEdit()
        self.strength_input.setPlaceholderText("مثال: 500 mg, 1 %, 250 mg/5 ml (مع ترك مسافة)")
        self.strength_input.setStyleSheet(default_field_style())

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("وصف إضافي أو استخدامات...")
        self.desc_input.setStyleSheet(default_field_style())

        self.supplier_combo = QComboBox()
        self.supplier_combo.setStyleSheet(default_field_style())
        self.supplier_combo.addItem("بدون مورد محدد", None)

        self.buy_price_input = QDoubleSpinBox()
        self.buy_price_input.setMaximum(1000000)
        self.buy_price_input.setDecimals(2)
        self.buy_price_input.setStyleSheet(default_field_style())

        self.sell_price_input = QDoubleSpinBox()
        self.sell_price_input.setMaximum(1000000)
        self.sell_price_input.setDecimals(2)
        self.sell_price_input.setStyleSheet(default_field_style())

        self.qty_input = QSpinBox()
        self.qty_input.setMaximum(100000)
        self.qty_input.setToolTip("إذا كانت الكمية 0 لن يتم إنشاء تشغيلة افتتاحية")
        self.qty_input.setStyleSheet(default_field_style())

        self.min_stock_input = QSpinBox()
        self.min_stock_input.setMaximum(100000)
        self.min_stock_input.setValue(10)
        self.min_stock_input.setStyleSheet(default_field_style())

        self.expiry_input = QDateEdit()
        self.expiry_input.setDate(QDate.currentDate().addDays(365))
        self.expiry_input.setCalendarPopup(True)
        self.expiry_input.setStyleSheet(default_field_style())

        form_layout.addRow(build_required_label("الباركود"), self.barcode_input)
        form_layout.addRow(build_required_label("اسم الدواء"), self.name_input)
        form_layout.addRow(build_required_label("المادة الفعالة"), self.active_ing_input)
        form_layout.addRow(build_required_label("الشكل الصيدلاني"), self.dosage_form_combo)
        form_layout.addRow(build_required_label("التركيز/العيار"), self.strength_input)
        form_layout.addRow("الوصف:", self.desc_input)
        form_layout.addRow("المورد الافتراضي:", self.supplier_combo)
        form_layout.addRow("سعر الشراء:", self.buy_price_input)
        form_layout.addRow("سعر البيع:", self.sell_price_input)
        form_layout.addRow("الكمية الافتتاحية:", self.qty_input)
        form_layout.addRow("حد التنبيه (نواقص):", self.min_stock_input)
        form_layout.addRow("تاريخ الانتهاء:", self.expiry_input)

        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet("""
            background-color: #FDEDEC;
            border: 1px solid #E74C3C;
            border-radius: 5px;
            padding: 5px;
        """)
        ctrl_layout = QFormLayout(ctrl_frame)
        ctrl_layout.setSpacing(10)

        self.is_controlled_cb = QCheckBox("تصنيف كدواء رقابي / مخدر (Controlled Drug)")
        self.is_controlled_cb.setStyleSheet("color: #C0392B; font-weight: bold; font-size: 16px;")
        self.is_controlled_cb.stateChanged.connect(self.toggle_controlled_fields)

        self.controlled_class_input = QLineEdit()
        self.controlled_class_input.setPlaceholderText("فئة الدواء (مثال: Schedule II، جدول أول)")
        self.controlled_class_input.setEnabled(False)
        self.controlled_class_input.setStyleSheet(default_field_style())

        self.controlled_notes_input = QLineEdit()
        self.controlled_notes_input.setPlaceholderText("ملاحظات تنظيمية وشروط صرف إضافية...")
        self.controlled_notes_input.setEnabled(False)
        self.controlled_notes_input.setStyleSheet(default_field_style())

        ctrl_layout.addRow(self.is_controlled_cb)
        ctrl_layout.addRow(build_required_label("الفئة الرقابية"), self.controlled_class_input)
        ctrl_layout.addRow("ملاحظات:", self.controlled_notes_input)

        form_layout.addRow(ctrl_frame)

        haz_frame = QFrame()
        haz_frame.setStyleSheet("""
            background-color: #FEF9E7;
            border: 1px solid #F39C12;
            border-radius: 5px;
            padding: 5px;
        """)
        haz_layout = QFormLayout(haz_frame)
        haz_layout.setSpacing(10)

        self.is_hazardous_cb = QCheckBox("تصنيف كمادة خطرة ☣️ (Hazardous Material)")
        self.is_hazardous_cb.setStyleSheet("color: #D35400; font-weight: bold; font-size: 16px;")
        self.is_hazardous_cb.stateChanged.connect(self.toggle_hazardous_fields)

        self.hazard_class_input = QLineEdit()
        self.hazard_class_input.setPlaceholderText("فئة الخطورة (مثال: toxic, flammable, cytotoxic)")
        self.hazard_class_input.setEnabled(False)
        self.hazard_class_input.setStyleSheet(default_field_style())

        self.hazard_notes_input = QLineEdit()
        self.hazard_notes_input.setPlaceholderText("تعليمات التداول والسلامة والتخزين...")
        self.hazard_notes_input.setEnabled(False)
        self.hazard_notes_input.setStyleSheet(default_field_style())

        haz_layout.addRow(self.is_hazardous_cb)
        haz_layout.addRow(build_required_label("فئة الخطورة"), self.hazard_class_input)
        haz_layout.addRow("تعليمات السلامة:", self.hazard_notes_input)

        form_layout.addRow(haz_frame)

        layout.addLayout(form_layout)

        warning_lbl = QLabel("⚠️ دقة (المادة الفعالة، الشكل، والتركيز) ضروري لعمل البدائل الدوائية.")
        warning_lbl.setStyleSheet("color: #2980B9; font-size: 14px; font-style: italic; margin-bottom: 10px;")
        warning_lbl.setWordWrap(True)
        layout.addWidget(warning_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ واعتماد")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet("background-color: #27AE60; color: white;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.save_medicine)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def toggle_controlled_fields(self):
        is_checked = self.is_controlled_cb.isChecked()
        self.controlled_class_input.setEnabled(is_checked)
        self.controlled_notes_input.setEnabled(is_checked)
        if not is_checked:
            self.controlled_class_input.clear()
            self.controlled_notes_input.clear()
            self.clear_field_mark(self.controlled_class_input)

    def toggle_hazardous_fields(self):
        is_checked = self.is_hazardous_cb.isChecked()
        self.hazard_class_input.setEnabled(is_checked)
        self.hazard_notes_input.setEnabled(is_checked)
        if not is_checked:
            self.hazard_class_input.clear()
            self.hazard_notes_input.clear()
            self.clear_field_mark(self.hazard_class_input)

    def load_suppliers(self):
        suppliers = self.dao.get_active_suppliers()
        for sup_id, sup_name in suppliers:
            self.supplier_combo.addItem(sup_name, sup_id)

    def mark_field_invalid(self, widget):
        widget.setStyleSheet(invalid_field_style())

    def clear_field_mark(self, widget):
        widget.setStyleSheet(default_field_style())

    def clear_validation_marks(self):
        widgets = [
            self.barcode_input,
            self.name_input,
            self.active_ing_input,
            self.dosage_form_combo,
            self.strength_input,
            self.controlled_class_input,
            self.hazard_class_input
        ]
        for widget in widgets:
            self.clear_field_mark(widget)

    def save_medicine(self):
        if not self.user_id:
            QMessageBox.critical(self, "خطأ أمني", "المستخدم غير محدد! يرجى إعادة تسجيل الدخول.")
            return

        self.clear_validation_marks()

        barcode = self.barcode_input.text().strip()
        name = self.name_input.text().strip()
        active_ing = self.active_ing_input.text().strip()
        dosage_form = self.dosage_form_combo.currentData()
        strength = self.strength_input.text().strip()
        supplier_id = self.supplier_combo.currentData()
        description = self.desc_input.text().strip()

        buy_price = self.buy_price_input.value()
        sell_price = self.sell_price_input.value()
        qty = self.qty_input.value()
        min_stock = self.min_stock_input.value()
        expiry = self.expiry_input.date().toString("yyyy-MM-dd")

        is_controlled = 1 if self.is_controlled_cb.isChecked() else 0
        controlled_class = self.controlled_class_input.text().strip()
        controlled_notes = self.controlled_notes_input.text().strip()

        is_hazardous = 1 if self.is_hazardous_cb.isChecked() else 0
        hazard_class = self.hazard_class_input.text().strip()
        hazard_notes = self.hazard_notes_input.text().strip()

        invalid = False

        if not barcode:
            self.mark_field_invalid(self.barcode_input)
            invalid = True

        if not name:
            self.mark_field_invalid(self.name_input)
            invalid = True

        if not active_ing:
            self.mark_field_invalid(self.active_ing_input)
            invalid = True

        if not dosage_form:
            self.mark_field_invalid(self.dosage_form_combo)
            invalid = True

        if not strength:
            self.mark_field_invalid(self.strength_input)
            invalid = True

        if invalid:
            QMessageBox.warning(self, "تنبيه", "جميع الحقول الإلزامية يجب تعبئتها.")
            return

        if is_controlled == 1 and not controlled_class:
            self.mark_field_invalid(self.controlled_class_input)
            QMessageBox.warning(self, "تنبيه رقابي", "يجب إدخال الفئة الرقابية بشكل إلزامي.")
            return

        if is_hazardous == 1 and not hazard_class:
            self.mark_field_invalid(self.hazard_class_input)
            QMessageBox.warning(self, "تنبيه تشغيلي", "يجب إدخال فئة الخطورة بشكل إلزامي.")
            return

        success, message = self.dao.add_medicine(
            barcode,
            name,
            active_ing,
            dosage_form,
            strength,
            buy_price,
            sell_price,
            qty,
            expiry,
            self.user_id,
            supplier_id,
            description=description,
            min_stock_alert=min_stock,
            is_controlled=is_controlled,
            controlled_class=controlled_class,
            controlled_notes=controlled_notes,
            is_hazardous=is_hazardous,
            hazard_class=hazard_class,
            hazard_notes=hazard_notes
        )

        if success:
            QMessageBox.information(self, "نجاح", message)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", message)


class EditMedicineDialog(QDialog):
    def __init__(self, session_data, medicine_id, parent=None):
        super().__init__(parent)
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.medicine_id = medicine_id
        self.dao = MedicineDAO()

        self.setWindowTitle("تعديل البيانات الأساسية للدواء")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(620, screen.width() - 120), min(780, screen.height() - 120))
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setSizeGripEnabled(True)
        self.setStyleSheet("""
            QDialog {
                font-family: 'Times New Roman';
                font-size: 16px;
                background-color: #F5F6FA;
            }
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2C3E50;
            }
            QPushButton {
                height: 40px;
                font-size: 16px;
                font-weight: bold;
            }
        """)

        self.setup_ui()
        self.load_suppliers()
        self.load_current_data()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.barcode_input = QLineEdit()
        self.barcode_input.setStyleSheet(default_field_style())

        self.name_input = QLineEdit()
        self.name_input.setStyleSheet(default_field_style())

        self.active_ing_input = QLineEdit()
        self.active_ing_input.setStyleSheet(default_field_style())

        self.dosage_form_combo = QComboBox()
        self.dosage_form_combo.setStyleSheet(default_field_style())
        self.dosage_form_combo.addItem("-- اختر الشكل الصيدلاني --", "")
        forms = [
            "Tablet", "Capsule", "Syrup", "Suspension", "Injection",
            "Cream", "Ointment", "Drops", "Suppository", "Inhaler",
            "Powder", "Other"
        ]
        for item in forms:
            self.dosage_form_combo.addItem(item, item)

        self.strength_input = QLineEdit()
        self.strength_input.setPlaceholderText("مثال: 500 mg, 1 %, 250 mg/5 ml")
        self.strength_input.setStyleSheet(default_field_style())

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("وصف إضافي أو استخدامات...")
        self.desc_input.setStyleSheet(default_field_style())

        self.supplier_combo = QComboBox()
        self.supplier_combo.setStyleSheet(default_field_style())
        self.supplier_combo.addItem("بدون مورد محدد", None)

        self.buy_price_input = QDoubleSpinBox()
        self.buy_price_input.setMaximum(1000000)
        self.buy_price_input.setDecimals(2)
        self.buy_price_input.setStyleSheet(default_field_style())

        self.sell_price_input = QDoubleSpinBox()
        self.sell_price_input.setMaximum(1000000)
        self.sell_price_input.setDecimals(2)
        self.sell_price_input.setStyleSheet(default_field_style())

        self.min_stock_input = QSpinBox()
        self.min_stock_input.setMaximum(100000)
        self.min_stock_input.setStyleSheet(default_field_style())

        form_layout.addRow(build_required_label("الباركود"), self.barcode_input)
        form_layout.addRow(build_required_label("اسم الدواء"), self.name_input)
        form_layout.addRow(build_required_label("المادة الفعالة"), self.active_ing_input)
        form_layout.addRow(build_required_label("الشكل الصيدلاني"), self.dosage_form_combo)
        form_layout.addRow(build_required_label("التركيز/العيار"), self.strength_input)
        form_layout.addRow("الوصف:", self.desc_input)
        form_layout.addRow("المورد:", self.supplier_combo)
        form_layout.addRow("سعر الشراء:", self.buy_price_input)
        form_layout.addRow("سعر البيع:", self.sell_price_input)
        form_layout.addRow("حد التنبيه (نواقص):", self.min_stock_input)

        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet("""
            background-color: #FDEDEC;
            border: 1px solid #E74C3C;
            border-radius: 5px;
            padding: 5px;
        """)
        ctrl_layout = QFormLayout(ctrl_frame)
        ctrl_layout.setSpacing(10)

        self.is_controlled_cb = QCheckBox("تصنيف كدواء رقابي / مخدر (Controlled Drug)")
        self.is_controlled_cb.setStyleSheet("color: #C0392B; font-weight: bold; font-size: 16px;")
        self.is_controlled_cb.stateChanged.connect(self.toggle_controlled_fields)

        self.controlled_class_input = QLineEdit()
        self.controlled_class_input.setPlaceholderText("فئة الدواء (مثال: Schedule II)")
        self.controlled_class_input.setEnabled(False)
        self.controlled_class_input.setStyleSheet(default_field_style())

        self.controlled_notes_input = QLineEdit()
        self.controlled_notes_input.setPlaceholderText("ملاحظات تنظيمية...")
        self.controlled_notes_input.setEnabled(False)
        self.controlled_notes_input.setStyleSheet(default_field_style())

        ctrl_layout.addRow(self.is_controlled_cb)
        ctrl_layout.addRow(build_required_label("الفئة الرقابية"), self.controlled_class_input)
        ctrl_layout.addRow("ملاحظات:", self.controlled_notes_input)

        form_layout.addRow(ctrl_frame)

        haz_frame = QFrame()
        haz_frame.setStyleSheet("""
            background-color: #FEF9E7;
            border: 1px solid #F39C12;
            border-radius: 5px;
            padding: 5px;
        """)
        haz_layout = QFormLayout(haz_frame)
        haz_layout.setSpacing(10)

        self.is_hazardous_cb = QCheckBox("تصنيف كمادة خطرة ☣️ (Hazardous Material)")
        self.is_hazardous_cb.setStyleSheet("color: #D35400; font-weight: bold; font-size: 16px;")
        self.is_hazardous_cb.stateChanged.connect(self.toggle_hazardous_fields)

        self.hazard_class_input = QLineEdit()
        self.hazard_class_input.setPlaceholderText("فئة الخطورة (مثال: toxic, flammable, cytotoxic)")
        self.hazard_class_input.setEnabled(False)
        self.hazard_class_input.setStyleSheet(default_field_style())

        self.hazard_notes_input = QLineEdit()
        self.hazard_notes_input.setPlaceholderText("تعليمات التداول والسلامة والتخزين...")
        self.hazard_notes_input.setEnabled(False)
        self.hazard_notes_input.setStyleSheet(default_field_style())

        haz_layout.addRow(self.is_hazardous_cb)
        haz_layout.addRow(build_required_label("فئة الخطورة"), self.hazard_class_input)
        haz_layout.addRow("تعليمات السلامة:", self.hazard_notes_input)

        form_layout.addRow(haz_frame)

        layout.addLayout(form_layout)

        info_lbl = QLabel("* تغيير التصنيف الرقابي/الخطر سيتم توثيقه بالكامل في سجلات التدقيق.")
        info_lbl.setStyleSheet("color: #7F8C8D; font-size: 14px; font-style: italic;")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ التعديلات")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet("background-color: #F39C12; color: white;")
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        self.buttons.accepted.connect(self.save_edits)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def toggle_controlled_fields(self):
        is_checked = self.is_controlled_cb.isChecked()
        self.controlled_class_input.setEnabled(is_checked)
        self.controlled_notes_input.setEnabled(is_checked)
        if not is_checked:
            self.controlled_class_input.clear()
            self.controlled_notes_input.clear()
            self.clear_field_mark(self.controlled_class_input)

    def toggle_hazardous_fields(self):
        is_checked = self.is_hazardous_cb.isChecked()
        self.hazard_class_input.setEnabled(is_checked)
        self.hazard_notes_input.setEnabled(is_checked)
        if not is_checked:
            self.hazard_class_input.clear()
            self.hazard_notes_input.clear()
            self.clear_field_mark(self.hazard_class_input)

    def load_suppliers(self):
        suppliers = self.dao.get_active_suppliers()
        for sup_id, sup_name in suppliers:
            self.supplier_combo.addItem(sup_name, sup_id)

    def mark_field_invalid(self, widget):
        widget.setStyleSheet(invalid_field_style())

    def clear_field_mark(self, widget):
        widget.setStyleSheet(default_field_style())

    def clear_validation_marks(self):
        widgets = [
            self.barcode_input,
            self.name_input,
            self.active_ing_input,
            self.dosage_form_combo,
            self.strength_input,
            self.controlled_class_input,
            self.hazard_class_input
        ]
        for widget in widgets:
            self.clear_field_mark(widget)

    def load_current_data(self):
        data = self.dao.get_medicine_info(self.medicine_id)
        if not data:
            QMessageBox.critical(self, "خطأ", "تعذر تحميل بيانات الدواء.")
            self.reject()
            return

        self.barcode_input.setText(data[0] if data[0] else "")
        self.name_input.setText(data[1] if data[1] else "")
        self.active_ing_input.setText(data[2] if data[2] else "")

        if data[3] is not None:
            index = self.supplier_combo.findData(data[3])
            if index >= 0:
                self.supplier_combo.setCurrentIndex(index)

        if data[4]:
            index = self.dosage_form_combo.findData(data[4])
            self.dosage_form_combo.setCurrentIndex(index if index >= 0 else 0)

        self.strength_input.setText(data[5] if data[5] else "")

        is_ctrl = int(data[6]) if data[6] is not None else 0
        self.is_controlled_cb.setChecked(is_ctrl == 1)
        self.controlled_class_input.setText(data[7] if data[7] else "")
        self.controlled_notes_input.setText(data[8] if data[8] else "")

        if len(data) >= 12:
            is_haz = int(data[9]) if data[9] is not None else 0
            self.is_hazardous_cb.setChecked(is_haz == 1)
            self.hazard_class_input.setText(data[10] if data[10] else "")
            self.hazard_notes_input.setText(data[11] if data[11] else "")

        if len(data) >= 16:
            self.desc_input.setText(data[12] if data[12] else "")
            self.min_stock_input.setValue(int(data[13]) if data[13] is not None else 10)
            self.buy_price_input.setValue(float(data[14]) if data[14] is not None else 0.0)
            self.sell_price_input.setValue(float(data[15]) if data[15] is not None else 0.0)

    def save_edits(self):
        if not self.user_id:
            QMessageBox.critical(self, "خطأ أمني", "المستخدم غير محدد!")
            return

        self.clear_validation_marks()

        barcode = self.barcode_input.text().strip()
        name = self.name_input.text().strip()
        active_ing = self.active_ing_input.text().strip()
        dosage_form = self.dosage_form_combo.currentData()
        strength = self.strength_input.text().strip()
        supplier_id = self.supplier_combo.currentData()
        description = self.desc_input.text().strip()

        buy_price = self.buy_price_input.value()
        sell_price = self.sell_price_input.value()
        min_stock = self.min_stock_input.value()

        is_controlled = 1 if self.is_controlled_cb.isChecked() else 0
        controlled_class = self.controlled_class_input.text().strip()
        controlled_notes = self.controlled_notes_input.text().strip()

        is_hazardous = 1 if self.is_hazardous_cb.isChecked() else 0
        hazard_class = self.hazard_class_input.text().strip()
        hazard_notes = self.hazard_notes_input.text().strip()

        invalid = False

        if not barcode:
            self.mark_field_invalid(self.barcode_input)
            invalid = True

        if not name:
            self.mark_field_invalid(self.name_input)
            invalid = True

        if not active_ing:
            self.mark_field_invalid(self.active_ing_input)
            invalid = True

        if not dosage_form:
            self.mark_field_invalid(self.dosage_form_combo)
            invalid = True

        if not strength:
            self.mark_field_invalid(self.strength_input)
            invalid = True

        if invalid:
            QMessageBox.warning(self, "تنبيه", "جميع الحقول الإلزامية يجب تعبئتها.")
            return

        if is_controlled == 1 and not controlled_class:
            self.mark_field_invalid(self.controlled_class_input)
            QMessageBox.warning(self, "تنبيه رقابي", "يجب إدخال الفئة الرقابية بشكل إلزامي.")
            return

        if is_hazardous == 1 and not hazard_class:
            self.mark_field_invalid(self.hazard_class_input)
            QMessageBox.warning(self, "تنبيه تشغيلي", "يجب إدخال فئة الخطورة بشكل إلزامي.")
            return

        success, message = self.dao.update_medicine_info(
            self.medicine_id,
            barcode,
            name,
            active_ing,
            dosage_form,
            strength,
            supplier_id,
            self.user_id,
            buy_price,
            sell_price,
            description,
            min_stock,
            is_controlled=is_controlled,
            controlled_class=controlled_class,
            controlled_notes=controlled_notes,
            is_hazardous=is_hazardous,
            hazard_class=hazard_class,
            hazard_notes=hazard_notes
        )

        if success:
            QMessageBox.information(self, "نجاح", message)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", message)