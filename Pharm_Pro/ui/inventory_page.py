from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QMessageBox, QLabel)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from models.medicine_dao import MedicineDAO
from ui.add_medicine_dialog import AddMedicineDialog
from datetime import datetime, timedelta


class InventoryPage(QWidget):
    def __init__(self, user_role="admin"):
        super().__init__()
        self.user_role = user_role
        self.dao = MedicineDAO()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # --- العنوان ومفتاح الألوان ---
        header_layout = QHBoxLayout()

        title = QLabel("إدارة المخزون والأدوية")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")

        legend = QLabel("🔴 منتهي الصلاحية   🟠 وشيك الانتهاء (أقل من 3 شهور)")
        legend.setStyleSheet("font-size: 14px; font-weight: bold; color: #555; font-family: 'Times New Roman';")

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(legend)

        layout.addLayout(header_layout)

        # الشريط العلوي
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 بحث بالاسم، الباركود، أو المادة الفعالة...")
        self.search_input.setFixedHeight(50)
        self.search_input.setStyleSheet(
            "font-size: 18px; padding: 0 10px; border: 1px solid #ccc; border-radius: 5px; font-family: 'Times New Roman';")
        self.search_input.textChanged.connect(self.search_data)
        top_bar.addWidget(self.search_input)

        self.btn_add = QPushButton("➕ إضافة دواء")
        self.btn_add.setFixedHeight(50)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.open_add_dialog)
        self.btn_add.setStyleSheet(
            "background-color: #27AE60; color: white; padding: 0 20px; font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';")

        self.btn_refresh = QPushButton("🔄 تحديث")
        self.btn_refresh.setFixedHeight(50)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_refresh.setStyleSheet("font-size: 18px; font-family: 'Times New Roman';")

        # زر الحذف (أصبح الآن ذكياً للحذف أو التصفير)
        self.btn_delete = QPushButton("🗑️ حذف / تصفير")
        self.btn_delete.setFixedHeight(50)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet(
            "background-color: #E74C3C; color: white; padding: 0 20px; font-size: 18px; border-radius: 5px; font-weight: bold; font-family: 'Times New Roman';")

        # إضافة الأزرار للواجهة
        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(self.btn_delete)

        # --- تطبيق الصلاحيات ---
        if self.user_role != 'admin':
            self.btn_add.hide()
            self.btn_delete.hide()

        layout.addLayout(top_bar)

        # جدول البيانات
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "الباركود", "اسم الدواء", "المادة الفعالة", "شراء", "بيع", "الكمية", "انتهاء الصلاحية"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setStyleSheet(
            "QTableWidget { font-size: 16px; font-family: 'Times New Roman'; } QHeaderView::section { font-size: 16px; font-weight: bold; font-family: 'Times New Roman'; }")

        # منع التعديل اليدوي المباشر في الجدول (لأن الحفظ يتطلب إجراء خاص)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        medicines = self.dao.get_all_medicines()
        self.fill_table(medicines)

    def search_data(self):
        text = self.search_input.text()
        if text:
            medicines = self.dao.search_medicine(text)
        else:
            medicines = self.dao.get_all_medicines()
        self.fill_table(medicines)

    def fill_table(self, data):
        self.table.setRowCount(0)

        today = datetime.now().date()
        warning_date = today + timedelta(days=90)

        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            expiry_str = row_data[7]
            bg_color = None

            try:
                if expiry_str:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                    if expiry_date < today:
                        bg_color = QColor("#FFCDD2")
                    elif expiry_date <= warning_date:
                        bg_color = QColor("#FFE0B2")
            except Exception:
                pass

            for col_idx, col_data in enumerate(row_data):
                item = QTableWidgetItem(str(col_data))
                item.setTextAlignment(Qt.AlignCenter)

                if bg_color:
                    item.setBackground(bg_color)

                self.table.setItem(row_idx, col_idx, item)

    def open_add_dialog(self):
        dialog = AddMedicineDialog(self)
        if dialog.exec_():
            self.load_data()

    def delete_selected(self):
        if self.user_role != 'admin':
            QMessageBox.warning(self, "تنبيه", "ليس لديك صلاحية الحذف!")
            return

        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد دواء لحذفه")
            return

        drug_id = self.table.item(selected_row, 0).text()
        drug_name = self.table.item(selected_row, 2).text()

        confirm = QMessageBox.question(self, "تأكيد الحذف", f"هل أنت متأكد من حذف {drug_name}؟",
                                       QMessageBox.Yes | QMessageBox.No)

        if confirm == QMessageBox.Yes:
            success, msg = self.dao.delete_medicine(drug_id)

            if success:
                self.load_data()
                QMessageBox.information(self, "تم", msg)
            else:
                # إذا كان الخطأ بسبب ارتباط الدواء بمبيعات سابقة
                if msg == "FOREIGN_KEY_ERROR":
                    reply = QMessageBox.question(self, "تنبيه هام",
                                                 f"لا يمكن حذف '{drug_name}' لأنه مرتبط بفواتير بيع/شراء سابقة.\n\n"
                                                 "هل تريد 'تصفير الكمية' (جعلها 0) بدلاً من الحذف؟",
                                                 QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.Yes:
                        # استدعاء دالة التصفير الجديدة
                        ok, txt = self.dao.clear_medicine_stock(drug_id)
                        if ok:
                            self.load_data()
                            QMessageBox.information(self, "تم", txt)
                        else:
                            QMessageBox.critical(self, "خطأ", txt)
                else:
                    QMessageBox.critical(self, "خطأ", msg)