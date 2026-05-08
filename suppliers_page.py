"""
وظيفة الملف: واجهة إدارة الموردين والشركات الدائنة.
الطبقة: Presentation Layer

ملاحظة معمارية وأمنية:
- [UI RBAC]&#58; الواجهة تحجب الصفحة بالكامل عن غير المدراء.
- [Dumb Client]&#58; تمرر (requester_id) في كل عملية لتترك القرار الأمني والمحاسبي للنواة.
- [V25 Extended Supplier Profile]&#58;   تم توسيع بطاقة المورد لتشمل (البريد الإلكتروني، العنوان، الملاحظات، الحالة).
- [Soft Archive UI]&#58;   تم إضافة زر (تعطيل المورد) بدلاً من إجبار الحذف دائماً، حفاظاً على السجل التاريخي.
- [Search Upgrade]&#58;   البحث أصبح يشمل الاسم، الشركة، الهاتف، والبريد الإلكتروني.
- [Financial Safety]&#58;   لا يزال الرصيد المالي غير قابل للتعديل من الواجهة إطلاقاً.
- [Data Integrity]&#58;   الواجهة لا تعتمد على نفسها في منع التكرار؛ بل تعرض رسائل الرفض القادمة من النواة.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QLabel, QAbstractItemView, QTextEdit, QCheckBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from models.suppliers_dao import SuppliersDAO


# ==========================================
# النوافذ المنبثقة (Dialogs)
# ==========================================

class AddSupplierDialog(QDialog):
    def __init__(self, requester_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.dao = SuppliersDAO()

        self.setWindowTitle("إضافة مورد جديد")
        self.resize(560, 470)
        self.setStyleSheet("""
            QDialog {
                font-family: 'Times New Roman';
                font-size: 16px;
                background-color: #F5F6FA;
            }
            QLineEdit, QTextEdit {
                padding: 6px;
                border: 1px solid #BDC3C7;
                border-radius: 5px;
                font-size: 16px;
            }
            QLineEdit {
                min-height: 38px;
            }
            QTextEdit {
                min-height: 90px;
            }
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2C3E50;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(16)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم المورد / المندوب (إلزامي)")

        self.company_input = QLineEdit()
        self.company_input.setPlaceholderText("اسم الشركة")

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف")

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("البريد الإلكتروني")

        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("العنوان")

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("ملاحظات عامة على المورد أو آلية التعامل أو بيانات إضافية...")

        form_layout.addRow("الاسم:", self.name_input)
        form_layout.addRow("الشركة:", self.company_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("الإيميل:", self.email_input)
        form_layout.addRow("العنوان:", self.address_input)
        form_layout.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form_layout)

        info_lbl = QLabel(
            "* الرصيد الافتتاحي يتم تصفيره تلقائياً، والمديونية تتولد فقط من فواتير المشتريات.\n"
            "* التفرد المنطقي يعتمد على هوية المورد، وليس على الهاتف وحده."
        )
        info_lbl.setStyleSheet("color: #7F8C8D; font-size: 13px; font-style: italic; font-weight: normal;")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ واعتماد")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; padding: 8px 14px;"
        )
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.save_supplier)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def save_supplier(self):
        name = self.name_input.text().strip()
        company = self.company_input.text().strip()
        phone = self.phone_input.text().strip()
        email = self.email_input.text().strip()
        address = self.address_input.text().strip()
        notes = self.notes_input.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم المورد بشكل إلزامي.")
            return

        success, msg = self.dao.add_supplier(
            requester_id=self.requester_id,
            name=name,
            phone=phone,
            company=company,
            email=email,
            address=address,
            notes=notes
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


class EditSupplierDialog(QDialog):
    def __init__(self, requester_id, supplier_id, parent=None):
        super().__init__(parent)
        self.requester_id = requester_id
        self.supplier_id = supplier_id
        self.dao = SuppliersDAO()
        self.supplier_data = None

        self.setWindowTitle("تعديل بيانات مورد")
        self.resize(560, 470)
        self.setStyleSheet("""
            QDialog {
                font-family: 'Times New Roman';
                font-size: 16px;
                background-color: #F5F6FA;
            }
            QLineEdit, QTextEdit {
                padding: 6px;
                border: 1px solid #BDC3C7;
                border-radius: 5px;
                font-size: 16px;
            }
            QLineEdit {
                min-height: 38px;
            }
            QTextEdit {
                min-height: 90px;
            }
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #2C3E50;
            }
        """)
        self.setup_ui()
        self.load_supplier_data()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(16)

        self.name_input = QLineEdit()
        self.company_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.email_input = QLineEdit()
        self.address_input = QLineEdit()
        self.notes_input = QTextEdit()

        self.name_input.setPlaceholderText("اسم المورد / المندوب (إلزامي)")
        self.company_input.setPlaceholderText("اسم الشركة")
        self.phone_input.setPlaceholderText("رقم الهاتف")
        self.email_input.setPlaceholderText("البريد الإلكتروني")
        self.address_input.setPlaceholderText("العنوان")
        self.notes_input.setPlaceholderText("ملاحظات عامة على المورد أو آلية التعامل...")

        form_layout.addRow("الاسم:", self.name_input)
        form_layout.addRow("الشركة:", self.company_input)
        form_layout.addRow("الهاتف:", self.phone_input)
        form_layout.addRow("الإيميل:", self.email_input)
        form_layout.addRow("العنوان:", self.address_input)
        form_layout.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form_layout)

        self.balance_lbl = QLabel("الرصيد الدائن الحالي: 0.00")
        self.balance_lbl.setStyleSheet("color: #C0392B; font-size: 14px;")
        layout.addWidget(self.balance_lbl)

        info_lbl = QLabel("* تعديل الرصيد المالي يتم فقط عبر المشتريات والتسويات المحاسبية، وليس من هذه الواجهة.")
        info_lbl.setStyleSheet("color: #7F8C8D; font-size: 13px; font-style: italic; font-weight: normal;")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("حفظ التعديلات")
        self.buttons.button(QDialogButtonBox.Save).setStyleSheet(
            "background-color: #F39C12; color: white; font-weight: bold; padding: 8px 14px;"
        )
        self.buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")

        self.buttons.accepted.connect(self.update_supplier)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

    def load_supplier_data(self):
        row = self.dao.get_supplier_by_id(self.supplier_id, include_inactive=True)
        if not row:
            QMessageBox.critical(self, "خطأ", "تعذر تحميل بيانات المورد.")
            self.reject()
            return

        self.supplier_data = row

        # ترتيب الحقول القادم من DAO:
        # id, name, phone, company_name, balance, email, address, notes, is_active, created_at, updated_at
        self.name_input.setText("" if row[1] is None else str(row[1]))
        self.phone_input.setText("" if row[2] is None else str(row[2]))
        self.company_input.setText("" if row[3] is None else str(row[3]))
        self.email_input.setText("" if row[5] is None else str(row[5]))
        self.address_input.setText("" if row[6] is None else str(row[6]))
        self.notes_input.setPlainText("" if row[7] is None else str(row[7]))
        self.balance_lbl.setText(f"الرصيد الدائن الحالي: {float(row[4] or 0.0):,.2f}")

    def update_supplier(self):
        name = self.name_input.text().strip()
        company = self.company_input.text().strip()
        phone = self.phone_input.text().strip()
        email = self.email_input.text().strip()
        address = self.address_input.text().strip()
        notes = self.notes_input.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "تنبيه", "يجب إدخال اسم المورد بشكل إلزامي.")
            return

        success, msg = self.dao.update_supplier(
            requester_id=self.requester_id,
            supplier_id=self.supplier_id,
            name=name,
            phone=phone,
            company=company,
            email=email,
            address=address,
            notes=notes
        )

        if success:
            QMessageBox.information(self, "نجاح", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "رفض العملية", msg)


