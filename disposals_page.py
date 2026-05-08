"""
وظيفة الملف: واجهة تسوية وإتلاف الأدوية المنتهية (Disposals Page).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- واجهة (Dumb Client) لا تقوم بأي حسابات نهائية.
- حصر مبدئي لسبب الإتلاف في (expired) فقط.
- حماية بصرية (UI RBAC): تمنع عرض أي مكون لغير الإداريين (admin).
- [V13 Patch - Hazardous Integration]:
    1. تمييز بصري (☣️) للمواد الخطرة في جميع الجداول.
    2. اعتراض ذكي قبل الاعتماد: إذا احتوت السلة على مواد خطرة، تُفتح نافذة خاصة لإجبار المستخدم على إدخال "آلية التخلص" الإلزامية لكل صنف خطر، وتكوين `hazard_data` بدقة لتمريرها للنواة.
- [Dashboard Integration Update]: دعم التوجيه الخارجي (apply_external_filter) مع تنظيف السلة العميق والحماية من انكسار الـ RBAC عند القفز من لوحة التحكم.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
                             QGroupBox, QSpinBox, QMessageBox, QSplitter, QAbstractItemView,
                             QDialog, QFormLayout, QLineEdit, QScrollArea)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from models.disposals_dao import DisposalsDAO

# ==========================================
# النوافذ المنبثقة (Dialogs) لـ V13
# ==========================================
class HazardousDisposalDialog(QDialog):
    """
    نافذة ديناميكية تظهر فقط إذا احتوت سلة الإتلاف على مواد خطرة.
    تُجبر المستخدم على إدخال آلية التخلص لكل مادة خطرة على حدة.
    """
    def __init__(self, hazardous_items, parent=None):
        super().__init__(parent)
        self.hazardous_items = hazardous_items # list of dicts: {batch_id, name, hazard_class, qty}
        self.hazard_data = {}
        self.inputs_map = {} # لتتبع حقول الإدخال لكل batch_id

        self.setWindowTitle("سجل إتلاف المواد الخطرة (إلزامي)")
        self.resize(600, 500)
        self.setStyleSheet("QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #FEF9E7; }")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        lbl = QLabel("⚠️ السلة تحتوي على مواد خطرة ☣️.\nيجب استكمال السجل البيئي لكل مادة قبل اعتماد الإتلاف:")
        lbl.setStyleSheet("color: #D35400; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(lbl)

        # منطقة قابلة للتمرير في حال وجود أكثر من مادة خطرة
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        for item in self.hazardous_items:
            batch_id = str(item['batch_id'])

            grp = QGroupBox(f"صنف: {item['name']} | فئة الخطورة: {item['hazard_class']} | الكمية: {item['qty']}")
            grp.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #F39C12; margin-top: 10px; padding-top: 15px; }")

            form = QFormLayout()

            method_input = QLineEdit()
            method_input.setPlaceholderText("آلية الإتلاف (مثال: حرق، تسليم لشركة مختصة) *")
            method_input.setStyleSheet("border: 1px solid #D35400; padding: 5px;")

            receiver_input = QLineEdit()
            receiver_input.setPlaceholderText("الجهة المستلمة (اختياري)")
            receiver_input.setStyleSheet("border: 1px solid #BDC3C7; padding: 5px;")

            manifest_input = QLineEdit()
            manifest_input.setPlaceholderText("رقم محضر الإتلاف/البيان (اختياري)")
            manifest_input.setStyleSheet("border: 1px solid #BDC3C7; padding: 5px;")

            notes_input = QLineEdit()
            notes_input.setPlaceholderText("ملاحظات إضافية (اختياري)")
            notes_input.setStyleSheet("border: 1px solid #BDC3C7; padding: 5px;")

            form.addRow("آلية التخلص *:", method_input)
            form.addRow("الجهة المستلمة:", receiver_input)
            form.addRow("رقم البيان:", manifest_input)
            form.addRow("ملاحظات:", notes_input)

            grp.setLayout(form)
            scroll_layout.addWidget(grp)

            self.inputs_map[batch_id] = {
                'method': method_input,
                'receiver': receiver_input,
                'manifest': manifest_input,
                'notes': notes_input
            }

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton(" ✅ اعتماد ومتابعة الإتلاف")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet("background-color: #D35400; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_save.clicked.connect(self.validate_and_accept)

        self.btn_cancel = QPushButton(" ❌ إلغاء العملية")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet("background-color: #7F8C8D; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def validate_and_accept(self):
        self.hazard_data = {}
        for batch_id, inputs in self.inputs_map.items():
            method = inputs['method'].text().strip()
            if not method:
                QMessageBox.warning(self, "تنبيه بيئي", "حقل 'آلية التخلص' إلزامي لجميع المواد الخطرة.")
                return

            self.hazard_data[batch_id] = {
                'disposal_method': method,
                'receiver_entity': inputs['receiver'].text().strip(),
                'manifest_number': inputs['manifest'].text().strip(),
                'notes': inputs['notes'].text().strip()
            }

        self.accept()

    def get_hazard_data(self):
        return self.hazard_data


# ==========================================
# الواجهة الرئيسية لصفحة الإتلاف
# ==========================================
class DisposalsPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

        self.dao = DisposalsDAO()

        # تخزين بيانات الخطورة للرزم المتاحة للرجوع إليها عند الإضافة للسلة
        self.available_batches_data = {}

        # UI RBAC: حجب الصفحة بالكامل عن غير المدراء
        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.init_ui()
            self.load_initial_data()

    def init_access_denied_ui(self):
        layout = QVBoxLayout()
        warning_lbl = QLabel(
            "⛔ صلاحيات غير كافية.\nهذه الصفحة مخصصة لمدير النظام فقط (إدارة الإتلاف والتسويات الجردية).")
        warning_lbl.setAlignment(Qt.AlignCenter)
        warning_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';")
        layout.addWidget(warning_lbl)
        self.setLayout(layout)

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title = QLabel("إدارة إتلاف الأدوية وتسوية المخزون (الرزم المنتهية)")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        main_layout.addWidget(title)

        main_splitter = QSplitter(Qt.Vertical)

        # ==========================================
        # القسم الأول: الرزم المتاحة للإتلاف (Expired)
        # ==========================================
        grp_available = QGroupBox("1. الرزم المنتهية المتاحة للإتلاف")
        grp_available.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px; font-weight: bold;")
        lay_available = QVBoxLayout(grp_available)

        self.tbl_available = self.create_table([
            "ID التشغيلة", "الباركود", "اسم الدواء", "رقم التشغيلة",
            "تاريخ الانتهاء", "المتاح حالياً", "تكلفة الوحدة", "الحالة"
        ])
        lay_available.addWidget(self.tbl_available)

        # شريط أدوات الإضافة للسلة
        add_bar = QHBoxLayout()
        self.spin_dispose_qty = QSpinBox()
        self.spin_dispose_qty.setMinimum(1)
        self.spin_dispose_qty.setMaximum(10000)
        self.spin_dispose_qty.setStyleSheet("height: 35px; font-size: 16px;")

        btn_add_to_cart = QPushButton(" إضافة إلى سلة الإتلاف ⬇")
        btn_add_to_cart.setCursor(Qt.PointingHandCursor)
        btn_add_to_cart.setStyleSheet("background-color: #3498DB; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_add_to_cart.clicked.connect(self.add_to_cart)

        add_bar.addWidget(QLabel("الكمية المراد إتلافها:"))
        add_bar.addWidget(self.spin_dispose_qty)
        add_bar.addWidget(btn_add_to_cart)
        add_bar.addStretch()
        lay_available.addLayout(add_bar)

        main_splitter.addWidget(grp_available)

        # ==========================================
        # القسم الثاني: سلة الإتلاف
        # ==========================================
        grp_cart = QGroupBox("2. سلة الإتلاف (قيد التجهيز)")
        grp_cart.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px; font-weight: bold;")
        lay_cart = QVBoxLayout(grp_cart)

        # [V13 Patch]: إضافة عمود مخفي لتخزين حالة الخطورة والفئة
        self.tbl_cart = self.create_table(["ID التشغيلة", "اسم الدواء", "رقم التشغيلة", "الكمية للإتلاف", "is_haz", "haz_class"])
        self.tbl_cart.hideColumn(4)
        self.tbl_cart.hideColumn(5)
        lay_cart.addWidget(self.tbl_cart)

        cart_bar = QHBoxLayout()
        btn_remove_cart = QPushButton(" ❌ حذف من السلة")
        btn_remove_cart.setCursor(Qt.PointingHandCursor)
        btn_remove_cart.setStyleSheet("background-color: #E74C3C; color: white; padding: 8px 20px; border-radius: 5px;")
        btn_remove_cart.clicked.connect(self.remove_from_cart)

        btn_submit = QPushButton(" ⚠ اعتماد الإتلاف وتسوية المخزون نهائياً")
        btn_submit.setCursor(Qt.PointingHandCursor)
        btn_submit.setStyleSheet("background-color: #C0392B; color: white; padding: 8px 30px; border-radius: 5px;")
        btn_submit.clicked.connect(self.submit_disposal)

        cart_bar.addWidget(btn_remove_cart)
        cart_bar.addStretch()
        cart_bar.addWidget(btn_submit)
        lay_cart.addLayout(cart_bar)

        main_splitter.addWidget(grp_cart)

        # ==========================================
        # القسم الثالث: السجل التاريخي والتفاصيل
        # ==========================================
        grp_history = QGroupBox("3. السجل التاريخي للإتلافات")
        grp_history.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px; font-weight: bold;")
        lay_history = QVBoxLayout(grp_history)

        history_splitter = QSplitter(Qt.Horizontal)

        self.tbl_history = self.create_table(["رقم العملية", "بواسطة", "التاريخ", "التكلفة المهدرة", "السبب"])
        self.tbl_history.itemSelectionChanged.connect(self.on_history_select)

        self.tbl_details = self.create_table(["الباركود", "اسم الدواء", "التشغيلة", "الكمية", "التكلفة الإجمالية"])

        history_splitter.addWidget(self.tbl_history)
        history_splitter.addWidget(self.tbl_details)
        history_splitter.setSizes([400, 400])

        lay_history.addWidget(history_splitter)
        main_splitter.addWidget(grp_history)

        main_splitter.setSizes([300, 200, 300])
        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)

    # ==========================================
    # API for Main Controller (Dashboard Routing)
    # ==========================================
    def apply_external_filter(self, filter_type):
        """
        تُستدعى من خارج الكلاس لضبط الواجهة برمجياً عند الانتقال من لوحة التحكم.
        ملاحظة: هذه الصفحة تجلب حصراً الأدوية المنتهية (expired)، لذا التوجيه يهدف
        أساساً إلى تنظيف الحالة وتحديث القائمة لضمان دقة العمليات.
        """
        # [RBAC Guard]: حماية ضد الانكسار إذا تم استدعاء الواجهة لمستخدم غير إداري
        if self.user_role != 'admin':
            return

        # تنظيف جذري لحالة السلة والتفاصيل لضمان بداية نظيفة
        self.clear_cart_and_state()

        if filter_type == "expired":
            self.load_initial_data()
        else:
            self.load_initial_data()

    def clear_cart_and_state(self):
        """تفريغ سلة الإتلاف والمدخلات السابقة وتفاصيل السجل"""
        if hasattr(self, 'tbl_cart'):
            self.tbl_cart.setRowCount(0)
            self.tbl_cart.clearSelection()

        if hasattr(self, 'spin_dispose_qty'):
            self.spin_dispose_qty.setValue(1)

        if hasattr(self, 'tbl_details'):
            self.tbl_details.setRowCount(0)

        if hasattr(self, 'tbl_history'):
            self.tbl_history.clearSelection()
        if hasattr(self, 'tbl_available'):
            self.tbl_available.clearSelection()

    # ==========================================
    # الدوال المساعدة للواجهة
    # ==========================================
    def create_table(self, headers):
        tbl = QTableWidget()
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        tbl.setStyleSheet("font-weight: normal; font-size: 15px;")
        return tbl

    def load_initial_data(self):
        self.load_available_batches()
        self.load_history()

    def load_available_batches(self):
        # هذه الواجهة مصممة لجلب الرزم المنتهية (expired) بشكل افتراضي
        batches = self.dao.get_disposable_batches(reason='expired')
        self.tbl_available.setRowCount(0)
        self.available_batches_data.clear()

        for row_idx, b in enumerate(batches):
            self.tbl_available.insertRow(row_idx)

            batch_id_str = str(b['batch_id'])
            self.available_batches_data[batch_id_str] = {
                'is_hazardous': b.get('is_hazardous', 0),
                'hazard_class': b.get('hazard_class', '')
            }

            med_name = b['medicine_name']
            if b.get('is_hazardous') == 1:
                med_name += " ☣️"

            items = [
                batch_id_str, b['barcode'], med_name,
                b['batch_number'], b['expiry_date'], str(b['available_qty']),
                f"{b['unit_cost']:.2f}", b['status']
            ]

            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if b.get('is_hazardous') == 1:
                    item.setForeground(QColor("#D35400"))
                    item.setFont(QFont("Times New Roman", 15, QFont.Bold))
                self.tbl_available.setItem(row_idx, col_idx, item)

    def add_to_cart(self):
        selected_row = self.tbl_available.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "يرجى تحديد تشغيلة من الجدول العلوي أولاً.")
            return

        batch_id = self.tbl_available.item(selected_row, 0).text()
        med_name = self.tbl_available.item(selected_row, 2).text()
        batch_num = self.tbl_available.item(selected_row, 3).text()
        available_qty = int(self.tbl_available.item(selected_row, 5).text())
        qty_to_dispose = self.spin_dispose_qty.value()

        if qty_to_dispose > available_qty:
            QMessageBox.warning(self, "تنبيه",
                                f"الكمية المطلوبة للإتلاف ({qty_to_dispose}) تتجاوز المتاح في التشغيلة ({available_qty}).")
            return

        for row in range(self.tbl_cart.rowCount()):
            if self.tbl_cart.item(row, 0).text() == batch_id:
                QMessageBox.warning(self, "تنبيه",
                                    "هذه التشغيلة موجودة بالفعل في السلة. احذفها وأضفها بالكمية الجديدة إذا أردت التعديل.")
                return

        row_idx = self.tbl_cart.rowCount()
        self.tbl_cart.insertRow(row_idx)

        haz_data = self.available_batches_data.get(batch_id, {'is_hazardous': 0, 'hazard_class': ''})

        items = [batch_id, med_name, batch_num, str(qty_to_dispose), str(haz_data['is_hazardous']), haz_data['hazard_class']]

        for col_idx, val in enumerate(items):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            if haz_data['is_hazardous'] == 1:
                item.setForeground(QColor("#D35400"))
                item.setFont(QFont("Times New Roman", 15, QFont.Bold))
            self.tbl_cart.setItem(row_idx, col_idx, item)

        self.spin_dispose_qty.setValue(1)

    def remove_from_cart(self):
        selected_row = self.tbl_cart.currentRow()
        if selected_row >= 0:
            self.tbl_cart.removeRow(selected_row)

    def submit_disposal(self):
        row_count = self.tbl_cart.rowCount()
        if row_count == 0:
            QMessageBox.warning(self, "تنبيه", "سلة الإتلاف فارغة.")
            return

        items_payload = []
        hazardous_items_for_dialog = []

        for row in range(row_count):
            batch_id_str = self.tbl_cart.item(row, 0).text()
            batch_id = int(batch_id_str)
            med_name = self.tbl_cart.item(row, 1).text().replace(" ☣️", "")
            qty = int(self.tbl_cart.item(row, 3).text())
            is_haz = int(self.tbl_cart.item(row, 4).text())
            haz_class = self.tbl_cart.item(row, 5).text()

            items_payload.append({"batch_id": batch_id, "quantity": qty})

            if is_haz == 1:
                hazardous_items_for_dialog.append({
                    'batch_id': batch_id_str,
                    'name': med_name,
                    'hazard_class': haz_class,
                    'qty': qty
                })

        hazard_data_dict = {}

        if hazardous_items_for_dialog:
            dialog = HazardousDisposalDialog(hazardous_items_for_dialog, self)
            if dialog.exec_() == QDialog.Accepted:
                hazard_data_dict = dialog.get_hazard_data()
            else:
                QMessageBox.warning(self, "إلغاء العملية", "تم إلغاء عملية الإتلاف لعدم استكمال بيانات السجل البيئي الإلزامية للمواد الخطرة.")
                return
        else:
            confirm = QMessageBox.question(self, "تأكيد الإتلاف",
                                           "هل أنت متأكد من اعتماد إتلاف هذه الأدوية؟\nسيتولد عن ذلك قيد مالي بالخسارة ولا يمكن التراجع عنه.",
                                           QMessageBox.Yes | QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return

        success, result = self.dao.process_disposal(
            user_id=self.user_id,
            items_to_dispose=items_payload,
            reason='expired',
            notes='تمت التسوية عبر واجهة النظام',
            hazard_data=hazard_data_dict
        )

        if success:
            QMessageBox.information(self, "تم الاعتماد", result['message'])
            self.tbl_cart.setRowCount(0)
            self.load_initial_data()
        else:
            QMessageBox.critical(self, "رفض العملية", result)

    def load_history(self):
        disposals = self.dao.get_all_disposals()
        self.tbl_history.setRowCount(0)
        for row_idx, d in enumerate(disposals):
            self.tbl_history.insertRow(row_idx)
            items = [str(d['id']), d['username'], d['disposal_date'], f"{d['total_cost']:.2f}", d['reason']]
            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                self.tbl_history.setItem(row_idx, col_idx, item)

    def on_history_select(self):
        selected_row = self.tbl_history.currentRow()
        if selected_row < 0: return

        disposal_id = int(self.tbl_history.item(selected_row, 0).text())
        details = self.dao.get_disposal_details(disposal_id)

        self.tbl_details.setRowCount(0)
        for row_idx, det in enumerate(details):
            self.tbl_details.insertRow(row_idx)

            med_name = det['medicine_name']
            if det.get('has_hazardous_log'):
                med_name += " ☣️"

            items = [det['barcode'], med_name, det['batch_number'],
                     str(det['quantity']), f"{det['total_item_cost']:.2f}"]

            for col_idx, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if det.get('has_hazardous_log'):
                    item.setForeground(QColor("#D35400"))
                self.tbl_details.setItem(row_idx, col_idx, item)