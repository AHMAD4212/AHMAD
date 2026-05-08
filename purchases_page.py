"""
وظيفة الملف: واجهة إدخال المشتريات (Execution Workflow).

الطبقة: Presentation Layer

ملاحظة معمارية وأمنية:
- [UI RBAC]&#58; الصفحة محجوبة بالكامل عن غير المدراء (admin).
- [Integration V16]&#58; تم إضافة وضع (الاستيراد من أمر شراء) Strict Traceability Workflow.
- [Operational Fix]&#58; دعم الاستلام الجزئي الحقيقي عبر النقر المزدوج لاستبعاد الأصناف التي لم تصل.
- [UX Fix]&#58; تصفير هادئ وآمن (Force Reset) بعد نجاح اعتماد الفاتورة.
- [Financial Activation]&#58; تفعيل الشراء النقدي/الآجل/المختلط من الواجهة وربطه بسياق الوردية.
- [UI SSOT]&#58; لا يتم استخراج إجمالي الفاتورة من النص البصري، بل من السلة نفسها.
- [History View]&#58; إضافة سجل فواتير الشراء السابقة مع تحميل تلقائي وتحديث مستقل بعد كل اعتماد.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QLabel, QComboBox, QDateEdit, QDoubleSpinBox,
    QSpinBox, QFrame, QAbstractItemView, QDialog
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor

from models.purchases_dao import PurchasesDAO
from models.suppliers_dao import SuppliersDAO
from models.medicine_dao import MedicineDAO
from models.purchase_orders_dao import PurchaseOrdersDAO


class POSearchDialog(QDialog):
    """نافذة مبسطة لاختيار أمر الشراء المراد استيراده."""

    def __init__(self, po_dao, parent=None):
        super().__init__(parent)
        self.po_dao = po_dao
        self.selected_po_id = None
        self.setWindowTitle("📥 استيراد من أمر شراء معتمد")
        self.resize(600, 400)
        self.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel("اختر أمر شراء (يجب أن يكون معتمداً أو مستلماً جزئياً):")
        info.setStyleSheet("font-weight: bold; color: #2980B9;")
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "رقم الطلب", "المورد", "الحالة", "التاريخ المتوقع"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(self.accept_selection)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        btn_select = QPushButton("استيراد الطلب المحدد")
        btn_select.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold;")
        btn_select.clicked.connect(self.accept_selection)

        btn_cancel = QPushButton("إلغاء")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_select)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.load_data()

    def load_data(self):
        orders = self.po_dao.get_importable_orders()
        self.table.setRowCount(0)

        for row, order in enumerate(orders):
            self.table.insertRow(row)
            for col, val in enumerate(order):
                item = QTableWidgetItem(str(val if val is not None else ""))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

    def accept_selection(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "يرجى تحديد أمر شراء أولاً.")
            return

        self.selected_po_id = int(self.table.item(row, 0).text())
        self.accept()


class PurchasesPage(QWidget):
    def __init__(self, session_data):
        super().__init__()

        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")
        self.shift_id = self.session.get("shift_id")

        self.purchase_dao = PurchasesDAO()
        self.supplier_dao = SuppliersDAO()
        self.medicine_dao = MedicineDAO()
        self.po_dao = PurchaseOrdersDAO()

        self.cart = []
        self.current_med_data = None

        self.selected_purchase_order_id = None
        self.selected_purchase_order_number = None
        self.import_mode_from_po = False

        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.init_ui()
            self.load_suppliers()
            self._refresh_financial_summary()
            self.load_purchase_history()

    def showEvent(self, event):
        super().showEvent(event)
        if self.user_role == 'admin':
            self.load_suppliers()
            self.load_purchase_history()
            self._refresh_financial_summary()

    # ==========================================
    # الحماية البصرية
    # ==========================================
    def init_access_denied_ui(self):
        layout = QVBoxLayout()
        warning_lbl = QLabel(
            "⛔ صلاحيات غير كافية.\nهذه الصفحة مخصصة لمدير النظام فقط (إدارة المشتريات وتكلفة البضاعة)."
        )
        warning_lbl.setAlignment(Qt.AlignCenter)
        warning_lbl.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';"
        )
        layout.addWidget(warning_lbl)
        self.setLayout(layout)

    # ==========================================
    # بناء الواجهة
    # ==========================================
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ------------------------------
        # العنوان والأزرار العليا
        # ------------------------------
        header_layout = QHBoxLayout()

        self.title_lbl = QLabel("تسجيل فاتورة شراء (مستقلة)")
        self.title_lbl.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )

        self.btn_import_po = QPushButton("📥 استيراد من أمر شراء معتمد")
        self.btn_import_po.setStyleSheet(
            "background-color: #8E44AD; color: white; font-weight: bold; "
            "font-size: 16px; padding: 5px 15px; border-radius: 5px;"
        )
        self.btn_import_po.setCursor(Qt.PointingHandCursor)
        self.btn_import_po.clicked.connect(self.open_import_dialog)

        self.btn_cancel_import = QPushButton("❌ إلغاء الربط (فاتورة حرة)")
        self.btn_cancel_import.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; "
            "font-size: 16px; padding: 5px 15px; border-radius: 5px;"
        )
        self.btn_cancel_import.setCursor(Qt.PointingHandCursor)
        self.btn_cancel_import.clicked.connect(lambda: self.reset_import_mode(force=False))
        self.btn_cancel_import.hide()

        header_layout.addWidget(self.title_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_cancel_import)
        header_layout.addWidget(self.btn_import_po)
        layout.addLayout(header_layout)

        # ------------------------------
        # بيانات رأس الفاتورة
        # ------------------------------
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white; border-radius: 10px; padding: 10px;")
        form_layout = QHBoxLayout(form_frame)

        self.supplier_combo = QComboBox()
        self.supplier_combo.setPlaceholderText("اختر المورد")
        self.supplier_combo.setFixedHeight(40)

        self.inv_num_input = QLineEdit()
        self.inv_num_input.setPlaceholderText("رقم فاتورة المورد (إلزامي)")
        self.inv_num_input.setFixedHeight(40)

        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setFixedHeight(40)

        form_layout.addWidget(QLabel("المورد:"))
        form_layout.addWidget(self.supplier_combo, stretch=2)
        form_layout.addWidget(QLabel("رقم الفاتورة:"))
        form_layout.addWidget(self.inv_num_input, stretch=1)
        form_layout.addWidget(QLabel("التاريخ:"))
        form_layout.addWidget(self.date_input, stretch=1)

        layout.addWidget(form_frame)

        # ------------------------------
        # الشريط المالي الجديد
        # ------------------------------
        financial_frame = QFrame()
        financial_frame.setStyleSheet(
            "background-color: #FBFCFC; border: 1px solid #D5DBDB; border-radius: 10px; padding: 10px;"
        )
        financial_layout = QHBoxLayout(financial_frame)

        self.paid_amount_spin = QDoubleSpinBox()
        self.paid_amount_spin.setDecimals(2)
        self.paid_amount_spin.setRange(0.0, 0.0)
        self.paid_amount_spin.setSingleStep(1.0)
        self.paid_amount_spin.setFixedHeight(40)
        self.paid_amount_spin.setPrefix("مدفوع نقداً الآن: ")
        self.paid_amount_spin.setKeyboardTracking(False)
        self.paid_amount_spin.valueChanged.connect(self._refresh_financial_summary)

        self.lbl_unpaid_amount = QLabel("المتبقي ذمة على المورد: 0.00")
        self.lbl_unpaid_amount.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #D35400; font-family: 'Times New Roman';"
        )

        self.lbl_payment_mode = QLabel("نوع السداد: غير محدد")
        self.lbl_payment_mode.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )

        self.lbl_shift_context = QLabel("")
        self.lbl_shift_context.setStyleSheet(
            "font-size: 15px; font-weight: bold; font-family: 'Times New Roman';"
        )

        financial_layout.addWidget(self.paid_amount_spin, stretch=2)
        financial_layout.addWidget(self.lbl_unpaid_amount, stretch=2)
        financial_layout.addWidget(self.lbl_payment_mode, stretch=2)
        financial_layout.addWidget(self.lbl_shift_context, stretch=2)

        layout.addWidget(financial_frame)

        # ------------------------------
        # الإدخال اليدوي
        # ------------------------------
        self.manual_entry_group = QFrame()
        manual_layout = QVBoxLayout(self.manual_entry_group)
        manual_layout.setContentsMargins(0, 0, 0, 0)

        action_layout1 = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث عن دواء (اسم/باركود)... واضغط Enter")
        self.search_input.setFixedHeight(40)
        self.search_input.setStyleSheet("border: 1px solid #3498DB;")
        self.search_input.returnPressed.connect(self.populate_med_data)

        action_layout1.addWidget(self.search_input, stretch=2)
        manual_layout.addLayout(action_layout1)

        action_layout2 = QHBoxLayout()

        self.batch_input = QLineEdit()
        self.batch_input.setPlaceholderText("التشغيلة")
        self.batch_input.setFixedHeight(40)

        self.expiry_input = QDateEdit()
        self.expiry_input.setDate(QDate.currentDate().addYears(1))
        self.expiry_input.setCalendarPopup(True)
        self.expiry_input.setFixedHeight(40)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 100000)
        self.qty_spin.setPrefix("الكمية: ")
        self.qty_spin.setFixedHeight(40)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setDecimals(2)
        self.cost_spin.setRange(0, 1000000)
        self.cost_spin.setPrefix("شراء: ")
        self.cost_spin.setFixedHeight(40)

        self.sell_spin = QDoubleSpinBox()
        self.sell_spin.setDecimals(2)
        self.sell_spin.setRange(0, 1000000)
        self.sell_spin.setPrefix("بيع: ")
        self.sell_spin.setFixedHeight(40)

        btn_add = QPushButton("⬇ إضافة للسلة")
        btn_add.clicked.connect(self.add_item_to_cart)
        btn_add.setFixedHeight(40)
        btn_add.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold;")

        action_layout2.addWidget(self.batch_input)
        action_layout2.addWidget(self.expiry_input)
        action_layout2.addWidget(self.qty_spin)
        action_layout2.addWidget(self.cost_spin)
        action_layout2.addWidget(self.sell_spin)
        action_layout2.addWidget(btn_add)
        manual_layout.addLayout(action_layout2)

        layout.addWidget(self.manual_entry_group)

        # ------------------------------
        # جدول السلة
        # ------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "ID", "اسم الدواء", "التشغيلة", "الصلاحية", "الكمية (الاستلام)",
            "المتبقي (PO)", "شراء", "بيع", "الإجمالي", "PO_Item_ID", "تحديث"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.hideColumn(9)
        self.table.doubleClicked.connect(self.handle_table_double_click)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 15px; font-family: 'Times New Roman'; }"
            "QHeaderView::section { font-size: 15px; font-weight: bold; font-family: 'Times New Roman'; }"
        )

        layout.addWidget(self.table)

        info_lbl = QLabel(
            "* لاستبعاد/حذف صنف من هذه الفاتورة: انقر نقراً مزدوجاً عليه.\n"
            "* لتحديث الكمية والتشغيلة للبنود المستوردة: اضغط على زر (تعديل) بجانب الصنف."
        )
        info_lbl.setStyleSheet("color: #7F8C8D; font-size: 13px; font-style: italic;")
        layout.addWidget(info_lbl)

        # ------------------------------
        # التذييل
        # ------------------------------
        footer_layout = QHBoxLayout()

        self.total_label = QLabel("الإجمالي: 0.00")
        self.total_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #27AE60; font-family: 'Times New Roman';"
        )

        btn_save = QPushButton("📥 اعتماد الفاتورة وترحيل للمخزون")
        btn_save.clicked.connect(self.save_invoice)
        btn_save.setFixedHeight(50)
        btn_save.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; "
            "font-size: 18px; padding: 0 30px; border-radius: 5px;"
        )

        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch()
        footer_layout.addWidget(btn_save)

        layout.addLayout(footer_layout)

        # ------------------------------
        # سجل فواتير الشراء السابقة
        # ------------------------------
        history_header_layout = QHBoxLayout()

        history_title = QLabel("سجل فواتير الشراء السابقة")
        history_title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #34495E; font-family: 'Times New Roman';"
        )

        self.btn_refresh_history = QPushButton("🔄 تحديث السجل")
        self.btn_refresh_history.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_history.clicked.connect(self.load_purchase_history)
        self.btn_refresh_history.setStyleSheet(
            "font-size: 14px; padding: 6px 16px; font-family: 'Times New Roman';"
        )

        history_header_layout.addWidget(history_title)
        history_header_layout.addStretch()
        history_header_layout.addWidget(self.btn_refresh_history)

        layout.addLayout(history_header_layout)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(9)
        self.history_table.setHorizontalHeaderLabels([
            "ID", "المورد", "رقم الفاتورة", "التاريخ",
            "الإجمالي", "المدفوع", "المتبقي", "الحالة", "تاريخ الإدخال"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet(
            "QTableWidget { font-size: 15px; font-family: 'Times New Roman'; }"
            "QHeaderView::section { font-size: 15px; font-weight: bold; font-family: 'Times New Roman'; }"
        )

        layout.addWidget(self.history_table)

        self.setLayout(layout)

    # ==========================================
    # Helpers مالية وسياقية
    # ==========================================
    def _get_current_shift_id(self):
        """قراءة مرنة من الجلسة المشتركة لضمان عدم تقادم shift_id."""
        self.shift_id = self.session.get("shift_id") if isinstance(self.session, dict) else None
        return self.shift_id

    def _calculate_cart_total(self):
        total = 0.0
        for item in self.cart:
            try:
                total += float(item.get("total", 0.0))
            except (TypeError, ValueError):
                continue
        return round(total, 2)

    def _refresh_shift_context_label(self):
        current_shift_id = self._get_current_shift_id()
        if current_shift_id:
            self.lbl_shift_context.setText(f"الوردية النقدية الحالية: {current_shift_id}")
            self.lbl_shift_context.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #27AE60; font-family: 'Times New Roman';"
            )
        else:
            self.lbl_shift_context.setText("لا توجد وردية مالية مفتوحة حالياً")
            self.lbl_shift_context.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';"
            )

    def _refresh_financial_summary(self):
        total_bill = self._calculate_cart_total()

        self.paid_amount_spin.blockSignals(True)
        self.paid_amount_spin.setMaximum(total_bill)
        if self.paid_amount_spin.value() > total_bill:
            self.paid_amount_spin.setValue(total_bill)
        paid_amount = round(float(self.paid_amount_spin.value()), 2)
        self.paid_amount_spin.blockSignals(False)

        unpaid_amount = round(total_bill - paid_amount, 2)

        self.lbl_unpaid_amount.setText(f"المتبقي ذمة على المورد: {unpaid_amount:,.2f}")

        if total_bill <= 0:
            mode_text = "نوع السداد: غير محدد"
            mode_color = "#7F8C8D"
        elif paid_amount == 0:
            mode_text = "نوع السداد: آجل بالكامل"
            mode_color = "#D35400"
        elif abs(paid_amount - total_bill) < 0.001:
            mode_text = "نوع السداد: نقدي كامل"
            mode_color = "#27AE60"
        else:
            mode_text = "نوع السداد: مختلط (نقد + ذمة)"
            mode_color = "#8E44AD"

        self.lbl_payment_mode.setText(mode_text)
        self.lbl_payment_mode.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {mode_color}; font-family: 'Times New Roman';"
        )

        self._refresh_shift_context_label()

    def _reset_manual_entry_fields(self):
        self.search_input.clear()
        self.batch_input.clear()
        self.qty_spin.setValue(1)
        self.cost_spin.setValue(0.0)
        self.sell_spin.setValue(0.0)
        self.current_med_data = None

    def _set_history_status_style(self, item, status_value):
        status_text = str(status_value).strip().lower()
        if status_text == "paid":
            item.setForeground(QColor("#27AE60"))
        elif status_text == "partial":
            item.setForeground(QColor("#F39C12"))
        elif status_text == "unpaid":
            item.setForeground(QColor("#C0392B"))

    # ==========================================
    # تحميل الموردين
    # ==========================================
    def load_suppliers(self):
        current_supplier = self.supplier_combo.currentData()

        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("-- غير محدد --", None)

        for sup in self.supplier_dao.get_all_suppliers():
            self.supplier_combo.addItem(f"{sup[1]} - {sup[3]}", sup[0])

        if current_supplier is not None:
            idx = self.supplier_combo.findData(current_supplier)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)

        self.supplier_combo.blockSignals(False)

    # ==========================================
    # سجل فواتير الشراء
    # ==========================================
    def load_purchase_history(self):
        if self.user_role != 'admin':
            return

        self.history_table.setRowCount(0)
        purchases = self.purchase_dao.get_all_purchases()

        for row_idx, row_data in enumerate(purchases):
            self.history_table.insertRow(row_idx)

            for col_idx, col_data in enumerate(row_data):
                if col_idx in [4, 5, 6]:
                    try:
                        display_text = f"{float(col_data):,.2f}"
                    except (TypeError, ValueError):
                        display_text = str(col_data if col_data is not None else "")
                else:
                    display_text = str(col_data if col_data is not None else "")

                item = QTableWidgetItem(display_text)
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 7:
                    self._set_history_status_style(item, col_data)

                self.history_table.setItem(row_idx, col_idx, item)

    # ==========================================
    # تكامل أوامر الشراء
    # ==========================================
    def open_import_dialog(self):
        if len(self.cart) > 0:
            reply = QMessageBox.question(
                self,
                "تنبيه",
                "استيراد طلب شراء سيمسح السلة الحالية. هل تود الاستمرار؟",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        dialog = POSearchDialog(self.po_dao, self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_po_id:
            self.import_from_po(dialog.selected_po_id)

    def import_from_po(self, po_id):
        header, items = self.po_dao.get_po_with_items(po_id)
        if not header:
            QMessageBox.critical(self, "خطأ", "تعذر جلب تفاصيل أمر الشراء.")
            return

        self.cart.clear()
        self.selected_purchase_order_id = header[0]
        self.selected_purchase_order_number = header[1]
        self.import_mode_from_po = True

        self.title_lbl.setText(f"تسجيل فاتورة شراء (مرتبطة بالطلب {self.selected_purchase_order_number})")
        self.title_lbl.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #8E44AD; font-family: 'Times New Roman';"
        )

        self.manual_entry_group.hide()
        self.btn_import_po.hide()
        self.btn_cancel_import.show()

        sup_id = header[2]
        idx = self.supplier_combo.findData(sup_id)
        if idx < 0:
            QMessageBox.critical(self, "خطأ تكاملي", "المورد المرتبط بأمر الشراء غير موجود في قائمة الموردين.")
            self.reset_import_mode(force=True)
            return

        self.supplier_combo.setCurrentIndex(idx)
        self.supplier_combo.setEnabled(False)

        for item in items:
            remaining = item[7]
            if remaining > 0:
                self.cart.append({
                    "id": item[1],
                    "name": item[2],
                    "barcode": item[3],
                    "qty": remaining,
                    "cost": item[5] or 0.0,
                    "sell_price": 0.0,
                    "batch": "",
                    "expiry": "",
                    "po_item_id": item[0],
                    "requested_qty": item[4],
                    "received_qty": item[6],
                    "remaining_qty": remaining,
                    "total": remaining * (item[5] or 0.0)
                })

        self.update_table()

    def reset_import_mode(self, force=False):
        """تصفير الوضع مع دعم Force للإغلاق الهادئ بعد الحفظ."""
        if not force and len(self.cart) > 0:
            reply = QMessageBox.question(
                self,
                "تنبيه",
                "إلغاء الربط سيمسح السلة الحالية. هل تود الاستمرار؟",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        self.selected_purchase_order_id = None
        self.selected_purchase_order_number = None
        self.import_mode_from_po = False

        self.cart.clear()
        self.title_lbl.setText("تسجيل فاتورة شراء (مستقلة)")
        self.title_lbl.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )

        self.manual_entry_group.show()
        self.btn_import_po.show()
        self.btn_cancel_import.hide()

        self.supplier_combo.setEnabled(True)
        self.supplier_combo.setCurrentIndex(0)

        self.paid_amount_spin.setValue(0.0)
        self.update_table()

    # ==========================================
    # الإدخال اليدوي
    # ==========================================
    def populate_med_data(self):
        text = self.search_input.text().strip()
        if not text:
            return

        medicines = self.medicine_dao.search_medicine(text)
        if medicines:
            self.current_med_data = medicines[0]

            self.search_input.setText(str(self.current_med_data[2] or ""))
            self.cost_spin.setValue(float(self.current_med_data[6] or 0.0))
            self.sell_spin.setValue(float(self.current_med_data[7] or 0.0))
            self.batch_input.setFocus()
        else:
            self.current_med_data = None
            QMessageBox.warning(self, "تنبيه", "الدواء غير موجود.")
            self.search_input.clear()

    def add_item_to_cart(self):
        if self.import_mode_from_po:
            QMessageBox.warning(
                self,
                "ممنوع",
                "لا يمكن إضافة أصناف حرة أثناء استيراد أمر شراء. الرجاء تعديل البنود الموجودة في السلة فقط."
            )
            return

        if not self.current_med_data:
            return

        batch = self.batch_input.text().strip()
        if not batch:
            QMessageBox.warning(self, "تنبيه", "رقم التشغيلة (Batch) مطلوب إجبارياً.")
            return

        med_id = self.current_med_data[0]
        qty = self.qty_spin.value()
        cost = self.cost_spin.value()
        sell = self.sell_spin.value()

        if cost <= 0 or sell <= 0:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال أسعار صحيحة.")
            return

        self.cart.append({
            "id": med_id,
            "name": self.current_med_data[2],
            "batch": batch,
            "expiry": self.expiry_input.date().toString("yyyy-MM-dd"),
            "qty": qty,
            "cost": cost,
            "sell_price": sell,
            "total": qty * cost,
            "po_item_id": None,
            "remaining_qty": None
        })

        self.update_table()
        self._reset_manual_entry_fields()
        self.search_input.setFocus()

    def edit_imported_item(self, row_idx):
        if not self.import_mode_from_po:
            return

        item = self.cart[row_idx]

        dialog = QDialog(self)
        dialog.setWindowTitle(f"تحديث استلام: {item['name']}")
        dialog.resize(300, 300)
        layout = QVBoxLayout(dialog)

        lbl_rem = QLabel(f"المتبقي من الطلب: {item['remaining_qty']}")
        lbl_rem.setStyleSheet("color: red; font-weight: bold;")

        batch_edit = QLineEdit(item['batch'])
        batch_edit.setPlaceholderText("رقم التشغيلة (إلزامي)")

        expiry_edit = QDateEdit()
        expiry_edit.setCalendarPopup(True)
        if item['expiry']:
            expiry_edit.setDate(QDate.fromString(item['expiry'], "yyyy-MM-dd"))
        else:
            expiry_edit.setDate(QDate.currentDate().addYears(1))

        qty_spin = QSpinBox()
        qty_spin.setRange(1, item['remaining_qty'])
        qty_spin.setValue(item['qty'])

        cost_spin = QDoubleSpinBox()
        cost_spin.setDecimals(2)
        cost_spin.setRange(0, 1000000)
        cost_spin.setValue(item['cost'])

        sell_spin = QDoubleSpinBox()
        sell_spin.setDecimals(2)
        sell_spin.setRange(0, 1000000)
        sell_spin.setValue(item['sell_price'])

        btn_save = QPushButton("حفظ")
        btn_save.clicked.connect(dialog.accept)

        layout.addWidget(lbl_rem)
        layout.addWidget(QLabel("التشغيلة:"))
        layout.addWidget(batch_edit)
        layout.addWidget(QLabel("الصلاحية:"))
        layout.addWidget(expiry_edit)
        layout.addWidget(QLabel("الكمية المستلمة:"))
        layout.addWidget(qty_spin)
        layout.addWidget(QLabel("سعر الشراء:"))
        layout.addWidget(cost_spin)
        layout.addWidget(QLabel("سعر البيع:"))
        layout.addWidget(sell_spin)
        layout.addWidget(btn_save)

        if dialog.exec_() == QDialog.Accepted:
            new_batch = batch_edit.text().strip()
            if not new_batch:
                QMessageBox.warning(self, "خطأ", "يجب إدخال رقم التشغيلة.")
                return

            if cost_spin.value() <= 0 or sell_spin.value() <= 0:
                QMessageBox.warning(self, "خطأ", "يجب إدخال أسعار صحيحة.")
                return

            self.cart[row_idx]['batch'] = new_batch
            self.cart[row_idx]['expiry'] = expiry_edit.date().toString("yyyy-MM-dd")
            self.cart[row_idx]['qty'] = qty_spin.value()
            self.cart[row_idx]['cost'] = cost_spin.value()
            self.cart[row_idx]['sell_price'] = sell_spin.value()
            self.cart[row_idx]['total'] = qty_spin.value() * cost_spin.value()
            self.update_table()

    # ==========================================
    # التفاعل مع الجدول
    # ==========================================
    def handle_table_double_click(self, index):
        """استبعاد حقيقي وصريح للبند من الفاتورة الحالية."""
        row = index.row()
        if row < 0:
            return

        item_name = self.cart[row].get("name", "هذا الصنف")
        reply = QMessageBox.question(
            self,
            "تأكيد الاستبعاد",
            f"هل تريد استبعاد الصنف '{item_name}' من هذه الفاتورة الحالية؟",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            del self.cart[row]
            self.update_table()

    def update_table(self):
        self.table.setRowCount(0)
        total_bill = 0.0

        for row, item in enumerate(self.cart):
            self.table.insertRow(row)

            rem_str = str(item.get('remaining_qty', '-'))
            items_text = [
                str(item['id']),
                item['name'],
                item['batch'],
                item['expiry'],
                str(item['qty']),
                rem_str,
                f"{item['cost']:.2f}",
                f"{item['sell_price']:.2f}",
                f"{item['total']:.2f}",
                str(item.get('po_item_id', ''))
            ]

            for col, text in enumerate(items_text):
                tbl_item = QTableWidgetItem(text)
                tbl_item.setTextAlignment(Qt.AlignCenter)
                if col == 2 and not item['batch']:
                    tbl_item.setBackground(QColor("#FDEDEC"))
                self.table.setItem(row, col, tbl_item)

            if self.import_mode_from_po:
                btn_edit = QPushButton("📝 تعديل")
                btn_edit.clicked.connect(lambda _, r=row: self.edit_imported_item(r))
                self.table.setCellWidget(row, 10, btn_edit)

            total_bill += float(item['total'])

        if self.import_mode_from_po and len(self.cart) == 0:
            self.total_label.setText("تم استبعاد جميع البنود، لا يمكن اعتماد فاتورة فارغة.")
            self.total_label.setStyleSheet(
                "font-size: 18px; font-weight: bold; color: #E74C3C; font-family: 'Times New Roman';"
            )
        else:
            self.total_label.setText(f"الإجمالي: {total_bill:,.2f}")
            self.total_label.setStyleSheet(
                "font-size: 24px; font-weight: bold; color: #27AE60; font-family: 'Times New Roman';"
            )

        self._refresh_financial_summary()

    # ==========================================
    # الحفظ النهائي
    # ==========================================
    def save_invoice(self):
        if not self.cart:
            QMessageBox.warning(self, "تنبيه", "الفاتورة فارغة! لا يوجد أصناف للاعتماد.")
            return

        supplier_idx = self.supplier_combo.currentIndex()
        if supplier_idx <= 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار المورد أولاً.")
            return

        supplier_id = self.supplier_combo.itemData(supplier_idx)
        inv_num = self.inv_num_input.text().strip()

        if not inv_num:
            QMessageBox.warning(self, "تنبيه", "رقم فاتورة المورد إلزامي للتوثيق المحاسبي.")
            return

        if self.import_mode_from_po:
            for item in self.cart:
                if not item['batch'] or item['cost'] <= 0 or item['sell_price'] <= 0:
                    QMessageBox.critical(
                        self,
                        "بيانات ناقصة",
                        f"الرجاء استكمال بيانات التشغيلة والأسعار للصنف: {item['name']} بالضغط على زر (تعديل)."
                    )
                    return

        date = self.date_input.date().toString("yyyy-MM-dd")
        total = self._calculate_cart_total()
        paid_amount = round(float(self.paid_amount_spin.value()), 2)
        unpaid_amount = round(total - paid_amount, 2)

        if total <= 0:
            QMessageBox.warning(self, "تنبيه", "إجمالي الفاتورة غير صالح.")
            return

        if paid_amount < 0 or paid_amount > total:
            QMessageBox.warning(
                self,
                "تنبيه",
                "المبلغ المدفوع نقدًا غير صالح. يجب أن يكون بين صفر وإجمالي الفاتورة."
            )
            return

        current_shift_id = self._get_current_shift_id()
        if paid_amount > 0 and not current_shift_id:
            QMessageBox.critical(
                self,
                "رفض محاسبي",
                "تم تحديد دفعة نقدية لهذه الفاتورة، لكن لا توجد وردية مالية مفتوحة حالياً.\n"
                "إما افتح وردية أولاً، أو اجعل الفاتورة آجلة بالكامل."
            )
            return

        confirm_msg = (
            f"هل أنت متأكد من ترحيل هذه الفاتورة؟\n\n"
            f"إجمالي الفاتورة: {total:,.2f}\n"
            f"المدفوع نقداً الآن: {paid_amount:,.2f}\n"
            f"المتبقي ذمة على المورد: {unpaid_amount:,.2f}"
        )

        confirm = QMessageBox.question(
            self,
            "تأكيد الترحيل",
            confirm_msg,
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        success, msg = self.purchase_dao.add_purchase_invoice(
            supplier_id=supplier_id,
            invoice_number=inv_num,
            invoice_date=date,
            total_amount=total,
            items=self.cart,
            user_id=self.user_id,
            purchase_order_id=self.selected_purchase_order_id,
            paid_amount=paid_amount,
            shift_id=current_shift_id if paid_amount > 0 else None
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)

            self.inv_num_input.clear()
            self.date_input.setDate(QDate.currentDate())
            self.paid_amount_spin.setValue(0.0)
            self._reset_manual_entry_fields()
            self.reset_import_mode(force=True)
            self.load_purchase_history()
            self.inv_num_input.setFocus()
        else:
            QMessageBox.critical(self, "رفض العملية (حماية أمنية/محاسبية)", msg)