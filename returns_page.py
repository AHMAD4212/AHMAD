"""
وظيفة الملف: واجهة إدارة المرتجعات (Returns Page).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Strict Dumb Client]&#58; تعتمد على quote_return للمعاينة، و process_return للاعتماد. لا تحسب شيئاً محلياً.
- [UI/Logic Decoupling]&#58; تعتمد على Qt.UserRole لتقييم حالة السجل التاريخي (voided/completed) بعيداً عن النصوص البصرية.
- [Clean State UX]&#58; التنظيف الصارم لحالة الواجهة (Tooltips, Inputs, Focus) عند كل عملية بحث أو إبطال أو فلترة.
- [Data Truth Alignment]&#58; تمت إزالة سبب الإرجاع السطري ليتطابق العقد البصري 100% مع قدرات النواة.
- [Dashboard Integration Update]&#58; دعم الفلترة الخارجية عبر (apply_external_filter) مع فلتر (مرتجعات اليوم) والتعامل اللطيف مع حالة غياب الوردية.
- [Live Session Context]&#58; لا يتم الاعتماد على shift_id مخزن داخل الكائن؛ بل يُقرأ من session وقت الحاجة أو عند تحديث السياق.
"""

from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QLabel, QSpinBox, QFrame, QSplitter, QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
import logging

from models.returns_dao import ReturnsDAO

logger = logging.getLogger(__name__)


class ReturnsPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.returns_dao = ReturnsDAO()
        self.current_sale_id = None
        self._is_rendering = False

        # نظام إدارة حالة الفلترة للسجل التاريخي: None, 'today'
        self.active_filter = None

        self.init_ui()
        self.refresh_session_context()
        self.load_returns_history()

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
        self._update_shift_banner()

    def _update_shift_banner(self):
        current_shift_id = self._get_current_shift_id()
        if current_shift_id:
            self.no_shift_banner.hide()
        else:
            self.no_shift_banner.show()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_session_context()
        self.load_returns_history()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # ---------------------------------------------------------
        # التعامل اللطيف مع حالة عدم وجود وردية (Graceful Degradation)
        # ---------------------------------------------------------
        self.no_shift_banner = QLabel(
            "⚠️ لا توجد وردية مالية مفتوحة. يمكنك تصفح المرتجعات السابقة براحة، ولكن إنشاء أو إبطال مرتجع يتطلب فتح وردية من لوحة التحكم."
        )
        self.no_shift_banner.setStyleSheet("""
            background-color: #FFF3CD; 
            color: #856404; 
            border: 1px solid #FFEEBA; 
            padding: 10px 15px; 
            font-weight: bold; 
            font-size: 15px; 
            border-radius: 6px;
            font-family: 'Times New Roman';
        """)
        main_layout.addWidget(self.no_shift_banner)

        title = QLabel("إدارة المرتجعات والتسويات العكسية")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        main_layout.addWidget(title)

        main_splitter = QSplitter(Qt.Vertical)

        # ==========================================
        # القسم العلوي: البحث وإنشاء المرتجع
        # ==========================================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        search_frame = QFrame()
        search_frame.setStyleSheet("background-color: white; border-radius: 10px; padding: 10px;")
        search_layout = QHBoxLayout(search_frame)

        self.sale_id_input = QLineEdit()
        self.sale_id_input.setPlaceholderText("أدخل رقم فاتورة البيع المرجعي (Sale ID)...")
        self.sale_id_input.setFixedHeight(45)
        self.sale_id_input.setStyleSheet("font-size: 16px; padding: 5px; font-family: 'Times New Roman'; border: 1px solid #BDC3C7; border-radius: 5px;")
        self.sale_id_input.returnPressed.connect(self.fetch_sale_details)

        btn_search = QPushButton(" بحث وجلب الفاتورة")
        btn_search.setFixedHeight(45)
        btn_search.setCursor(Qt.PointingHandCursor)
        btn_search.setStyleSheet("background-color: #34495E; color: white; font-weight: bold; font-size: 16px; padding: 0 20px; border-radius: 5px;")
        btn_search.clicked.connect(self.fetch_sale_details)

        search_layout.addWidget(QLabel("رقم الفاتورة:"))
        search_layout.addWidget(self.sale_id_input, stretch=2)
        search_layout.addWidget(btn_search, stretch=1)
        top_layout.addWidget(search_frame)

        info_layout = QHBoxLayout()
        self.sale_info_label = QLabel("يرجى إدخال رقم الفاتورة لجلب بياناتها.")
        self.sale_info_label.setStyleSheet("font-size: 16px; color: #7F8C8D; font-weight: bold;")

        self.lbl_quote_error = QLabel("")
        self.lbl_quote_error.setStyleSheet("color: #C0392B; font-weight: bold; font-size: 14px;")
        self.lbl_quote_error.hide()

        info_layout.addWidget(self.sale_info_label)
        info_layout.addStretch()
        info_layout.addWidget(self.lbl_quote_error)
        top_layout.addLayout(info_layout)

        # --- جدول الأصناف القابلة للإرجاع ---
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID السطر", "اسم الدواء", "التشغيلة", "المباع", "متاح للإرجاع",
            "الكمية المرتجعة", "قيمة الرد", "ملاحظات سريرية"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.hideColumn(0)
        top_layout.addWidget(self.table)

        execution_layout = QHBoxLayout()

        self.general_reason_input = QLineEdit()
        self.general_reason_input.setPlaceholderText("سبب المرتجع العام (اختياري)...")
        self.general_reason_input.setFixedHeight(50)
        self.general_reason_input.setStyleSheet("font-size: 16px; padding: 5px; border: 1px solid #BDC3C7; border-radius: 5px;")
        self.general_reason_input.setEnabled(False)

        self.lbl_total_refund = QLabel("إجمالي المسترد: 0.00")
        self.lbl_total_refund.setStyleSheet("font-size: 20px; font-weight: bold; color: #27AE60; padding: 0 15px;")

        self.btn_execute = QPushButton(" 🔄 اعتماد المرتجع وتسوية الصندوق")
        self.btn_execute.setFixedHeight(50)
        self.btn_execute.setCursor(Qt.PointingHandCursor)
        self.btn_execute.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; font-size: 18px; padding: 0 30px; border-radius: 5px;")
        self.btn_execute.clicked.connect(self.execute_return)
        self.btn_execute.setEnabled(False)

        execution_layout.addWidget(self.general_reason_input, stretch=2)
        execution_layout.addWidget(self.lbl_total_refund)
        execution_layout.addWidget(self.btn_execute, stretch=1)

        top_layout.addLayout(execution_layout)
        main_splitter.addWidget(top_widget)

        # ==========================================
        # القسم السفلي: السجل التاريخي (Immutability UI)
        # ==========================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 20, 0, 0)

        history_header = QHBoxLayout()
        history_title = QLabel("السجل التاريخي للمرتجعات (Immutability Log)")
        history_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2C3E50;")

        # --- أزرار الفلترة ---
        self.btn_today_filter = QPushButton(" مرتجعات اليوم فقط")
        self.btn_today_filter.setCheckable(True)
        self.btn_today_filter.setCursor(Qt.PointingHandCursor)
        self.btn_today_filter.clicked.connect(self.toggle_history_filter)
        self.btn_today_filter.setStyleSheet("""
            QPushButton { background-color: #2980B9; color: white; font-weight: bold; font-size: 14px; padding: 5px 15px; border-radius: 4px;}
            QPushButton:checked { background-color: #1ABC9C; }
        """)

        btn_refresh_history = QPushButton(" تحديث السجل")
        btn_refresh_history.setCursor(Qt.PointingHandCursor)
        btn_refresh_history.clicked.connect(self.load_returns_history)
        btn_refresh_history.setStyleSheet("font-size: 14px; padding: 5px 15px;")

        self.btn_void_return = QPushButton(" إبطال مرتجع وعكس القيود (إداري)")
        self.btn_void_return.setCursor(Qt.PointingHandCursor)
        self.btn_void_return.clicked.connect(self.void_selected_return)
        self.btn_void_return.setStyleSheet("background-color: #C0392B; color: white; font-weight: bold; font-size: 14px; padding: 5px 15px;")

        history_header.addWidget(history_title)
        history_header.addStretch()
        history_header.addWidget(self.btn_today_filter)
        history_header.addWidget(btn_refresh_history)
        history_header.addWidget(self.btn_void_return)

        if self.user_role != 'admin':
            self.btn_void_return.hide()

        bottom_layout.addLayout(history_header)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "رقم المرتجع", "الفاتورة الأصلية", "بواسطة", "تاريخ المرتجع",
            "إجمالي المسترد", "السبب", "الحالة"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setLayoutDirection(Qt.RightToLeft)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")

        bottom_layout.addWidget(self.history_table)
        main_splitter.addWidget(bottom_widget)

        main_splitter.setSizes([450, 250])
        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)

    # ==========================================
    # API for Main Controller (Dashboard Routing)
    # ==========================================
    def apply_external_filter(self, filter_type):
        """
        تُستدعى من خارج الكلاس لضبط الفلترة برمجياً (مثل القفز من لوحة التحكم).
        """
        self.refresh_session_context()

        # تنظيف النصف العلوي (البحث) لضمان عدم حدوث تشويش على تجربة المستخدم
        self.sale_id_input.blockSignals(True)
        self.clear_table_and_state()
        self.sale_id_input.clear()
        self.sale_id_input.blockSignals(False)

        if filter_type == "today_returns":
            self.btn_today_filter.setChecked(True)
            self.active_filter = 'today'
        else:
            self.btn_today_filter.setChecked(False)
            self.active_filter = None

        self._update_filter_button_ui()
        self.load_returns_history()

    def toggle_history_filter(self):
        if self.btn_today_filter.isChecked():
            self.active_filter = 'today'
        else:
            self.active_filter = None

        self._update_filter_button_ui()
        self.load_returns_history()

    def _update_filter_button_ui(self):
        if self.active_filter == 'today':
            self.btn_today_filter.setText("إلغاء فلتر اليوم")
        else:
            self.btn_today_filter.setText("مرتجعات اليوم فقط")

    # ==========================================
    # 1. جلب البيانات والتنظيف
    # ==========================================
    def clear_table_and_state(self):
        self.current_sale_id = None
        self.table.setRowCount(0)
        self.lbl_total_refund.setText("إجمالي المسترد: 0.00")
        self.btn_execute.setEnabled(False)

        self.lbl_quote_error.hide()
        self.lbl_quote_error.setText("")

        self.general_reason_input.clear()
        self.general_reason_input.setEnabled(False)

        self.sale_info_label.setText("يرجى إدخال رقم الفاتورة لجلب بياناتها.")
        self.sale_id_input.setFocus()

    def fetch_sale_details(self):
        sale_id_text = self.sale_id_input.text().strip()
        if not sale_id_text.isdigit():
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال رقم فاتورة صحيح (أرقام فقط).")
            return

        sale_id = int(sale_id_text)
        result = self.returns_dao.get_sale_for_return(sale_id)

        if not result or not result.get("header"):
            QMessageBox.warning(self, "تنبيه", "فاتورة البيع غير موجودة في النظام.")
            self.clear_table_and_state()
            return

        header = result["header"]
        items = result.get("lines", [])

        if not items:
            QMessageBox.information(self, "معلومة", "تم إرجاع جميع أصناف هذه الفاتورة مسبقاً، لا يوجد شيء قابل للإرجاع.")
            self.clear_table_and_state()
            self.sale_info_label.setText(f"تم استنفاد مرتجعات الفاتورة رقم ({sale_id}) بالكامل.")
            return

        self.current_sale_id = sale_id
        sale_date = header['sale_date']
        total_amount = header['total_amount']
        cust_name = header['customer_name']
        orig_shift = header['original_shift_id']

        self.sale_info_label.setText(
            f"فاتورة: {sale_id} | التاريخ: {sale_date} | الإجمالي: {total_amount:,.2f} | العميل: {cust_name} | الوردية: {orig_shift}"
        )

        self.general_reason_input.setEnabled(True)
        self.general_reason_input.clear()

        self._is_rendering = True
        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(item['sale_item_id'])))

            med_name = item['medicine_name']
            if item['is_controlled'] == 1:
                med_name += " 🔴"
            if item['prescription_item_id']:
                med_name += " 📜"

            name_widget = QTableWidgetItem(med_name)
            if item['is_controlled'] == 1:
                name_widget.setForeground(QColor("#C0392B"))
            self.table.setItem(row, 1, name_widget)

            self.table.setItem(row, 2, QTableWidgetItem(item['batch_number']))
            self.table.setItem(row, 3, QTableWidgetItem(str(item['sold_qty'])))
            self.table.setItem(row, 4, QTableWidgetItem(str(item['returnable_qty'])))

            qty_spin = QSpinBox()
            qty_spin.setRange(0, item['returnable_qty'])
            qty_spin.setValue(0)
            qty_spin.setStyleSheet("font-size: 16px; padding: 5px;")
            qty_spin.valueChanged.connect(self.refresh_quote)
            self.table.setCellWidget(row, 5, qty_spin)

            refund_widget = QTableWidgetItem("0.00")
            refund_widget.setForeground(QColor("#7F8C8D"))
            self.table.setItem(row, 6, refund_widget)

            notes = ""
            if item['is_controlled'] == 1:
                notes += "رقابي "
            if item['prescription_item_id']:
                notes += "سيعيد فتح الوصفة "

            notes_widget = QTableWidgetItem(notes.strip())
            notes_widget.setForeground(QColor("#8E44AD"))
            self.table.setItem(row, 7, notes_widget)

            for col in [0, 1, 2, 3, 4, 6, 7]:
                if self.table.item(row, col):
                    self.table.item(row, col).setTextAlignment(Qt.AlignCenter)

        self._is_rendering = False
        self.refresh_quote()

    # ==========================================
    # 2. التسعير العكسي اللحظي (Dumb Client)
    # ==========================================
    def refresh_quote(self):
        if self._is_rendering or not self.current_sale_id:
            return

        return_lines = []
        for row in range(self.table.rowCount()):
            si_id = int(self.table.item(row, 0).text())
            qty_widget = self.table.cellWidget(row, 5)
            if qty_widget and qty_widget.value() > 0:
                return_lines.append({
                    "sale_item_id": si_id,
                    "return_qty": qty_widget.value()
                })

        if not return_lines:
            self.lbl_total_refund.setText("إجمالي المسترد: 0.00")
            self.btn_execute.setEnabled(False)
            self.lbl_quote_error.hide()

            for row in range(self.table.rowCount()):
                ref_w = self.table.item(row, 6)
                if ref_w:
                    ref_w.setText("0.00")
                    ref_w.setForeground(QColor("#7F8C8D"))
                    ref_w.setToolTip("")
            return

        quote_result = self.returns_dao.quote_return(self.current_sale_id, return_lines)

        has_errors = False
        if quote_result.get("general_error"):
            self.lbl_quote_error.setText(f"⚠️ خطأ: {quote_result['general_error']}")
            self.lbl_quote_error.show()
            has_errors = True
        else:
            self.lbl_quote_error.hide()

        invalid_map = {inv['sale_item_id']: inv['reason'] for inv in quote_result.get("invalid_lines", [])}
        if invalid_map:
            has_errors = True

        eligible_map = {el['sale_item_id']: el['refund_amount'] for el in quote_result.get("eligible_lines", [])}

        for row in range(self.table.rowCount()):
            si_id = int(self.table.item(row, 0).text())
            ref_w = self.table.item(row, 6)

            ref_w.setToolTip("")

            if si_id in invalid_map:
                ref_w.setText("مرفوض")
                ref_w.setForeground(QColor("#C0392B"))
                ref_w.setToolTip(invalid_map[si_id])
            elif si_id in eligible_map:
                ref_w.setText(f"{eligible_map[si_id]:.2f}")
                ref_w.setForeground(QColor("#27AE60"))
                ref_w.setToolTip("رد مالي مبني على السجل التاريخي (Pro-Rata).")
            else:
                ref_w.setText("0.00")
                ref_w.setForeground(QColor("#7F8C8D"))

        self.lbl_total_refund.setText(f"إجمالي المسترد: {quote_result.get('total_refund_amount', 0.0):,.2f}")

        can_execute = (not has_errors) and (quote_result.get("total_refund_amount", 0) > 0)
        self.btn_execute.setEnabled(can_execute)

    # ==========================================
    # 3. الاعتماد السيادي للمرتجع (Process Return)
    # ==========================================
    def execute_return(self):
        if not self.current_sale_id:
            return

        self.refresh_session_context()
        current_shift_id = self._get_current_shift_id()

        # الاستبدال اللطيف للتنبيهات بدل الرسالة القاسية
        if not self.user_id or not current_shift_id:
            QMessageBox.warning(
                self,
                "تنبيه تشغيلي",
                "عذراً، لا يمكن تنفيذ مرتجع مالي لعدم وجود وردية مالية مفتوحة.\nيرجى العودة للوحة التحكم وفتح وردية للاستمرار."
            )
            return

        general_reason = self.general_reason_input.text().strip()
        items_to_return = []

        for row in range(self.table.rowCount()):
            si_id = int(self.table.item(row, 0).text())
            qty_widget = self.table.cellWidget(row, 5).value()
            if qty_widget > 0:
                items_to_return.append({
                    "sale_item_id": si_id,
                    "return_qty": qty_widget
                })

        if not items_to_return:
            return

        confirm = QMessageBox.question(
            self,
            "تأكيد الاعتماد",
            "هل أنت متأكد من تنفيذ المرتجع؟\nسيتم إخراج النقدية وإعادة البضاعة للمخزون، وتسوية الوصفات المرتبطة.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        success, result = self.returns_dao.process_return(
            sale_id=self.current_sale_id,
            user_id=self.user_id,
            shift_id=current_shift_id,
            items_to_return=items_to_return,
            reason=general_reason
        )

        if success:
            return_id = result.get("return_id")
            total_refund = result.get("total_return_amount")

            QMessageBox.information(
                self,
                "نجاح العملية",
                f"تم اعتماد المرتجع رقم {return_id} بنجاح.\n\n"
                f"المبلغ الإجمالي المسترد من الصندوق: {total_refund:,.2f}"
            )
            self.fetch_sale_details()
            self.load_returns_history()
        else:
            QMessageBox.critical(self, "رفض سيادي", f"فشل تنفيذ المرتجع:\n{result}")
            self.refresh_quote()

    # ==========================================
    # 4. السجل التاريخي والإبطال الإداري (Immutability)
    # ==========================================
    def load_returns_history(self):
        returns = self.returns_dao.get_all_returns()
        self.history_table.setRowCount(0)

        # تطبيق فلتر "اليوم" إذا كان مفعلاً
        today_str = datetime.now().strftime("%Y-%m-%d")
        filtered_returns = []

        for r in returns:
            # r[3] هو تاريخ المرتجع (string)
            if self.active_filter == 'today':
                if not r[3] or not str(r[3]).startswith(today_str):
                    continue
            filtered_returns.append(r)

        for row_idx, r in enumerate(filtered_returns):
            self.history_table.insertRow(row_idx)
            # r = (id, sale_id, username, return_date, total_amount, reason, status)

            r_status = r[6]
            status_str = "مبطل ❌" if r_status == 'voided' else "مكتمل ✅"

            items_text = [
                str(r[0]), str(r[1]), r[2], r[3], f"{r[4]:,.2f}", r[5] if r[5] else "-", status_str
            ]

            for col_idx, text in enumerate(items_text):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 6:
                    item.setData(Qt.UserRole, r_status)

                if r_status == 'voided':
                    item.setForeground(QColor("#7F8C8D"))
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)

                self.history_table.setItem(row_idx, col_idx, item)

    def void_selected_return(self):
        self.refresh_session_context()
        current_shift_id = self._get_current_shift_id()

        # الاستبدال اللطيف للتنبيهات
        if not self.user_id or not current_shift_id:
            QMessageBox.warning(
                self,
                "تنبيه تشغيلي",
                "عذراً، لا يمكن إبطال المرتجع لعدم وجود وردية مالية مفتوحة لتسجيل القيود العكسية."
            )
            return

        selected_row = self.history_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مرتجع من الجدول السفلي لإبطاله.")
            return

        raw_status = self.history_table.item(selected_row, 6).data(Qt.UserRole)
        if raw_status == 'voided':
            QMessageBox.warning(self, "تنبيه", "هذا المرتجع مُبطل مسبقاً ولا يمكن إبطاله مرة أخرى.")
            return

        return_id = int(self.history_table.item(selected_row, 0).text())
        total_amount = self.history_table.item(selected_row, 4).text()
        target_sale_id = self.history_table.item(selected_row, 1).text()

        confirm = QMessageBox.question(
            self,
            "تأكيد الإبطال الإداري",
            f"هل أنت متأكد من (إبطال) المرتجع رقم ({return_id})؟\n"
            f"سيتم استقطاع البضاعة مجدداً وإرجاع مبلغ {total_amount} للصندوق كقيد وارد.\n"
            "لن يتم حذف السجل بل سيتم وسمه بـ (مبطل) للحفاظ على التوثيق.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.returns_dao.void_return(self.user_id, current_shift_id, return_id)
            if success:
                self.load_returns_history()
                QMessageBox.information(self, "تم الإبطال", msg)

                if self.current_sale_id and str(self.current_sale_id) == target_sale_id:
                    self.fetch_sale_details()
            else:
                QMessageBox.critical(self, "رفض العملية", msg)