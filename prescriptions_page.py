"""
وظيفة الملف: واجهة إدارة الوصفات الطبية الإلكترونية (E-Prescriptions Page).
الطبقة: Presentation Layer

ملاحظة معمارية:
- [Dumb Client]&#58; الواجهة لا تتخذ أي قرار أمني أو منطقي بمفردها.
- [CDSS Integration - Level 1]&#58; فحص التداخلات الدوائية (Interactions) ومنع الممنوع (Contraindicated).
- [CDSS Integration - Level 2]&#58; مراجعة سريرية (Clinical Review) تعرض ملخصات السلامة الدوائية استباقياً قبل حفظ الوصفة.
- [V10 Patch]&#58; تم إضافة حقل (أيام التغطية - days_supply) لكل صنف في سلة الوصفة لتغذية محرك التنبيهات (Refill Alerts) بأرقام سريرية دقيقة.
- [UI RBAC]&#58; أزرار الاعتماد والإلغاء محجوبة عن (الكاشير).
- [UX Fix]&#58; إضافة حقل رقم الوصفة، وإعادة تحميل قوائم المرضى والأطباء عند فتح الصفحة.
- [Patient UX Upgrade]&#58; عرض المرضى بشكل أغنى (الاسم + الهاتف + الهوية)، مع بطاقة معلومات مختصرة للمريض المحدد.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QLabel, QComboBox, QDateEdit, QFrame, QSplitter,
    QSpinBox, QInputDialog, QAbstractItemView, QDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor

from models.prescriptions_dao import PrescriptionsDAO
from models.doctors_dao import DoctorsDAO
from models.customers_dao import CustomersDAO
from models.medicine_dao import MedicineDAO
from models.interactions_dao import InteractionsDAO
from models.drug_safety_dao import DrugSafetyDAO


class ClinicalReviewDialog(QDialog):
    def __init__(self, html_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("المراجعة السريرية للوصفة الطبية")
        self.resize(650, 500)
        self.setStyleSheet(
            "QDialog { background-color: #F5F6FA; font-family: 'Times New Roman'; font-size: 16px; }"
        )

        layout = QVBoxLayout(self)

        title = QLabel("⚠️ مراجعة السلامة الدوائية للأصناف الموصوفة")
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #2C3E50; margin-bottom: 10px;"
        )
        layout.addWidget(title)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setHtml(html_content)
        self.text_edit.setStyleSheet(
            "background-color: white; padding: 15px; border: 1px solid #BDC3C7; "
            "border-radius: 5px; line-height: 1.6;"
        )
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()

        self.btn_accept = QPushButton("✅ اطلعت، اعتماد الوصفة")
        self.btn_accept.setCursor(Qt.PointingHandCursor)
        self.btn_accept.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; "
            "padding: 12px; border-radius: 5px;"
        )
        self.btn_accept.clicked.connect(self.accept)

        self.btn_reject = QPushButton("❌ تراجع لتعديل الوصفة")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; "
            "padding: 12px; border-radius: 5px;"
        )
        self.btn_reject.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_reject)
        btn_layout.addWidget(self.btn_accept)
        layout.addLayout(btn_layout)


class PrescriptionsPage(QWidget):
    CUSTOMER_ROLE = Qt.UserRole + 1

    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.rx_dao = PrescriptionsDAO()
        self.doctors_dao = DoctorsDAO()
        self.customers_dao = CustomersDAO()
        self.medicine_dao = MedicineDAO()
        self.interactions_dao = InteractionsDAO()
        self.safety_dao = DrugSafetyDAO()

        self.init_ui()
        self.load_initial_data()

    def showEvent(self, event):
        super().showEvent(event)
        self.load_reference_data()
        self.load_history()

    # ==========================================
    # Helpers
    # ==========================================
    def _normalize_text(self, value):
        return str(value).strip() if value is not None else ""

    def _gender_to_arabic(self, value):
        mapping = {
            "male": "ذكر",
            "female": "أنثى",
            "other": "أخرى"
        }
        return mapping.get((value or "").strip().lower(), "غير محدد")

    def _build_customer_display_text(self, customer_row):
        customer_id = customer_row[0]
        name = self._normalize_text(customer_row[1]) if len(customer_row) > 1 else f"مريض #{customer_id}"
        phone = self._normalize_text(customer_row[2]) if len(customer_row) > 2 else ""
        national_id = self._normalize_text(customer_row[4]) if len(customer_row) > 4 else ""

        parts = [name]
        if phone:
            parts.append(phone)
        if national_id:
            parts.append(f"ID: {national_id}")

        return " | ".join(parts)

    def _extract_customer_payload(self, customer_row):
        return {
            "id": customer_row[0],
            "name": self._normalize_text(customer_row[1]) if len(customer_row) > 1 else "",
            "phone": self._normalize_text(customer_row[2]) if len(customer_row) > 2 else "",
            "email": self._normalize_text(customer_row[3]) if len(customer_row) > 3 else "",
            "national_id": self._normalize_text(customer_row[4]) if len(customer_row) > 4 else "",
            "date_of_birth": self._normalize_text(customer_row[5]) if len(customer_row) > 5 else "",
            "gender": self._normalize_text(customer_row[6]) if len(customer_row) > 6 else "",
            "address": self._normalize_text(customer_row[7]) if len(customer_row) > 7 else "",
            "medical_notes": self._normalize_text(customer_row[8]) if len(customer_row) > 8 else "",
            "is_active": int(customer_row[9]) if len(customer_row) > 9 and customer_row[9] is not None else 1,
            "notes": self._normalize_text(customer_row[10]) if len(customer_row) > 10 else ""
        }

    def _calculate_age_text(self, dob_str):
        if not dob_str:
            return "غير محدد"

        dob = QDate.fromString(dob_str, "yyyy-MM-dd")
        if not dob.isValid():
            return dob_str

        today = QDate.currentDate()
        age = dob.daysTo(today) // 365
        return f"{age} سنة تقريباً"

    def get_selected_customer_id(self):
        return self.customer_combo.currentData(Qt.UserRole)

    def get_selected_customer_payload(self):
        return self.customer_combo.currentData(self.CUSTOMER_ROLE)

    def update_selected_patient_summary(self):
        payload = self.get_selected_customer_payload()
        if not payload:
            self.patient_summary_label.setText("لم يتم اختيار مريض بعد.")
            self.patient_summary_label.setStyleSheet(
                "font-size: 14px; color: #7F8C8D; background-color: #FBFCFC; "
                "border: 1px solid #E5E7E9; border-radius: 6px; padding: 10px;"
            )
            return

        gender_text = self._gender_to_arabic(payload.get("gender"))
        age_text = self._calculate_age_text(payload.get("date_of_birth"))
        phone_text = payload.get("phone") or "غير محدد"
        email_text = payload.get("email") or "غير محدد"
        national_id_text = payload.get("national_id") or "غير محدد"
        address_text = payload.get("address") or "غير محدد"
        medical_notes = payload.get("medical_notes") or "لا توجد ملاحظات طبية مسجلة"
        general_notes = payload.get("notes") or "لا توجد ملاحظات عامة"

        html = f"""
        <div style="line-height:1.8;">
            <b>المريض:</b> {payload.get('name', 'غير محدد')} &nbsp;&nbsp;|&nbsp;&nbsp;
            <b>الجنس:</b> {gender_text} &nbsp;&nbsp;|&nbsp;&nbsp;
            <b>العمر:</b> {age_text}<br>
            <b>الهاتف:</b> {phone_text} &nbsp;&nbsp;|&nbsp;&nbsp;
            <b>الهوية:</b> {national_id_text}<br>
            <b>البريد:</b> {email_text}<br>
            <b>العنوان:</b> {address_text}<br>
            <b>ملاحظات طبية:</b> {medical_notes}<br>
            <b>ملاحظات عامة:</b> {general_notes}
        </div>
        """
        self.patient_summary_label.setText(html)

        style = (
            "font-size: 14px; color: #2C3E50; background-color: #F8F9F9; "
            "border: 1px solid #D5DBDB; border-radius: 6px; padding: 10px;"
        )
        if payload.get("medical_notes"):
            style = (
                "font-size: 14px; color: #7D6608; background-color: #FCF3CF; "
                "border: 1px solid #F1C40F; border-radius: 6px; padding: 10px;"
            )
        self.patient_summary_label.setStyleSheet(style)

    # ==========================================
    # UI
    # ==========================================
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title = QLabel("إدارة الوصفات الطبية الإلكترونية (E-Prescriptions)")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )
        main_layout.addWidget(title)

        main_splitter = QSplitter(Qt.Vertical)

        # ==========================================
        # القسم العلوي: إنشاء وصفة جديدة
        # ==========================================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        header_frame = QFrame()
        header_frame.setStyleSheet(
            "background-color: white; border-radius: 8px; padding: 10px; border: 1px solid #BDC3C7;"
        )
        header_layout = QVBoxLayout(header_frame)
        header_layout.setSpacing(10)

        # الصف الأول
        row1 = QHBoxLayout()

        self.rx_number_input = QLineEdit()
        self.rx_number_input.setPlaceholderText("رقم الوصفة (اختياري إذا كانت النواة تولده تلقائياً)")
        self.rx_number_input.setStyleSheet("font-size: 16px; padding: 5px;")
        self.rx_number_input.setMinimumHeight(40)

        self.customer_combo = QComboBox()
        self.customer_combo.setStyleSheet("font-size: 16px; padding: 5px;")
        self.customer_combo.setMinimumHeight(40)
        self.customer_combo.currentIndexChanged.connect(self.update_selected_patient_summary)

        self.doctor_combo = QComboBox()
        self.doctor_combo.setStyleSheet("font-size: 16px; padding: 5px;")
        self.doctor_combo.setMinimumHeight(40)

        self.type_combo = QComboBox()
        self.type_combo.addItems(['regular', 'chronic', 'controlled', 'insurance'])
        self.type_combo.setStyleSheet("font-size: 16px; padding: 5px;")
        self.type_combo.setMinimumHeight(40)

        row1.addWidget(QLabel("رقم الوصفة:"), stretch=1)
        row1.addWidget(self.rx_number_input, stretch=2)
        row1.addWidget(QLabel("المريض:"), stretch=1)
        row1.addWidget(self.customer_combo, stretch=4)
        row1.addWidget(QLabel("الطبيب المعالج:"), stretch=1)
        row1.addWidget(self.doctor_combo, stretch=4)
        row1.addWidget(QLabel("نوع الوصفة:"), stretch=1)
        row1.addWidget(self.type_combo, stretch=2)

        # الصف الثاني
        row2 = QHBoxLayout()

        self.issue_date = QDateEdit()
        self.issue_date.setCalendarPopup(True)
        self.issue_date.setDate(QDate.currentDate())
        self.issue_date.setStyleSheet("font-size: 16px; padding: 5px;")
        self.issue_date.setMinimumHeight(40)

        self.expiry_date = QDateEdit()
        self.expiry_date.setCalendarPopup(True)
        self.expiry_date.setDate(QDate.currentDate().addDays(7))
        self.expiry_date.setStyleSheet("font-size: 16px; padding: 5px;")
        self.expiry_date.setMinimumHeight(40)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("ملاحظات عامة على الوصفة...")
        self.notes_input.setStyleSheet("font-size: 16px; padding: 5px;")
        self.notes_input.setMinimumHeight(40)

        self.btn_reload_refs = QPushButton("🔄 تحديث القوائم")
        self.btn_reload_refs.setCursor(Qt.PointingHandCursor)
        self.btn_reload_refs.clicked.connect(self.load_reference_data)
        self.btn_reload_refs.setStyleSheet(
            "background-color: #5D6D7E; color: white; font-weight: bold; "
            "font-size: 14px; padding: 8px 15px; border-radius: 5px;"
        )

        row2.addWidget(QLabel("تاريخ الإصدار:"), stretch=1)
        row2.addWidget(self.issue_date, stretch=2)
        row2.addWidget(QLabel("تاريخ الانتهاء:"), stretch=1)
        row2.addWidget(self.expiry_date, stretch=2)
        row2.addWidget(QLabel("ملاحظات:"), stretch=1)
        row2.addWidget(self.notes_input, stretch=4)
        row2.addWidget(self.btn_reload_refs, stretch=1)

        self.patient_summary_label = QLabel("لم يتم اختيار مريض بعد.")
        self.patient_summary_label.setWordWrap(True)
        self.patient_summary_label.setTextFormat(Qt.RichText)
        self.patient_summary_label.setStyleSheet(
            "font-size: 14px; color: #7F8C8D; background-color: #FBFCFC; "
            "border: 1px solid #E5E7E9; border-radius: 6px; padding: 10px;"
        )

        header_layout.addLayout(row1)
        header_layout.addLayout(row2)
        header_layout.addWidget(self.patient_summary_label)

        top_layout.addWidget(header_frame)

        # ==========================================
        # البحث وإضافة الأدوية
        # ==========================================
        search_layout = QHBoxLayout()

        self.search_med_input = QLineEdit()
        self.search_med_input.setPlaceholderText("بحث عن دواء لإضافته للوصفة (الباركود أو الاسم)...")
        self.search_med_input.setFixedHeight(40)
        self.search_med_input.setStyleSheet(
            "font-size: 16px; padding: 5px; border: 1px solid #ccc; border-radius: 4px;"
        )
        self.search_med_input.returnPressed.connect(self.search_and_add_medicine)

        self.btn_add_med = QPushButton("إضافة دواء")
        self.btn_add_med.setFixedHeight(40)
        self.btn_add_med.clicked.connect(self.search_and_add_medicine)
        self.btn_add_med.setStyleSheet(
            "background-color: #34495E; color: white; font-weight: bold; "
            "font-size: 16px; border-radius: 4px; padding: 0 15px;"
        )

        search_layout.addWidget(self.search_med_input, stretch=4)
        search_layout.addWidget(self.btn_add_med, stretch=1)
        top_layout.addLayout(search_layout)

        # ==========================================
        # سلة أصناف الوصفة
        # ==========================================
        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(7)
        self.cart_table.setHorizontalHeaderLabels([
            "ID", "اسم الدواء", "الكمية الموصوفة", "أيام التغطية",
            "تعليمات الجرعة", "ملاحظات", "إجراء"
        ])
        self.cart_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cart_table.setLayoutDirection(Qt.RightToLeft)
        self.cart_table.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        top_layout.addWidget(self.cart_table)

        self.btn_save_rx = QPushButton("💾 مراجعة واعتماد الوصفة الطبية")
        self.btn_save_rx.setFixedHeight(45)
        self.btn_save_rx.setCursor(Qt.PointingHandCursor)
        self.btn_save_rx.clicked.connect(self.save_prescription)
        self.btn_save_rx.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; "
            "font-size: 18px; border-radius: 5px;"
        )
        top_layout.addWidget(self.btn_save_rx)

        main_splitter.addWidget(top_widget)

        # ==========================================
        # القسم السفلي: السجل التاريخي
        # ==========================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 15, 0, 0)

        history_header = QHBoxLayout()

        history_title = QLabel("سجل الوصفات الطبية")
        history_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #34495E;")

        btn_refresh = QPushButton("🔄 تحديث السجل")
        btn_refresh.clicked.connect(self.load_history)
        btn_refresh.setStyleSheet("font-size: 14px; padding: 5px 15px;")

        self.btn_cancel_rx = QPushButton("🚫 إلغاء الوصفة المحددة")
        self.btn_cancel_rx.clicked.connect(self.cancel_selected_prescription)
        self.btn_cancel_rx.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; "
            "font-size: 14px; padding: 5px 15px;"
        )

        history_header.addWidget(history_title)
        history_header.addStretch()
        history_header.addWidget(btn_refresh)
        history_header.addWidget(self.btn_cancel_rx)
        bottom_layout.addLayout(history_header)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "ID", "رقم الوصفة", "المريض", "الطبيب",
            "الحالة", "تاريخ الإصدار", "تاريخ الانتهاء"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setLayoutDirection(Qt.RightToLeft)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")
        bottom_layout.addWidget(self.history_table)

        main_splitter.addWidget(bottom_widget)
        main_splitter.setSizes([470, 250])

        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)

        # UI RBAC
        if self.user_role not in ['admin', 'pharmacist']:
            self.btn_save_rx.hide()
            self.btn_cancel_rx.hide()
            self.btn_add_med.hide()
            self.search_med_input.setEnabled(False)
            self.search_med_input.setPlaceholderText("ليس لديك صلاحية لإنشاء وصفات...")
            self.rx_number_input.setEnabled(False)
            self.customer_combo.setEnabled(False)
            self.doctor_combo.setEnabled(False)
            self.type_combo.setEnabled(False)
            self.issue_date.setEnabled(False)
            self.expiry_date.setEnabled(False)
            self.notes_input.setEnabled(False)

    # ==========================================
    # تحميل البيانات المرجعية
    # ==========================================
    def load_initial_data(self):
        self.load_reference_data()
        self.load_history()

    def load_reference_data(self):
        self.load_customers()
        self.load_doctors()
        self.update_selected_patient_summary()

    def load_customers(self):
        previous_customer_id = self.get_selected_customer_id()

        self.customer_combo.blockSignals(True)
        self.customer_combo.clear()
        self.customer_combo.addItem("-- اختر المريض --", None)
        self.customer_combo.setItemData(0, None, self.CUSTOMER_ROLE)

        customers = []
        try:
            customers = self.customers_dao.get_all_customers(active_only=True)
        except TypeError:
            try:
                customers = self.customers_dao.get_all_customers()
                customers = [c for c in customers if len(c) < 10 or int(c[9]) == 1]
            except Exception:
                customers = []
        except Exception:
            customers = []

        for row in customers:
            payload = self._extract_customer_payload(row)
            display_text = self._build_customer_display_text(row)

            self.customer_combo.addItem(display_text, payload["id"])
            idx = self.customer_combo.count() - 1
            self.customer_combo.setItemData(idx, payload, self.CUSTOMER_ROLE)

        if previous_customer_id is not None:
            idx = self.customer_combo.findData(previous_customer_id, Qt.UserRole)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)
            elif self.customer_combo.count() > 0:
                self.customer_combo.setCurrentIndex(0)
        else:
            self.customer_combo.setCurrentIndex(0)

        self.customer_combo.blockSignals(False)

    def load_doctors(self):
        previous_doctor = self.doctor_combo.currentData()

        self.doctor_combo.blockSignals(True)
        self.doctor_combo.clear()
        self.doctor_combo.addItem("-- اختر الطبيب --", None)

        doctors = []
        try:
            doctors = self.doctors_dao.get_all_doctors(active_only=True)
        except TypeError:
            try:
                doctors = self.doctors_dao.get_all_doctors()
            except Exception:
                doctors = []
        except Exception:
            doctors = []

        for d in doctors:
            doctor_id = d[0]
            doctor_name = d[1] if len(d) > 1 else "غير معروف"
            specialty = d[2] if len(d) > 2 and d[2] else ""
            display_text = f"{doctor_name} ({specialty})" if specialty else doctor_name
            self.doctor_combo.addItem(display_text, doctor_id)

        if previous_doctor is not None:
            idx = self.doctor_combo.findData(previous_doctor)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)
            else:
                self.doctor_combo.setCurrentIndex(0)
        else:
            self.doctor_combo.setCurrentIndex(0)

        self.doctor_combo.blockSignals(False)

    def load_history(self):
        self.history_table.setRowCount(0)

        try:
            prescriptions = self.rx_dao.get_all_prescriptions()
        except Exception:
            prescriptions = []

        for row_idx, rx in enumerate(prescriptions):
            self.history_table.insertRow(row_idx)
            for col_idx, val in enumerate(rx):
                item = QTableWidgetItem(str(val if val is not None else ""))
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 4:
                    status_val = str(val)
                    if status_val == 'active':
                        item.setForeground(QColor("#27AE60"))
                    elif status_val == 'expired':
                        item.setForeground(QColor("#7F8C8D"))
                    elif status_val == 'cancelled':
                        item.setForeground(QColor("#E74C3C"))
                    elif status_val == 'partially_dispensed':
                        item.setForeground(QColor("#F39C12"))
                    elif status_val == 'fully_dispensed':
                        item.setForeground(QColor("#2980B9"))

                self.history_table.setItem(row_idx, col_idx, item)

    # ==========================================
    # سلة الأدوية
    # ==========================================
    def search_and_add_medicine(self):
        text = self.search_med_input.text().strip()
        if not text:
            return

        results = self.medicine_dao.search_medicine(text)
        if not results:
            QMessageBox.warning(self, "تنبيه", "لم يتم العثور على دواء بهذا الاسم أو الباركود.")
            return

        med = results[0]
        med_id = str(med[0])
        med_name = str(med[2])

        for row in range(self.cart_table.rowCount()):
            existing_item = self.cart_table.item(row, 0)
            if existing_item and existing_item.text() == med_id:
                QMessageBox.information(self, "تنبيه", "هذا الدواء موجود بالفعل في الوصفة. يرجى تعديل الكمية.")
                self.search_med_input.clear()
                return

        row_idx = self.cart_table.rowCount()
        self.cart_table.insertRow(row_idx)

        item_id = QTableWidgetItem(med_id)
        item_id.setFlags(Qt.ItemIsEnabled)
        self.cart_table.setItem(row_idx, 0, item_id)

        item_name = QTableWidgetItem(med_name)
        item_name.setFlags(Qt.ItemIsEnabled)
        self.cart_table.setItem(row_idx, 1, item_name)

        qty_spin = QSpinBox()
        qty_spin.setRange(1, 1000)
        qty_spin.setValue(1)
        qty_spin.setStyleSheet("font-size: 16px; padding: 5px;")
        self.cart_table.setCellWidget(row_idx, 2, qty_spin)

        days_spin = QSpinBox()
        days_spin.setRange(1, 365)
        days_spin.setValue(30)
        days_spin.setToolTip("حدد كم يوم تكفي هذه الكمية الموصوفة")
        days_spin.setStyleSheet("font-size: 16px; padding: 5px; background-color: #E8F8F5;")
        self.cart_table.setCellWidget(row_idx, 3, days_spin)

        dosage_input = QLineEdit()
        dosage_input.setPlaceholderText("مثال: حبة كل 8 ساعات")
        self.cart_table.setCellWidget(row_idx, 4, dosage_input)

        item_notes_input = QLineEdit()
        item_notes_input.setPlaceholderText("ملاحظات إضافية للصنف...")
        self.cart_table.setCellWidget(row_idx, 5, item_notes_input)

        btn_remove = QPushButton("❌ حذف")
        btn_remove.setCursor(Qt.PointingHandCursor)
        btn_remove.setStyleSheet("color: red; font-weight: bold; border: none;")
        btn_remove.clicked.connect(lambda _, r=row_idx: self.remove_item(r))
        self.cart_table.setCellWidget(row_idx, 6, btn_remove)

        self.search_med_input.clear()
        self.search_med_input.setFocus()

    def remove_item(self, row_idx):
        self.cart_table.removeRow(row_idx)
        self.rebind_remove_buttons()

    def rebind_remove_buttons(self):
        for row in range(self.cart_table.rowCount()):
            btn = self.cart_table.cellWidget(row, 6)
            if btn:
                try:
                    btn.clicked.disconnect()
                except Exception:
                    pass
                btn.clicked.connect(lambda _, r=row: self.remove_item(r))

    # ==========================================
    # بناء محتوى المراجعة السريرية
    # ==========================================
    def build_clinical_review_html(self, med_ids_for_check, med_names_map):
        clinical_html = ""

        for med_id in set(med_ids_for_check):
            profile = self.safety_dao.get_profile_by_medicine_id(med_id)
            if not profile:
                continue

            full_profile = self.safety_dao.get_full_profile(profile['id'])
            med_name = med_names_map.get(med_id, "دواء غير معروف")

            clinical_html += (
                f"<h3 style='color:#2980B9;'>💊 {med_name} "
                f"<span style='font-size:14px; color:#7F8C8D;'>({full_profile['ingredient_key']})</span></h3>"
            )
            clinical_html += "<ul style='margin-top:5px; margin-bottom:15px;'>"

            if full_profile.get('contraindications'):
                clinical_html += (
                    f"<li><b>🚫 موانع الاستخدام:</b> "
                    f"<span style='color:#C0392B;'>{full_profile['contraindications']}</span></li>"
                )

            preg_warn = full_profile.get('pregnancy_warning')
            lact_warn = full_profile.get('lactation_warning')
            if preg_warn or lact_warn:
                clinical_html += (
                    f"<li><b>⚠️ الحمل والرضاعة:</b> {preg_warn or '-'} / {lact_warn or '-'}</li>"
                )

            if full_profile.get('max_daily_dose'):
                clinical_html += f"<li><b>⚖️ الجرعة القصوى:</b> {full_profile['max_daily_dose']}</li>"

            if full_profile.get('counseling_notes'):
                clinical_html += (
                    f"<li><b>💡 نصائح الإرشاد:</b> "
                    f"<span style='color:#16A085;'>{full_profile['counseling_notes']}</span></li>"
                )

            severe_se = [
                se['effect_name']
                for se in full_profile.get('side_effects', [])
                if se.get('severity') == 'severe'
            ]
            if severe_se:
                clinical_html += f"<li><b>🔴 آثار جانبية شديدة:</b> {', '.join(severe_se[:3])}</li>"

            clinical_html += "</ul><hr style='border: 1px solid #ECF0F1;'>"

        return clinical_html

    # ==========================================
    # الحفظ
    # ==========================================
    def save_prescription(self):
        if not self.user_id:
            return

        customer_id = self.get_selected_customer_id()
        doctor_id = self.doctor_combo.currentData()
        rx_number = self.rx_number_input.text().strip()
        p_type = self.type_combo.currentText()
        issue_date = self.issue_date.date().toString("yyyy-MM-dd")
        expiry_date = self.expiry_date.date().toString("yyyy-MM-dd")
        general_notes = self.notes_input.text().strip()

        if customer_id is None:
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار المريض أولاً.")
            return

        if doctor_id is None:
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار الطبيب أولاً.")
            return

        if self.issue_date.date() > self.expiry_date.date():
            QMessageBox.warning(self, "تنبيه", "تاريخ الانتهاء لا يمكن أن يكون قبل تاريخ الإصدار.")
            return

        items = []
        med_ids_for_check = []
        med_names_map = {}

        for row in range(self.cart_table.rowCount()):
            med_id = int(self.cart_table.item(row, 0).text())
            med_name = self.cart_table.item(row, 1).text()
            qty = self.cart_table.cellWidget(row, 2).value()
            days_supply = self.cart_table.cellWidget(row, 3).value()
            dosage = self.cart_table.cellWidget(row, 4).text().strip()
            notes = self.cart_table.cellWidget(row, 5).text().strip()

            items.append({
                "medicine_id": med_id,
                "prescribed_qty": qty,
                "days_supply": days_supply,
                "dosage": dosage,
                "notes": notes
            })
            med_ids_for_check.append(med_id)
            med_names_map[med_id] = med_name

        if not items:
            QMessageBox.warning(self, "تنبيه", "سلة الوصفة فارغة. يرجى إضافة دواء واحد على الأقل.")
            return

        # ==========================================
        # CDSS Level 1: التداخلات الدوائية
        # ==========================================
        interactions = self.interactions_dao.check_cart_interactions(med_ids_for_check)

        has_contra = len(interactions.get('contraindicated', [])) > 0
        has_major = len(interactions.get('major', [])) > 0
        has_mod_min = (
            len(interactions.get('moderate', [])) > 0 or
            len(interactions.get('minor', [])) > 0
        )

        if has_contra or has_major or has_mod_min:
            msg = ""

            if has_contra:
                msg += "🚫 تداخلات ممنوعة (Contraindicated):\n"
                for inter in interactions['contraindicated']:
                    msg += f"- {inter['medicine_1']} و {inter['medicine_2']}: {inter['description']}\n"
                msg += "\nلا يمكن اعتماد الوصفة بوجود تداخلات ممنوعة طبياً."
                QMessageBox.critical(self, "تداخل دوائي خطير (مرفوض)", msg)
                return

            if has_major:
                msg += "⚠️ تداخلات خطيرة (Major):\n"
                for inter in interactions['major']:
                    msg += f"- {inter['medicine_1']} و {inter['medicine_2']}: {inter['description']}\n"
                msg += "\nهل ترغب بتجاوز هذا التحذير واعتماد الوصفة؟"
                reply = QMessageBox.warning(self, "تنبيه تداخل دوائي عالي", msg, QMessageBox.Yes | QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return

            elif has_mod_min:
                if len(interactions['moderate']) > 0:
                    msg += "🟠 تداخلات متوسطة (Moderate):\n"
                    for inter in interactions['moderate']:
                        msg += f"- {inter['medicine_1']} و {inter['medicine_2']}\n"

                if len(interactions['minor']) > 0:
                    msg += "🟡 تداخلات طفيفة (Minor):\n"
                    for inter in interactions['minor']:
                        msg += f"- {inter['medicine_1']} و {inter['medicine_2']}\n"

                msg += "\nيوجد تداخلات دوائية. هل تريد المتابعة؟"
                reply = QMessageBox.information(self, "ملاحظة طبية", msg, QMessageBox.Yes | QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return

        # ==========================================
        # CDSS Level 2: المراجعة السريرية
        # ==========================================
        clinical_html = self.build_clinical_review_html(med_ids_for_check, med_names_map)
        if clinical_html:
            dialog = ClinicalReviewDialog(clinical_html, self)
            if not dialog.exec_():
                return

        # ==========================================
        # الحفظ الفعلي
        # ==========================================
        try:
            success, msg = self.rx_dao.add_prescription(
                requester_id=self.user_id,
                customer_id=customer_id,
                doctor_id=doctor_id,
                prescription_number=rx_number if rx_number else None,
                p_type=p_type,
                issue_date=issue_date,
                expiry_date=expiry_date,
                notes=general_notes,
                items=items
            )
        except TypeError:
            success, msg = self.rx_dao.add_prescription(
                requester_id=self.user_id,
                customer_id=customer_id,
                doctor_id=doctor_id,
                p_type=p_type,
                issue_date=issue_date,
                expiry_date=expiry_date,
                notes=general_notes,
                items=items
            )

        if success:
            QMessageBox.information(self, "نجاح العملية", msg)
            self.cart_table.setRowCount(0)
            self.rx_number_input.clear()
            self.notes_input.clear()
            self.type_combo.setCurrentIndex(0)
            self.issue_date.setDate(QDate.currentDate())
            self.expiry_date.setDate(QDate.currentDate().addDays(7))
            self.customer_combo.setCurrentIndex(0)
            self.doctor_combo.setCurrentIndex(0)
            self.update_selected_patient_summary()
            self.load_history()
        else:
            QMessageBox.critical(self, "رفض أمني/منطقي", msg)

    # ==========================================
    # إلغاء الوصفة
    # ==========================================
    def cancel_selected_prescription(self):
        if not self.user_id:
            return

        selected_row = self.history_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد وصفة من الجدول السفلي لإلغائها.")
            return

        rx_id = int(self.history_table.item(selected_row, 0).text())
        rx_number = self.history_table.item(selected_row, 1).text()

        reason, ok = QInputDialog.getText(
            self,
            "إلغاء الوصفة",
            f"أدخل سبب إلغاء الوصفة ({rx_number}):"
        )
        if not ok or not reason.strip():
            return

        success, msg = self.rx_dao.cancel_prescription(self.user_id, rx_id, reason.strip())

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.load_history()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)