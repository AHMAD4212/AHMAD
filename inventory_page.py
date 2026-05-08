"""
وظيفة الملف: واجهة إدارة المخزون والأدوية.
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- تم استكمال مسار الـ CRUD بربط واجهة (التعديل) الجديدة.
- تم تطبيق (UI RBAC) بإخفاء أزرار (الإضافة، التعديل، التصفير، الحذف) لغير المدراء.
- [V9 Update]: تم توسيع الجدول والفهارس لدعم عرض (الشكل الصيدلاني) و (التركيز) لتأسيس محرك البدائل الدوائية.
- [V11 & V13 Update]: إضافة الوسم البصري (Visual Badging) للأدوية الرقابية (💊) والمواد الخطرة (☣️) لتعزيز الوعي التشغيلي أثناء الجرد، مع الإبقاء على 10 أعمدة برمجياً لعدم كسر هيكل الجدول.
- [V14 Update]: إضافة تمييز بصري للأدوية الناقصة (Low Stock) مع زر "عرض النواقص فقط".
- [Dashboard Integration Update]: إضافة دعم الفلترة الخارجية عبر (apply_external_filter) لدعم أزرار لوحة التحكم (Nawakes & Expired) مع مسح حالة البحث.
"""

from datetime import datetime, timedelta

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QMessageBox, QLabel
)

from models.medicine_dao import MedicineDAO
from ui.add_medicine_dialog import AddMedicineDialog, EditMedicineDialog


class InventoryPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

        self.dao = MedicineDAO()

        # نظام إدارة حالة الفلترة: None, 'low_stock', 'expired'
        self.active_filter = None
        self.low_stock_ids = set()

        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header_layout = QHBoxLayout()

        title = QLabel("إدارة المخزون والأدوية")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )

        legend = QLabel("🔴 منتهي الصلاحية   🟠 وشيك الانتهاء   |   🚨 ناقص مخزون   ☣️ مادة خطرة   💊 دواء رقابي")
        legend.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #555; font-family: 'Times New Roman';"
        )

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(legend)
        layout.addLayout(header_layout)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("بحث بالاسم، الباركود، أو المادة الفعالة...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet(
            "font-size: 18px; padding: 0 10px; border: 1px solid #ccc; "
            "border-radius: 5px; font-family: 'Times New Roman';"
        )
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input)

        # زر فلترة النواقص
        self.btn_low_stock_filter = QPushButton("عرض النواقص فقط")
        self.btn_low_stock_filter.setCheckable(True)
        self.btn_low_stock_filter.setFixedHeight(50)
        self.btn_low_stock_filter.setCursor(Qt.PointingHandCursor)
        self.btn_low_stock_filter.clicked.connect(lambda: self.toggle_filter('low_stock'))
        self.btn_low_stock_filter.setStyleSheet("""
            QPushButton {
                background-color: #C0392B;
                color: white;
                padding: 0 20px;
                font-size: 18px;
                border-radius: 5px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
            QPushButton:checked {
                background-color: #922B21;
            }
        """)
        top_bar.addWidget(self.btn_low_stock_filter)

        # زر فلترة المنتهية الصلاحية
        self.btn_expired_filter = QPushButton("عرض المنتهية فقط")
        self.btn_expired_filter.setCheckable(True)
        self.btn_expired_filter.setFixedHeight(50)
        self.btn_expired_filter.setCursor(Qt.PointingHandCursor)
        self.btn_expired_filter.clicked.connect(lambda: self.toggle_filter('expired'))
        self.btn_expired_filter.setStyleSheet("""
            QPushButton {
                background-color: #34495E;
                color: white;
                padding: 0 20px;
                font-size: 18px;
                border-radius: 5px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
            QPushButton:checked {
                background-color: #2C3E50;
            }
        """)
        top_bar.addWidget(self.btn_expired_filter)

        self.btn_add = QPushButton("إضافة دواء")
        self.btn_add.setFixedHeight(50)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; "
            "font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';"
        )

        self.btn_edit = QPushButton("تعديل البيانات")
        self.btn_edit.setFixedHeight(50)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self.open_edit_dialog)
        self.btn_edit.setStyleSheet(
            "background-color: #F39C12; color: white; padding: 0 20px; "
            "font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';"
        )

        self.btn_refresh = QPushButton("تحديث")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet("font-size: 18px; font-family: 'Times New Roman';")

        self.btn_clear_stock = QPushButton("تصفير الكمية")
        self.btn_clear_stock.setFixedHeight(50)
        self.btn_clear_stock.setCursor(Qt.PointingHandCursor)
        self.btn_clear_stock.clicked.connect(self.clear_selected_stock)
        self.btn_clear_stock.setStyleSheet(
            "background-color: #D35400; color: white; padding: 0 20px; "
            "font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';"
        )

        self.btn_delete = QPushButton("حذف نهائي")
        self.btn_delete.setFixedHeight(50)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 0 20px; "
            "font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';"
        )

        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_edit)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_clear_stock)
        top_bar.addWidget(self.btn_delete)

        if self.user_role != 'admin':
            self.btn_add.hide()
            self.btn_edit.hide()
            self.btn_clear_stock.hide()
            self.btn_delete.hide()

        layout.addLayout(top_bar)

        self.low_stock_info_label = QLabel("")
        self.low_stock_info_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #C0392B; font-family: 'Times New Roman';"
        )
        layout.addWidget(self.low_stock_info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "ID", "الباركود", "اسم الدواء", "المادة الفعالة",
            "الشكل الصيدلاني", "التركيز",
            "شراء", "بيع", "الكمية الكلية", "أقرب صلاحية"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setStyleSheet("""
            QTableWidget {
                font-size: 16px;
                font-family: 'Times New Roman';
            }
            QHeaderView::section {
                font-size: 16px;
                font-weight: bold;
                font-family: 'Times New Roman';
            }
        """)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addWidget(self.table)
        self.setLayout(layout)

    # ==========================================
    # API for Main Controller (Dashboard Routing)
    # ==========================================
    def apply_external_filter(self, filter_type):
        """
        دالة عامة تُستدعى من خارج الكلاس (مثل main.py)
        لضبط حالة الفلترة برمجياً عند الانتقال من لوحة التحكم.
        """
        # مسح آمن للبحث لتجنب تأثيرات جانبية غير مرغوبة
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        if filter_type == "low_stock":
            self.btn_low_stock_filter.setChecked(True)
            self.btn_expired_filter.setChecked(False)
            self.active_filter = 'low_stock'
        elif filter_type == "expired":
            self.btn_expired_filter.setChecked(True)
            self.btn_low_stock_filter.setChecked(False)
            self.active_filter = 'expired'
        else:
            self.btn_low_stock_filter.setChecked(False)
            self.btn_expired_filter.setChecked(False)
            self.active_filter = None

        self._update_filter_buttons_ui()
        self.load_data()

    def toggle_filter(self, clicked_filter):
        """
        معالجة النقرات على أزرار الفلترة وضمان عدم تشغيل فلترين في آن واحد (Mutual Exclusion).
        """
        if clicked_filter == 'low_stock':
            if self.btn_low_stock_filter.isChecked():
                self.active_filter = 'low_stock'
                self.btn_expired_filter.setChecked(False)
            else:
                self.active_filter = None

        elif clicked_filter == 'expired':
            if self.btn_expired_filter.isChecked():
                self.active_filter = 'expired'
                self.btn_low_stock_filter.setChecked(False)
            else:
                self.active_filter = None

        self._update_filter_buttons_ui()
        self.load_data()

    def _update_filter_buttons_ui(self):
        self.btn_low_stock_filter.setText(
            "إلغاء فلتر النواقص" if self.active_filter == 'low_stock' else "عرض النواقص فقط"
        )
        self.btn_expired_filter.setText(
            "إلغاء فلتر المنتهية" if self.active_filter == 'expired' else "عرض المنتهية فقط"
        )

    def load_data(self):
        self._refresh_low_stock_state()
        self.refresh_table()

    def search_data(self):
        self.refresh_table()

    def _refresh_low_stock_state(self):
        low_stock_rows = self.dao.get_low_stock_medicines()
        self.low_stock_ids = {int(row[0]) for row in low_stock_rows if row and row[0] is not None}

        if self.low_stock_ids:
            self.low_stock_info_label.setText(f"عدد الأدوية الناقصة حالياً: {len(self.low_stock_ids)}")
        else:
            self.low_stock_info_label.setText("لا توجد أدوية ناقصة حالياً.")

    # ملاحظة تعاقدية مع MedicineDAO:
    # row_data[0]  = id
    # row_data[1]  = barcode
    # row_data[2]  = name
    # row_data[3]  = active_ingredient
    # row_data[4]  = dosage_form
    # row_data[5]  = strength
    # row_data[6]  = buy_price
    # row_data[7]  = sell_price
    # row_data[8]  = total_quantity
    # row_data[9]  = nearest_expiry
    # row_data[10] = is_controlled
    # row_data[11] = is_hazardous
    def refresh_table(self):
        search_text = self.search_input.text().strip()

        if search_text:
            data = self.dao.search_medicine(search_text)
        else:
            data = self.dao.get_all_medicines()

        # تطبيق الفلتر النشط
        filtered_data = []
        today = datetime.now().date()

        for row in data:
            medicine_id = int(row[0]) if row[0] is not None else None

            if self.active_filter == 'low_stock':
                if medicine_id in self.low_stock_ids:
                    filtered_data.append(row)

            elif self.active_filter == 'expired':
                expiry_str = row[9] if len(row) > 9 else None
                if expiry_str and expiry_str != "لا يوجد":
                    try:
                        expiry_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
                        if expiry_date < today:
                            filtered_data.append(row)
                    except Exception:
                        pass
            else:
                # لا يوجد فلتر نشط
                filtered_data.append(row)

        self.fill_table(filtered_data)

    def fill_table(self, data):
        self.table.setRowCount(0)

        today = datetime.now().date()
        warning_date = today + timedelta(days=90)

        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            medicine_id = int(row_data[0]) if row_data[0] is not None else None
            expiry_str = row_data[9] if len(row_data) > 9 else None
            is_controlled = int(row_data[10]) if len(row_data) > 10 and row_data[10] is not None else 0
            is_hazardous = int(row_data[11]) if len(row_data) > 11 and row_data[11] is not None else 0
            is_low_stock = medicine_id in self.low_stock_ids

            bg_color = None

            try:
                if expiry_str and expiry_str != "لا يوجد":
                    expiry_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
                    if expiry_date < today:
                        bg_color = QColor("#FFCDD2")   # منتهي الصلاحية
                    elif expiry_date <= warning_date:
                        bg_color = QColor("#FFE0B2")   # وشيك الانتهاء
            except Exception:
                pass

            if bg_color is None and is_low_stock:
                bg_color = QColor("#FDEDEC")         # ناقص مخزون

            for col_idx, col_data in enumerate(row_data):
                if col_idx >= 10:
                    break

                display_text = str(col_data) if col_data is not None and str(col_data).strip() != "" else "لا يوجد"

                if col_idx == 2:
                    badges = []

                    if is_low_stock:
                        badges.append("🚨")
                    if is_controlled == 1:
                        badges.append("💊")
                    if is_hazardous == 1:
                        badges.append("☣️")

                    if badges:
                        display_text = f"{' '.join(badges)} {display_text}"

                item = QTableWidgetItem(display_text)
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 2:
                    tooltip_parts = [display_text]
                    if is_low_stock:
                        tooltip_parts.append("هذا الدواء تحت حد التنبيه للمخزون.")
                    item.setToolTip("\n".join(tooltip_parts))

                    if is_controlled == 1 and is_hazardous == 1:
                        item.setForeground(QColor("#8E44AD"))
                        item.setFont(QFont("Times New Roman", 15, QFont.Bold))
                    elif is_controlled == 1:
                        item.setForeground(QColor("#C0392B"))
                        item.setFont(QFont("Times New Roman", 15, QFont.Bold))
                    elif is_hazardous == 1:
                        item.setForeground(QColor("#D35400"))
                        item.setFont(QFont("Times New Roman", 15, QFont.Bold))
                    elif is_low_stock:
                        item.setForeground(QColor("#C0392B"))
                        item.setFont(QFont("Times New Roman", 15, QFont.Bold))

                if col_idx == 8 and is_low_stock:
                    item.setForeground(QColor("#C0392B"))
                    item.setFont(QFont("Times New Roman", 15, QFont.Bold))
                    item.setToolTip("الكمية الحالية تحت حد التنبيه.")

                if bg_color:
                    item.setBackground(bg_color)

                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        dialog = AddMedicineDialog(self.session, self)
        if dialog.exec_():
            self.load_data()

    def open_edit_dialog(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد دواء لتعديله.")
            return

        drug_id = int(self.table.item(selected_row, 0).text())
        dialog = EditMedicineDialog(self.session, drug_id, self)
        if dialog.exec_():
            self.load_data()

    def clear_selected_stock(self):
        if not self.user_id:
            QMessageBox.critical(self, "خطأ أمني", "المستخدم غير محدد!")
            return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد دواء لتصفير كميته.")
            return

        drug_id = self.table.item(selected_row, 0).text()
        drug_name = self.table.item(selected_row, 2).text()

        confirm = QMessageBox.question(
            self,
            "تأكيد التصفير",
            f"هل أنت متأكد من تصفير كمية الدواء ({drug_name})؟\n"
            f"هذا الإجراء سيخرج الدواء من المخزون التشغيلي مع الحفاظ على تاريخه المالي.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.clear_medicine_stock(drug_id, self.user_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم التصفير بنجاح", msg)
            else:
                QMessageBox.critical(self, "رفض العملية", msg)

    def delete_selected(self):
        if not self.user_id:
            QMessageBox.critical(self, "خطأ أمني", "المستخدم غير محدد!")
            return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد دواء لحذفه.")
            return

        drug_id = self.table.item(selected_row, 0).text()
        drug_name = self.table.item(selected_row, 2).text()

        confirm = QMessageBox.question(
            self,
            "تحذير حذف جذري",
            f"هل أنت متأكد من الحذف النهائي للدواء ({drug_name})؟\n"
            f"ملاحظة: سيتم رفض العملية من النظام إذا كان للدواء أي ارتباطات مالية سابقة.",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_medicine(drug_id, self.user_id)
            if success:
                self.load_data()
                QMessageBox.information(self, "تم الحذف بنجاح", msg)
            else:
                QMessageBox.critical(self, "رفض العملية (حماية أمنية)", msg)