# ==========================================
# الصفحة الرئيسية للموردين
# ==========================================

class SuppliersPage(QWidget):
    def __init__(self, session_data=None):
        super().__init__()
        self.session = session_data if session_data is not None else {}
        self.requester_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")
        self.dao = SuppliersDAO()

        if self.user_role != 'admin':
            self.init_access_denied_ui()
        else:
            self.init_ui()
            self.load_data()

    # ==========================================
    # الحماية البصرية
    # ==========================================
    def init_access_denied_ui(self):
        layout = QVBoxLayout()
        warning_lbl = QLabel("⛔ صلاحيات غير كافية.\nهذه الصفحة مخصصة لمدير النظام فقط لتأمين الحسابات الدائنة والموردين.")
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

        title = QLabel("إدارة الموردين والشركات")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; margin-bottom: 10px; font-family: 'Times New Roman';"
        )
        layout.addWidget(title)

        # ------------------------------
        # شريط الفلاتر والبحث
        # ------------------------------
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث باسم المورد، الشركة، الهاتف أو الإيميل...")
        self.search_input.setFixedHeight(46)
        self.search_input.setStyleSheet(
            "font-size: 17px; padding: 0 10px; border-radius: 5px; border: 1px solid #ccc; font-family: 'Times New Roman';"
        )
        self.search_input.textChanged.connect(self.search_data)

        self.chk_show_inactive = QCheckBox("عرض الموردين المعطلين أيضاً")
        self.chk_show_inactive.setStyleSheet("font-size: 15px; font-family: 'Times New Roman';")
        self.chk_show_inactive.stateChanged.connect(self.load_data)

        filter_bar.addWidget(self.search_input, stretch=4)
        filter_bar.addWidget(self.chk_show_inactive, stretch=1)

        layout.addLayout(filter_bar)

        # ------------------------------
        # الأزرار
        # ------------------------------
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.btn_add = QPushButton("إضافة مورد")
        self.btn_add.setFixedHeight(48)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; font-size: 18px; "
            "font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';"
        )

        self.btn_edit = QPushButton("تعديل البيانات")
        self.btn_edit.setFixedHeight(48)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self.open_edit_dialog)
        self.btn_edit.setStyleSheet(
            "background-color: #F39C12; color: white; padding: 0 20px; font-size: 18px; "
            "font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';"
        )

        self.btn_archive = QPushButton("تعطيل المورد")
        self.btn_archive.setFixedHeight(48)
        self.btn_archive.setCursor(Qt.PointingHandCursor)
        self.btn_archive.clicked.connect(self.archive_selected)
        self.btn_archive.setStyleSheet(
            "background-color: #8E44AD; color: white; padding: 0 20px; font-size: 18px; "
            "font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';"
        )

        self.btn_refresh = QPushButton("تحديث")
        self.btn_refresh.setFixedHeight(48)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet(
            "font-size: 18px; padding: 0 15px; font-family: 'Times New Roman';"
        )

        self.btn_delete = QPushButton("حذف إداري")
        self.btn_delete.setFixedHeight(48)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 0 20px; font-size: 18px; "
            "font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';"
        )

        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_edit)
        top_bar.addWidget(self.btn_archive)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_delete)
        top_bar.addStretch()

        layout.addLayout(top_bar)

        # ------------------------------
        # شريط المعلومات
        # ------------------------------
        self.summary_label = QLabel("—")
        self.summary_label.setStyleSheet(
            "font-size: 14px; color: #566573; font-family: 'Times New Roman'; padding: 2px 4px;"
        )
        layout.addWidget(self.summary_label)

        # ------------------------------
        # الجدول
        # ------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "ID", "الاسم", "الشركة", "الهاتف", "الإيميل",
            "العنوان", "ملاحظات", "الرصيد الدائن", "الحالة"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                font-size: 16px;
                font-family: 'Times New Roman';
                alternate-background-color: #FAFAFA;
                background-color: white;
            }
            QHeaderView::section {
                font-size: 16px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
        """)

        layout.addWidget(self.table)
        self.setLayout(layout)

    # ==========================================
    # تحميل البيانات
    # ==========================================
    def _active_only_filter(self):
        return not self.chk_show_inactive.isChecked()

    def load_data(self):
        suppliers = self.dao.get_all_suppliers(
            active_only=self._active_only_filter(),
            include_extended=True
        )
        self.fill_table(suppliers)

    def search_data(self):
        text = self.search_input.text().strip()
        if text:
            suppliers = self.dao.search_supplier(
                text=text,
                active_only=self._active_only_filter(),
                include_extended=True
            )
        else:
            suppliers = self.dao.get_all_suppliers(
                active_only=self._active_only_filter(),
                include_extended=True
            )

        self.fill_table(suppliers)

    # ==========================================
    # العرض داخل الجدول
    # ==========================================
    def fill_table(self, data):
        self.table.setRowCount(0)

        active_count = 0
        inactive_count = 0

        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            # ترتيب الحقول القادم من DAO:
            # id, name, phone, company_name, balance, email, address, notes, is_active, created_at, updated_at
            supplier_id = row_data[0]
            name = row_data[1]
            phone = row_data[2]
            company_name = row_data[3]
            balance = float(row_data[4] or 0.0)
            email = row_data[5]
            address = row_data[6]
            notes = row_data[7]
            is_active = int(row_data[8] or 0)

            if is_active == 1:
                active_count += 1
            else:
                inactive_count += 1

            display_row = [
                str(supplier_id),
                name or "",
                company_name or "",
                phone or "",
                email or "",
                address or "",
                notes or "",
                f"{balance:,.2f}",
                "نشط" if is_active == 1 else "معطل"
            ]

            row_bg = QColor("#F4F6F7") if is_active == 0 else None

            for col_idx, col_data in enumerate(display_row):
                item = QTableWidgetItem(col_data)
                item.setTextAlignment(Qt.AlignCenter)

                if row_bg:
                    item.setBackground(row_bg)

                # تلوين الرصيد الدائن
                if col_idx == 7 and balance > 0.001:
                    item.setForeground(QColor("#C0392B"))

                # تلوين الحالة
                if col_idx == 8:
                    if is_active == 1:
                        item.setForeground(QColor("#27AE60"))
                    else:
                        item.setForeground(QColor("#7F8C8D"))

                # Tooltip للملاحظات والعنوان إن كانت طويلة
                if col_idx in (5, 6):
                    item.setToolTip(col_data)

                self.table.setItem(row_idx, col_idx, item)

        self.summary_label.setText(
            f"عدد الموردين الظاهرين: {len(data)}  |  النشطون: {active_count}  |  المعطلون: {inactive_count}"
        )

    # ==========================================
    # Helpers
    # ==========================================
    def _get_selected_supplier_id(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return None
        try:
            return int(self.table.item(selected_row, 0).text())
        except Exception:
            return None

    def _get_selected_supplier_name(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return ""
        item = self.table.item(selected_row, 1)
        return item.text() if item else ""

    def _get_selected_supplier_status(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return None
        item = self.table.item(selected_row, 8)
        return item.text() if item else None

    # ==========================================
    # العمليات
    # ==========================================
    def open_add_dialog(self):
        if not self.requester_id:
            return

        dialog = AddSupplierDialog(self.requester_id, self)
        if dialog.exec_():
            self.load_data()

    def open_edit_dialog(self):
        supplier_id = self._get_selected_supplier_id()
        if not supplier_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مورد لتعديل بياناته.")
            return

        dialog = EditSupplierDialog(self.requester_id, supplier_id, self)
        if dialog.exec_():
            self.load_data()

    def archive_selected(self):
        if not self.requester_id:
            return

        supplier_id = self._get_selected_supplier_id()
        if not supplier_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مورد لتعطيله.")
            return

        status_text = self._get_selected_supplier_status()
        if status_text == "معطل":
            QMessageBox.information(self, "معلومة", "هذا المورد معطل مسبقاً.")
            return

        name = self._get_selected_supplier_name()

        confirm = QMessageBox.question(
            self,
            "تأكيد تعطيل المورد",
            f"هل أنت متأكد من تعطيل المورد ({name})؟\n"
            "سيبقى السجل محفوظاً تاريخياً، لكنه لن يظهر ضمن الموردين النشطين الافتراضيين.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.archive_supplier(
                requester_id=self.requester_id,
                supplier_id=supplier_id,
                reason="Manual archive from UI"
            )
            if success:
                self.load_data()
                QMessageBox.information(self, "تم التعطيل", msg)
            else:
                QMessageBox.critical(self, "رفض العملية", msg)

    def delete_selected(self):
        if not self.requester_id:
            return

        supplier_id = self._get_selected_supplier_id()
        if not supplier_id:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد مورد لحذفه.")
            return

        name = self._get_selected_supplier_name()

        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف الجذري",
            f"هل أنت متأكد من حذف المورد ({name}) نهائياً؟\n"
            "ملاحظة: سيتم رفض العملية من النظام إذا كان للمورد رصيد قائم أو فواتير أو أوامر شراء أو ارتباطات مخزنية.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_supplier(self.requester_id, supplier_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم الحذف", msg)
            else:
                QMessageBox.critical(self, "رفض العملية (حماية محاسبية/أمنية)", msg)