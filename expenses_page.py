"""
وظيفة الملف: واجهة إدارة المصروفات التشغيلية والنثرية (Expenses Page).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Strict Dumb Client]&#58; لا توجد أي استعلامات SQL في هذه الواجهة مطلقاً. جميع القوائم تُجلب عبر الـ DAO.
- [Context Lock]&#58; تجميد النموذج العلوي بالكامل (Disable) في حال عدم وجود وردية مالية مفتوحة.
- [Governance Enforcement]&#58; الإبطال الإداري يتطلب سبباً كتابياً صريحاً ولا يقبل الفراغات.
- [Clean State UX]&#58; إعادة ضبط شاملة لعناصر الواجهة والتركيز (Focus) بعد كل اعتماد ناجح.
- [Safe Rendering]&#58; حماية الجداول من انهيارات الـ PyQt عند تمرير قيم (None) من القواعد القديمة وتوفير إرشاد بصري.
- [Live Session Context]&#58; لا يتم الاعتماد على shift_id مخزن داخل الكائن؛ بل يُقرأ من session وقت الحاجة أو عند تحديث السياق.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QLabel, QComboBox, QDateEdit, QFrame, QSplitter,
    QAbstractItemView, QStackedWidget, QInputDialog
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor
import logging

from models.expenses_dao import ExpensesDAO

logger = logging.getLogger(__name__)


class ExpensesPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.expenses_dao = ExpensesDAO()

        self.init_ui()
        self.load_initial_data()
        self.refresh_session_context()

    # ==========================================
    # Live Session Context
    # ==========================================
    def _get_current_shift_id(self):
        return self.session.get("shift_id") if self.session else None

    def refresh_session_context(self):
        """
        تحديث حيّ لسياق الجلسة عند فتح/إغلاق الوردية دون الحاجة لإعادة إنشاء الصفحة.
        """
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"
        self._update_shift_ui_state()

    def _update_shift_ui_state(self):
        current_shift_id = self._get_current_shift_id()

        if current_shift_id:
            self.lbl_shift.setText(f"الوردية الحالية: {current_shift_id}")
            self.lbl_shift.setStyleSheet(
                "font-size: 16px; font-weight: bold; padding: 5px 15px; border-radius: 5px; "
                "color: white; background-color: #27AE60;"
            )
            self.form_frame.setEnabled(True)
            self.form_frame.setToolTip("")
        else:
            self.lbl_shift.setText("⚠️ لا توجد وردية مفتوحة")
            self.lbl_shift.setStyleSheet(
                "font-size: 16px; font-weight: bold; padding: 5px 15px; border-radius: 5px; "
                "color: white; background-color: #C0392B;"
            )
            self.form_frame.setEnabled(False)
            self.form_frame.setToolTip("يجب فتح وردية مالية لتسجيل المصروفات.")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_session_context()
        self.load_expenses_history()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- العنوان ومعلومات الوردية ---
        header_layout = QHBoxLayout()
        title = QLabel("إدارة المصروفات التشغيلية والنثرية (الدرج النقدي)")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.lbl_shift = QLabel("")
        header_layout.addWidget(self.lbl_shift)

        main_layout.addLayout(header_layout)

        main_splitter = QSplitter(Qt.Vertical)

        # ==========================================
        # القسم الأول: نموذج إدخال المصروف (Strict Validation)
        # ==========================================
        self.form_frame = QFrame()
        self.form_frame.setStyleSheet(
            "background-color: white; border-radius: 10px; padding: 15px; border: 1px solid #BDC3C7;"
        )
        form_layout = QVBoxLayout(self.form_frame)

        # --- الصف الأول ---
        row1_layout = QHBoxLayout()

        self.category_combo = QComboBox()
        self.category_combo.setStyleSheet("font-size: 16px; padding: 5px;")

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("أدخل المبلغ (مثال: 150.50)...")
        self.amount_input.setStyleSheet("font-size: 16px; padding: 5px;")

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setStyleSheet("font-size: 16px; padding: 5px;")

        row1_layout.addWidget(QLabel("الفئة المحاسبية:"), stretch=1)
        row1_layout.addWidget(self.category_combo, stretch=2)
        row1_layout.addWidget(QLabel("المبلغ (نقدي):"), stretch=1)
        row1_layout.addWidget(self.amount_input, stretch=2)
        row1_layout.addWidget(QLabel("التاريخ:"), stretch=1)
        row1_layout.addWidget(self.date_input, stretch=2)

        form_layout.addLayout(row1_layout)

        # --- الصف الثاني (Dynamic Entity Binding) ---
        row2_layout = QHBoxLayout()

        self.payee_type_combo = QComboBox()
        self.payee_type_combo.addItem("موظف / سلفة (Employee)", "employee")
        self.payee_type_combo.addItem("تشغيلي عام (Operational)", "operational")
        self.payee_type_combo.addItem("مسحوبات مُلاك (Owner Draw)", "owner_draw")
        self.payee_type_combo.addItem("أخرى (Other)", "other")
        self.payee_type_combo.setStyleSheet("font-size: 16px; padding: 5px;")
        self.payee_type_combo.currentIndexChanged.connect(self.on_payee_type_changed)

        self.payee_stack = QStackedWidget()

        self.payee_entity_combo = QComboBox()
        self.payee_entity_combo.setStyleSheet("font-size: 16px; padding: 5px;")

        self.payee_text_input = QLineEdit()
        self.payee_text_input.setPlaceholderText("اسم / وصف المستفيد...")
        self.payee_text_input.setStyleSheet("font-size: 16px; padding: 5px;")

        self.payee_stack.addWidget(self.payee_entity_combo)
        self.payee_stack.addWidget(self.payee_text_input)

        row2_layout.addWidget(QLabel("نوع المستفيد:"), stretch=1)
        row2_layout.addWidget(self.payee_type_combo, stretch=2)
        row2_layout.addWidget(QLabel("جهة الصرف:"), stretch=1)
        row2_layout.addWidget(self.payee_stack, stretch=3)

        form_layout.addLayout(row2_layout)

        # --- الصف الثالث ---
        row3_layout = QHBoxLayout()

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("البيان أو الملاحظات (إلزامي لبعض الفئات)...")
        self.notes_input.setStyleSheet(
            "font-size: 16px; padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )

        self.btn_execute = QPushButton(" 🔄 اعتماد المصروف وخصم الصندوق")
        self.btn_execute.setFixedHeight(45)
        self.btn_execute.setCursor(Qt.PointingHandCursor)
        self.btn_execute.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; font-size: 16px; "
            "padding: 0 20px; border-radius: 5px;"
        )
        self.btn_execute.clicked.connect(self.execute_expense)

        row3_layout.addWidget(QLabel("البيان:"), stretch=1)
        row3_layout.addWidget(self.notes_input, stretch=4)
        row3_layout.addWidget(self.btn_execute, stretch=2)

        form_layout.addLayout(row3_layout)
        main_splitter.addWidget(self.form_frame)

        # ==========================================
        # القسم الثاني: السجل التاريخي والإبطال
        # ==========================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 10, 0, 0)

        history_header = QHBoxLayout()
        history_title = QLabel("السجل التاريخي للمصروفات (Immutability Log)")
        history_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495E;")

        btn_refresh = QPushButton(" تحديث السجل")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.load_expenses_history)
        btn_refresh.setStyleSheet("font-size: 14px; padding: 5px 15px;")

        self.btn_void = QPushButton(" إبطال المصروف وعكس القيد (إداري)")
        self.btn_void.setCursor(Qt.PointingHandCursor)
        self.btn_void.clicked.connect(self.void_selected_expense)
        self.btn_void.setStyleSheet(
            "background-color: #C0392B; color: white; font-weight: bold; font-size: 14px; padding: 5px 15px;"
        )

        history_header.addWidget(history_title)
        history_header.addStretch()
        history_header.addWidget(btn_refresh)
        history_header.addWidget(self.btn_void)

        if self.user_role != 'admin':
            self.btn_void.hide()

        bottom_layout.addLayout(history_header)

        self.history_table = QTableWidget()
        headers = ["رقم القيد", "الفئة", "المبلغ", "التاريخ", "المستفيد", "بواسطة", "الوردية", "الحالة", "الملاحظات"]
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setLayoutDirection(Qt.RightToLeft)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet("font-size: 14px;")

        bottom_layout.addWidget(self.history_table)
        main_splitter.addWidget(bottom_widget)

        main_splitter.setSizes([200, 400])
        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)

    # ==========================================
    # الدوال التشغيلية والتفاعلية
    # ==========================================
    def load_initial_data(self):
        self.load_categories()
        self.on_payee_type_changed()
        self.load_expenses_history()

    def load_categories(self):
        self.category_combo.clear()
        for cat in self.expenses_dao.get_active_categories():
            self.category_combo.addItem(cat['name'], cat['id'])

    def on_payee_type_changed(self):
        payee_type = self.payee_type_combo.currentData()

        if payee_type == 'employee':
            self.payee_stack.setCurrentIndex(0)
            self.load_entities_for_payee(payee_type)
        else:
            self.payee_stack.setCurrentIndex(1)
            self.payee_text_input.clear()

    def load_entities_for_payee(self, entity_type):
        """تحميل الكيانات المسموح بها فقط لهذه الصفحة."""
        self.payee_entity_combo.clear()

        if entity_type == 'employee':
            employees = self.expenses_dao.get_active_employees()
            if not employees:
                self.payee_entity_combo.addItem("لا يوجد موظفين نشطين", None)
            else:
                for emp in employees:
                    self.payee_entity_combo.addItem(f"موظف: {emp['name']}", emp['id'])

    def load_expenses_history(self):
        """[None-Safe Rendering]: منع انهيار الجدول بسبب قيم NULL التاريخية"""
        expenses = self.expenses_dao.get_all_expenses()
        self.history_table.setRowCount(0)

        payee_map = {
            "vendor": "مورد",
            "employee": "موظف",
            "operational": "تشغيلي",
            "owner_draw": "مسحوبات ملاك",
            "other": "أخرى"
        }

        for row_idx, exp in enumerate(expenses):
            self.history_table.insertRow(row_idx)

            r_status = exp.get('status') or "completed"
            status_str = "مبطل ❌" if r_status == 'voided' else "مكتمل ✅"

            p_type_ar = payee_map.get(exp['payee_type'], str(exp['payee_type'] or "-"))
            p_name = exp.get('payee_name') or "-"
            payee_display = f"[{p_type_ar}] {p_name}"

            items_text = [
                str(exp['id']),
                str(exp.get('category_name') or "-"),
                f"{exp['amount']:,.2f}" if exp.get('amount') is not None else "0.00",
                str(exp.get('expense_date') or "-"),
                payee_display,
                str(exp.get('username') or "-"),
                str(exp.get('shift_id')) if exp.get('shift_id') is not None else "-",
                status_str,
                str(exp.get('notes') or "-")
            ]

            for col_idx, text in enumerate(items_text):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 7:
                    item.setData(Qt.UserRole, r_status)

                if r_status == 'voided':
                    item.setForeground(QColor("#7F8C8D"))
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)

                self.history_table.setItem(row_idx, col_idx, item)

    # ==========================================
    # التنفيذ والاعتماد
    # ==========================================
    def execute_expense(self):
        self.refresh_session_context()
        current_shift_id = self._get_current_shift_id()

        if not self.user_id or not current_shift_id:
            QMessageBox.critical(self, "خطأ أمني", "المستخدم أو الوردية مفقودة.")
            return

        category_id = self.category_combo.currentData()
        amount_text = self.amount_input.text().strip()
        expense_date = self.date_input.date().toString("yyyy-MM-dd")
        payee_type = self.payee_type_combo.currentData()
        notes = self.notes_input.text().strip()

        payee_id = None
        payee_name = None

        if payee_type in ['vendor', 'employee']:
            payee_id = self.payee_entity_combo.currentData()
            if not payee_id:
                QMessageBox.warning(self, "تنبيه", "الرجاء تحديد الكيان المستفيد (لا يمكن اختيار قائمة فارغة).")
                return
        else:
            payee_name = self.payee_text_input.text().strip()

        if not amount_text:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال مبلغ المصروف.")
            self.amount_input.setFocus()
            return

        confirm = QMessageBox.question(
            self,
            "تأكيد المصروف",
            f"هل أنت متأكد من اعتماد المصروف النقدي بمبلغ ({amount_text})؟\n"
            "سيتم خصم المبلغ من الرصيد النظري للوردية الحالية.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        # التفويض الكامل للنواة
        success, result = self.expenses_dao.process_expense(
            user_id=self.user_id,
            shift_id=current_shift_id,
            category_id=category_id,
            amount=amount_text,
            expense_date=expense_date,
            payee_type=payee_type,
            payee_name=payee_name,
            payee_id=payee_id,
            notes=notes
        )

        if success:
            QMessageBox.information(self, "تم الاعتماد", f"تم تسجيل المصروف بنجاح. رقم القيد: {result['expense_id']}")
            self._reset_form()
            self.load_expenses_history()
        else:
            QMessageBox.critical(self, "رفض سيادي", f"تم رفض العملية من النواة:\n{result}")

    def _reset_form(self):
        """إعادة ضبط الواجهة لحالة الصفر بعد الاعتماد لتنظيف السياق"""
        self.amount_input.clear()
        self.payee_text_input.clear()
        self.notes_input.clear()
        self.date_input.setDate(QDate.currentDate())
        if self.category_combo.count() > 0:
            self.category_combo.setCurrentIndex(0)
        self.payee_type_combo.setCurrentIndex(0)
        self.amount_input.setFocus()

    def void_selected_expense(self):
        self.refresh_session_context()
        current_shift_id = self._get_current_shift_id()

        if not self.user_id or not current_shift_id:
            QMessageBox.warning(self, "تنبيه", "لا يمكن إبطال المصروف بدون وردية مالية مفتوحة.")
            return

        selected_row = self.history_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مصروف من السجل التاريخي لإبطاله.")
            return

        raw_status = self.history_table.item(selected_row, 7).data(Qt.UserRole)
        if raw_status == 'voided':
            QMessageBox.warning(self, "تنبيه", "هذا المصروف مُبطل مسبقاً.")
            return

        expense_id = int(self.history_table.item(selected_row, 0).text())
        cat_name = self.history_table.item(selected_row, 1).text()
        amount_val = self.history_table.item(selected_row, 2).text()
        orig_shift = self.history_table.item(selected_row, 6).text()

        # حوكمة السبب الإداري ومنع الفراغات
        reason, ok = QInputDialog.getText(
            self,
            "إبطال مصروف",
            f"سبب إبطال المصروف رقم {expense_id} (مبلغ {amount_val}):\n(السبب إلزامي ولن يتم الإبطال بدونه)"
        )

        if not ok:
            return
        safe_reason = reason.strip()

        if not safe_reason:
            QMessageBox.warning(self, "رفض إداري", "لا يمكن إبطال مصروف مالي بدون تقديم مبرر كتابي واضح.")
            return

        confirm = QMessageBox.question(
            self,
            "تأكيد الإبطال",
            f"هل أنت متأكد من إبطال المصروف ({cat_name}) المخصص للوردية الأصلية ({orig_shift})؟",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.expenses_dao.void_expense(self.user_id, current_shift_id, expense_id, safe_reason)
            if success:
                self.load_expenses_history()
                self.history_table.clearSelection()
                QMessageBox.information(self, "تم الإبطال", msg)
            else:
                QMessageBox.critical(self, "رفض العملية", msg)