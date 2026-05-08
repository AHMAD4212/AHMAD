"""
وظيفة الملف: لوحة تحكم التنبيهات الاستباقية للأدوية المزمنة (Refill Alerts Dashboard).
الطبقة: Presentation Layer
ملاحظة معمارية وسريرية:
- [Proactive CDSS]: تعرض تنبيهات إعادة التعبئة واقتراب انتهاء الوصفات بناءً على المحرك.
- [UI RBAC]: محجوبة بالكامل عن (الكاشير).
- [Data-Bound Filter]: الفلتر الزمني يعتمد على قيم برمجية (currentData) وليس تحليلاً نصياً هشاً.
- [Action Guard & State Hygiene]: زر التذكير معطل افتراضياً، ويتم تصفير حالة التحديد والزر إجبارياً عند أي تحديث للبيانات.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
                             QComboBox, QFrame, QSplitter, QMessageBox, QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from datetime import datetime

from models.refill_alerts_dao import RefillAlertsDAO

class RefillAlertsPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

        self.dao = RefillAlertsDAO()

        self.init_ui()
        if self.user_role in ['admin', 'pharmacist']:
            self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # ------------------------------------------
        # 1. فحص الصلاحيات (RBAC) الحاسم
        # ------------------------------------------
        if self.user_role not in ['admin', 'pharmacist']:
            lock_label = QLabel("⛔ عذراً، هذه اللوحة السريرية مخصصة للصيادلة ومدراء النظام فقط.")
            lock_label.setStyleSheet("font-size: 24px; color: #E74C3C; font-weight: bold;")
            lock_label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(lock_label)
            return

        title = QLabel("لوحة المتابعة السريرية: الأدوية المزمنة وإعادة التعبئة")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        main_layout.addWidget(title)

        # ------------------------------------------
        # 2. بطاقات الملخص (Summary Cards)
        # ------------------------------------------
        cards_layout = QHBoxLayout()

        self.card_refills = self._create_summary_card("أدوية مستحقة التعبئة", "0", "#E67E22")
        self.card_expiring = self._create_summary_card("وصفات قاربت على الانتهاء", "0", "#E74C3C")
        self.card_nearest = self._create_summary_card("أقرب تاريخ نفاد متوقع", "-", "#2980B9")

        cards_layout.addWidget(self.card_refills)
        cards_layout.addWidget(self.card_expiring)
        cards_layout.addWidget(self.card_nearest)
        main_layout.addLayout(cards_layout)

        # ------------------------------------------
        # 3. شريط أدوات التشغيل (Controls)
        # ------------------------------------------
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("نطاق التنبيه المسبق:"))

        self.filter_combo = QComboBox()
        self.filter_combo.addItem("خلال 7 أيام", 7)
        self.filter_combo.addItem("خلال 14 يوماً", 14)
        self.filter_combo.addItem("خلال 30 يوماً", 30)
        self.filter_combo.setStyleSheet("font-size: 16px; padding: 5px; border: 1px solid #BDC3C7; border-radius: 4px;")
        self.filter_combo.currentIndexChanged.connect(self.load_data)
        controls_layout.addWidget(self.filter_combo)

        controls_layout.addStretch()

        self.btn_refresh = QPushButton(" 🔄 تحديث البيانات")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("padding: 8px 15px; font-size: 16px;")
        self.btn_refresh.clicked.connect(self.load_data)
        controls_layout.addWidget(self.btn_refresh)

        self.btn_reminder = QPushButton(" 💬 إرسال تذكير للمريض (WhatsApp/SMS)")
        self.btn_reminder.setCursor(Qt.PointingHandCursor)
        self.btn_reminder.setEnabled(False)
        self.btn_reminder.setStyleSheet(
            "QPushButton { background-color: #27AE60; color: white; font-weight: bold; padding: 8px 15px; font-size: 16px; border-radius: 5px; }"
            "QPushButton:disabled { background-color: #95A5A6; color: #ECF0F1; }"
        )
        self.btn_reminder.clicked.connect(self.send_reminder_placeholder)
        controls_layout.addWidget(self.btn_reminder)

        main_layout.addLayout(controls_layout)

        # ------------------------------------------
        # 4. الجداول (Splitter)
        # ------------------------------------------
        splitter = QSplitter(Qt.Vertical)

        # جدول التعبئة المستحقة
        refills_widget = QWidget()
        refills_layout = QVBoxLayout(refills_widget)
        refills_layout.setContentsMargins(0, 0, 0, 0)

        lbl_refills = QLabel("📦 تنبيهات الأدوية المستحقة لإعادة التعبئة (Due Refills)")
        lbl_refills.setStyleSheet("font-size: 18px; font-weight: bold; color: #E67E22;")
        refills_layout.addWidget(lbl_refills)

        self.table_refills = QTableWidget()
        self.table_refills.setColumnCount(8)
        self.table_refills.setHorizontalHeaderLabels([
            "رقم الوصفة", "اسم المريض", "رقم الهاتف", "الطبيب",
            "اسم الدواء", "أيام التغطية", "تاريخ آخر صرف", "النفاد المتوقع"
        ])
        self.table_refills.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_refills.setLayoutDirection(Qt.RightToLeft)
        self.table_refills.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_refills.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_refills.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_refills.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        self.table_refills.itemSelectionChanged.connect(self._handle_refills_selection)

        refills_layout.addWidget(self.table_refills)
        splitter.addWidget(refills_widget)

        # جدول الوصفات المقاربة للانتهاء
        expiring_widget = QWidget()
        expiring_layout = QVBoxLayout(expiring_widget)
        expiring_layout.setContentsMargins(0, 10, 0, 0)

        lbl_expiring = QLabel("⏳ وصفات مزمنة قاربت صلاحيتها على الانتهاء (Expiring Prescriptions)")
        lbl_expiring.setStyleSheet("font-size: 18px; font-weight: bold; color: #E74C3C;")
        expiring_layout.addWidget(lbl_expiring)

        self.table_expiring = QTableWidget()
        self.table_expiring.setColumnCount(6)
        self.table_expiring.setHorizontalHeaderLabels([
            "رقم الوصفة", "المريض", "رقم الهاتف", "الطبيب", "تاريخ الإصدار", "تاريخ الانتهاء"
        ])
        self.table_expiring.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_expiring.setLayoutDirection(Qt.RightToLeft)
        self.table_expiring.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_expiring.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_expiring.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_expiring.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        self.table_expiring.itemSelectionChanged.connect(self._handle_expiring_selection)

        expiring_layout.addWidget(self.table_expiring)
        splitter.addWidget(expiring_widget)

        splitter.setSizes([400, 300])
        main_layout.addWidget(splitter)

    def _create_summary_card(self, title, value, color):
        card = QFrame()
        card.setStyleSheet(
            f"background-color: white; border-radius: 8px; border-top: 4px solid {color}; padding: 15px;")
        layout = QVBoxLayout(card)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 16px; color: #7F8C8D; font-weight: bold;")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_value = QLabel(value)
        lbl_value.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        lbl_value.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_value)
        card.value_label = lbl_value
        return card

    # ==========================================
    # State Management / Hygiene
    # ==========================================

    def _handle_refills_selection(self):
        if self.table_refills.selectedItems():
            self.table_expiring.blockSignals(True)
            self.table_expiring.clearSelection()
            self.table_expiring.blockSignals(False)
            self.btn_reminder.setEnabled(True)
        else:
            if not self.table_expiring.selectedItems():
                self.btn_reminder.setEnabled(False)

    def _handle_expiring_selection(self):
        if self.table_expiring.selectedItems():
            self.table_refills.blockSignals(True)
            self.table_refills.clearSelection()
            self.table_refills.blockSignals(False)
            self.btn_reminder.setEnabled(True)
        else:
            if not self.table_refills.selectedItems():
                self.btn_reminder.setEnabled(False)

    # ==========================================
    # العمليات (Operations)
    # ==========================================

    def load_data(self):
        days_ahead = self.filter_combo.currentData()

        due_refills = self.dao.get_due_refills(days_ahead)
        expiring_rx = self.dao.get_expiring_prescriptions(days_ahead)

        self.populate_refills_table(due_refills)
        self.populate_expiring_table(expiring_rx)

        self.card_refills.value_label.setText(str(len(due_refills)))
        self.card_expiring.value_label.setText(str(len(expiring_rx)))

        nearest_date = "-"
        if due_refills:
            dates = [r['expected_exhaustion_date'] for r in due_refills if r['expected_exhaustion_date']]
            if dates:
                nearest_date = min(dates)
        self.card_nearest.value_label.setText(nearest_date)

        # [State Hygiene Fix]: تصفير التحديد إجبارياً بعد إعادة تحميل البيانات
        self.table_refills.clearSelection()
        self.table_expiring.clearSelection()
        self.btn_reminder.setEnabled(False)

    def populate_refills_table(self, data):
        self.table_refills.blockSignals(True)
        self.table_refills.setRowCount(0)
        today = datetime.now().date()

        for row_idx, row in enumerate(data):
            self.table_refills.insertRow(row_idx)
            items = [
                row['prescription_number'],
                row['customer_name'],
                row['customer_phone'] or "لا يوجد",
                row['doctor_name'],
                row['medicine_name'],
                str(row['days_supply']),
                row['last_dispensed_date'][:10] if row['last_dispensed_date'] else "-",
                row['expected_exhaustion_date']
            ]
            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col_idx == 7 and row['expected_exhaustion_date']:
                    exp_date = datetime.strptime(row['expected_exhaustion_date'], "%Y-%m-%d").date()
                    item.setFont(QFont("Times New Roman", 14, QFont.Bold))
                    if exp_date < today:
                        item.setForeground(QColor("white"))
                        item.setBackground(QColor("#C0392B"))
                    elif exp_date == today:
                        item.setForeground(QColor("black"))
                        item.setBackground(QColor("#F1C40F"))
                    else:
                        item.setForeground(QColor("black"))
                        item.setBackground(QColor("#D5F5E3"))
                self.table_refills.setItem(row_idx, col_idx, item)
        self.table_refills.blockSignals(False)

    def populate_expiring_table(self, data):
        self.table_expiring.blockSignals(True)
        self.table_expiring.setRowCount(0)
        for row_idx, row in enumerate(data):
            self.table_expiring.insertRow(row_idx)
            items = [
                row['prescription_number'],
                row['customer_name'],
                row['customer_phone'] or "لا يوجد",
                row['doctor_name'],
                row['issue_date'],
                row['expiry_date']
            ]
            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col_idx == 5:
                    item.setFont(QFont("Times New Roman", 14, QFont.Bold))
                    item.setForeground(QColor("#C0392B"))
                self.table_expiring.setItem(row_idx, col_idx, item)
        self.table_expiring.blockSignals(False)

    def send_reminder_placeholder(self):
        patient_name = ""
        phone = ""
        context_msg = ""

        if self.table_refills.selectedItems():
            row = self.table_refills.currentRow()
            patient_name = self.table_refills.item(row, 1).text()
            phone = self.table_refills.item(row, 2).text()
            med_name = self.table_refills.item(row, 4).text()
            exp_date = self.table_refills.item(row, 7).text()
            context_msg = f"نود تذكيركم باقتراب موعد نفاد دواء ({med_name}) المخصص لكم بتاريخ ({exp_date}). يرجى زيارة الصيدلية لإعادة التعبئة لضمان استمرارية العلاج."

        elif self.table_expiring.selectedItems():
            row = self.table_expiring.currentRow()
            patient_name = self.table_expiring.item(row, 1).text()
            phone = self.table_expiring.item(row, 2).text()
            rx_num = self.table_expiring.item(row, 0).text()
            context_msg = f"نود إعلامكم بأن الوصفة الطبية المزمنة رقم ({rx_num}) قاربت على الانتهاء. يرجى مراجعة الطبيب المختص لتجديدها."
        else:
            return

        if phone == "لا يوجد":
            QMessageBox.warning(self, "بيانات ناقصة", "لا يوجد رقم هاتف مسجل لهذا المريض.")
            return

        draft = f"مرحباً {patient_name}،\nمعكم صيدلية الشفاء.\n{context_msg}\nمع تمنياتنا لكم بدوام الصحة."

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("مسودة رسالة التذكير (Placeholder/Simulation)")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText("<b>سيتم إرسال الرسالة التالية للمريض:</b>")
        msg_box.setInformativeText(
            f"<br><div style='background-color:#EAEDED; padding:10px; border-radius:5px;'>{draft.replace(chr(10), '<br>')}</div><br><b>رقم الإرسال:</b> {phone}")

        btn_sim_send = msg_box.addButton(" 🚀 محاكاة وتوثيق الإرسال", QMessageBox.AcceptRole)
        msg_box.addButton("إلغاء", QMessageBox.RejectRole)

        msg_box.exec_()

        if msg_box.clickedButton() == btn_sim_send:
            log_success = self.dao.log_reminder_simulation(self.user_id, patient_name, phone, context_msg)

            if log_success:
                QMessageBox.information(self, "تمت المحاكاة", "تم تسجيل طلب التذكير في النظام بنجاح (Simulation Recorded in Audit Logs).")
                self.table_refills.clearSelection()
                self.table_expiring.clearSelection()
                self.btn_reminder.setEnabled(False)
            else:
                QMessageBox.warning(self, "خطأ", "فشل توثيق المحاكاة في قاعدة البيانات بسبب خلل أو صلاحيات غير كافية.")