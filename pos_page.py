"""
وظيفة الملف: نقطة البيع (POS).
الطبقة: Presentation Layer

ملاحظة معمارية وأمنية:
- [Strict Dumb Client]&#58; لا توجد أي استعلامات SQL أو حسابات رياضية.
- [Logical Grouping]&#58; الإضافة، التعديل، والحذف (remove_group) تعمل حصراً على مستوى "المجموعة" (الدواء + الارتباط الوصفي).
- [Render Guard]&#58; حماية ضد تسرب إشارات QSpinBox أثناء إعادة بناء الجدول.
- [Clinical Policy]&#58; الوصفات تُحمل بالكمية المتبقية كاملة افتراضياً، مع السماح للصيدلي بتخفيضها (Partial Dispensing).
- [Requirement 18 - Alternative Alerts]&#58; إذا كان الدواء موجوداً في النظام لكنه غير متاح للبيع حالياً، يتم اقتراح البدائل الدوائية المطابقة بدل اعتباره "غير موجود".
- [Requirement 19 - PDF Invoice]&#58; بعد نجاح البيع، يتم طلب بيانات الفاتورة النهائية من النواة (SalesDAO)
  وتوليد ملف PDF بشكل مستقل وآمن دون التأثير على نجاح عملية البيع نفسها.
- [Auto Open Then Ask Print]&#58; بعد نجاح توليد الفاتورة، يتم فتحها تلقائياً أولاً ثم سؤال المستخدم إن كان يريد طباعتها.
- [Hazardous Confirmation Gate]&#58; الأدوية الخطرة لا تُضاف إلى السلة إلا بعد موافقة المستخدم صراحةً مسبقاً.
- [Live Session Context]&#58; لا يتم الاعتماد على shift_id مخزن داخل الكائن؛ بل يُقرأ من session وقت الحاجة أو عند تحديث السياق.
"""

import os
import sys
import uuid
import logging
import subprocess

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QMessageBox, QFrame, QComboBox,
    QAbstractItemView, QSpinBox, QDialog, QTextEdit, QFormLayout
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QColor, QDesktopServices

from models.sales_dao import SalesDAO
from models.customers_dao import CustomersDAO
from models.prescriptions_dao import PrescriptionsDAO
from models.interactions_dao import InteractionsDAO
from models.drug_safety_dao import DrugSafetyDAO
from models.alternatives_dao import AlternativesDAO
from models.refill_alerts_dao import RefillAlertsDAO
from utils.pdf_generator import create_invoice_pdf

logger = logging.getLogger(__name__)


# ==========================================
# النوافذ المنبثقة (Dialogs)
# ==========================================
class ControlledDispensingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("سجل الأدوية الرقابية / المخدرة (إلزامي)")
        self.resize(450, 380)
        self.setStyleSheet(
            "QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #FDEDEC; }"
        )
        self.data = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        lbl = QLabel(
            "⚠️ السلة تحتوي على أدوية رقابية/مخدرة.\n"
            "يجب استكمال البيانات التالية وفقاً لاشتراطات وزارة الصحة:"
        )
        lbl.setStyleSheet("color: #C0392B; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(lbl)

        form = QFormLayout()
        form.setSpacing(15)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("الاسم الرباعي للمستلم *")
        self.name_input.setStyleSheet("padding: 8px; border: 1px solid #C0392B; border-radius: 4px;")

        self.nid_input = QLineEdit()
        self.nid_input.setPlaceholderText("رقم الهوية الوطنية / الإقامة *")
        self.nid_input.setStyleSheet("padding: 8px; border: 1px solid #C0392B; border-radius: 4px;")

        self.relation_combo = QComboBox()
        self.relation_combo.addItems([
            "المريض نفسه (self)",
            "أب / أم (parent)",
            "زوج / زوجة (spouse)",
            "وصي قانوني (guardian)",
            "أخرى (other)"
        ])
        self.relation_combo.setStyleSheet("padding: 8px; border: 1px solid #BDC3C7; border-radius: 4px;")

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الجوال (اختياري)")
        self.phone_input.setStyleSheet("padding: 8px; border: 1px solid #BDC3C7; border-radius: 4px;")

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("ملاحظات تنظيمية إضافية...")
        self.notes_input.setStyleSheet("padding: 8px; border: 1px solid #BDC3C7; border-radius: 4px;")

        form.addRow("اسم المستلم *:", self.name_input)
        form.addRow("رقم الهوية *:", self.nid_input)
        form.addRow("صلة القرابة *:", self.relation_combo)
        form.addRow("رقم الهاتف:", self.phone_input)
        form.addRow("ملاحظات:", self.notes_input)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()

        self.btn_save = QPushButton(" ✅ اعتماد بيانات السجل")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(
            "background-color: #C0392B; color: white; font-weight: bold; padding: 10px; border-radius: 5px;"
        )
        self.btn_save.clicked.connect(self.validate_and_accept)

        self.btn_cancel = QPushButton(" ❌ إلغاء الصرف")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            "background-color: #7F8C8D; color: white; font-weight: bold; padding: 10px; border-radius: 5px;"
        )
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def validate_and_accept(self):
        name = self.name_input.text().strip()
        nid = self.nid_input.text().strip()

        if not name or not nid:
            QMessageBox.warning(self, "تنبيه رقابي", "اسم المستلم ورقم الهوية حقول إلزامية.")
            return

        relation_text = self.relation_combo.currentText()
        relation_val = 'self'
        if 'parent' in relation_text:
            relation_val = 'parent'
        elif 'spouse' in relation_text:
            relation_val = 'spouse'
        elif 'guardian' in relation_text:
            relation_val = 'guardian'
        elif 'other' in relation_text:
            relation_val = 'other'

        self.data = {
            'receiver_full_name': name,
            'receiver_national_id': nid,
            'receiver_phone': self.phone_input.text().strip(),
            'receiver_relation': relation_val,
            'notes': self.notes_input.text().strip()
        }
        self.accept()

    def get_data(self):
        return self.data


class ClinicalReviewDialog(QDialog):
    def __init__(self, html_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("المراجعة السريرية (قبل إتمام البيع)")
        self.resize(650, 500)
        self.setStyleSheet(
            "QDialog { background-color: #F5F6FA; font-family: 'Times New Roman'; font-size: 16px; }"
        )

        layout = QVBoxLayout(self)

        title = QLabel("⚠️ المراجعة السريرية النهائية للأصناف في السلة")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2C3E50; margin-bottom: 10px;")
        layout.addWidget(title)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setHtml(html_content)
        self.text_edit.setStyleSheet(
            "background-color: white; padding: 15px; border: 1px solid #BDC3C7; border-radius: 5px; line-height: 1.6;"
        )
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()

        self.btn_accept = QPushButton(" ✅ اطلعت، إتمام البيع")
        self.btn_accept.setCursor(Qt.PointingHandCursor)
        self.btn_accept.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; padding: 12px; border-radius: 5px;"
        )
        self.btn_accept.clicked.connect(self.accept)

        self.btn_reject = QPushButton(" ❌ تراجع لتعديل السلة")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; padding: 12px; border-radius: 5px;"
        )
        self.btn_reject.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_reject)
        btn_layout.addWidget(self.btn_accept)
        layout.addLayout(btn_layout)


class AlternativesDialog(QDialog):
    def __init__(self, alternatives, parent=None):
        super().__init__(parent)
        self.alternatives = alternatives
        self.selected_alt = None
        self.setWindowTitle("البدائل الدوائية المتاحة")
        self.resize(650, 400)
        self.setStyleSheet(
            "QDialog { font-family: 'Times New Roman'; font-size: 16px; background-color: #F5F6FA; }"
        )
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        if self.alternatives:
            base_info = (
                f"{self.alternatives[0]['active_ingredient']} | "
                f"{self.alternatives[0]['dosage_form']} | "
                f"{self.alternatives[0]['strength']}"
            )
            lbl = QLabel(f"<b>البدائل الطبية المطابقة لـ:</b><br>{base_info}")
            lbl.setStyleSheet("color: #2980B9; font-size: 16px; margin-bottom: 10px;")
            layout.addWidget(lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "اسم البديل (التجاري)", "السعر", "الكمية المتاحة"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.table.setRowCount(len(self.alternatives))
        for i, alt in enumerate(self.alternatives):
            self.table.setItem(i, 0, QTableWidgetItem(str(alt['id'])))

            alt_name = alt['name']
            if alt.get('is_controlled', 0) == 1:
                alt_name += " 🔴"
            elif alt.get('is_hazardous', 0) == 1:
                alt_name += " ☣️"

            name_item = QTableWidgetItem(alt_name)
            if alt.get('is_controlled', 0) == 1:
                name_item.setForeground(QColor("#C0392B"))
            elif alt.get('is_hazardous', 0) == 1:
                name_item.setForeground(QColor("#D35400"))

            self.table.setItem(i, 1, name_item)
            self.table.setItem(i, 2, QTableWidgetItem(f"{alt['sell_price']:.2f}"))

            qty_item = QTableWidgetItem(str(alt['available_qty']))
            qty_item.setForeground(QColor("#27AE60"))
            qty_item.setFont(QFont("Times New Roman", 12, QFont.Bold))
            self.table.setItem(i, 3, qty_item)

            for col in [0, 1, 2, 3]:
                self.table.item(i, col).setTextAlignment(Qt.AlignCenter)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_select = QPushButton(" 🛒 إضافة البديل المحدد للسلة")
        self.btn_select.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; padding: 10px; border-radius: 5px;"
        )
        self.btn_select.clicked.connect(self.select_alternative)

        self.btn_cancel = QPushButton(" ❌ إلغاء")
        self.btn_cancel.setStyleSheet(
            "background-color: #E74C3C; color: white; font-weight: bold; padding: 10px; border-radius: 5px;"
        )
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_select)
        layout.addLayout(btn_layout)

    def select_alternative(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد بديل من الجدول أولاً.")
            return

        self.selected_alt = self.alternatives[row]
        self.accept()

    def get_selected_alternative(self):
        return self.selected_alt


# ==========================================
# الواجهة الرئيسية (POS Page)
# ==========================================
class POSPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = SalesDAO()
        self.customers_dao = CustomersDAO()
        self.rx_dao = PrescriptionsDAO()
        self.interactions_dao = InteractionsDAO()
        self.safety_dao = DrugSafetyDAO()
        self.alt_dao = AlternativesDAO()
        self.refill_dao = RefillAlertsDAO()

        self.cart_lines = []
        self._is_rendering = False

        self.pricing_cache = {
            "items": {},
            "invalid_lines": {},
            "gross_subtotal": 0.0,
            "subtotal_amount": 0.0,
            "cart_discount_amount": 0.0,
            "net_total": 0.0,
            "general_error": None
        }

        self.init_ui()
        self.load_customers()
        self.refresh_session_context()

    # ==========================================
    # Live Session Context
    # ==========================================
    def _get_current_shift_id(self):
        return self.session.get("shift_id") if self.session else None

    def refresh_session_context(self):
        """
        تُستدعى عند تغير الجلسة من الخارج أو عند إظهار الصفحة.
        """
        self.user_id = self.session.get("user_id") if self.session else None
        self.user_role = self.session.get("role", "pharmacist") if self.session else "pharmacist"

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_session_context()

    def init_ui(self):
        layout = QHBoxLayout()
        right_panel = QVBoxLayout()

        rx_layout = QHBoxLayout()

        self.rx_input = QLineEdit()
        self.rx_input.setPlaceholderText("أدخل رقم الوصفة لاستدعائها (مثال: RX-2026...)...")
        self.rx_input.setStyleSheet(
            "padding: 10px; font-size: 16px; border: 2px solid #9B59B6; border-radius: 5px; font-family: 'Times New Roman';"
        )
        self.rx_input.returnPressed.connect(self.load_prescription)

        self.btn_load_rx = QPushButton(" 📜 استدعاء وصفة")
        self.btn_load_rx.setStyleSheet(
            "background-color: #8E44AD; color: white; padding: 10px; font-size: 16px; font-weight: bold; border-radius: 5px; font-family: 'Times New Roman';"
        )
        self.btn_load_rx.setCursor(Qt.PointingHandCursor)
        self.btn_load_rx.clicked.connect(self.load_prescription)

        rx_layout.addWidget(self.rx_input, stretch=3)
        rx_layout.addWidget(self.btn_load_rx, stretch=1)
        right_panel.addLayout(rx_layout)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("أدخل اسم الدواء أو الباركود (للمبيعات الحرة OTC)...")
        self.search_input.setStyleSheet(
            "padding: 15px; font-size: 16px; border: 2px solid #3498DB; border-radius: 10px; font-family: 'Times New Roman'; margin-top: 10px;"
        )
        self.search_input.returnPressed.connect(self.add_free_item)
        right_panel.addWidget(self.search_input)

        self.lbl_quote_error = QLabel("")
        self.lbl_quote_error.setStyleSheet("color: #C0392B; font-weight: bold; font-size: 14px;")
        self.lbl_quote_error.hide()
        right_panel.addWidget(self.lbl_quote_error)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Line ID", "اسم الدواء", "سعر الوحدة", "الكمية", "خصم السطر", "الإجمالي الصافي", "حذف"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.hideColumn(0)
        self.table.setStyleSheet("font-family: 'Times New Roman'; font-size: 16px;")
        right_panel.addWidget(self.table)

        actions_layout = QHBoxLayout()
        self.btn_clear = QPushButton(" تفريغ السلة")
        self.btn_clear.clicked.connect(self.clear_cart)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet("padding: 10px; font-size: 14px; border-radius: 5px;")
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_clear)
        right_panel.addLayout(actions_layout)

        layout.addLayout(right_panel, stretch=2)

        left_panel = QFrame()
        left_panel.setStyleSheet("background-color: #2C3E50; border-radius: 15px; color: white;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(20, 20, 20, 20)

        lbl_cust = QLabel(" العميل:")
        lbl_cust.setFont(QFont("Times New Roman", 14, QFont.Bold))
        left_layout.addWidget(lbl_cust)

        self.customer_combo = QComboBox()
        self.customer_combo.setStyleSheet(
            "QComboBox { background-color: white; color: black; padding: 10px; border-radius: 5px; font-family: 'Times New Roman'; font-size: 14px; }"
        )
        self.customer_combo.currentIndexChanged.connect(self.check_patient_alerts)
        left_layout.addWidget(self.customer_combo)

        lbl_doc = QLabel(" الطبيب المعالج:")
        lbl_doc.setFont(QFont("Times New Roman", 14, QFont.Bold))
        left_layout.addWidget(lbl_doc)

        self.doctor_input = QLineEdit()
        self.doctor_input.setPlaceholderText("اسم الطبيب (اختياري)")
        self.doctor_input.setStyleSheet(
            "background-color: white; color: black; padding: 10px; border-radius: 5px; font-family: 'Times New Roman'; font-size: 14px;"
        )
        left_layout.addWidget(self.doctor_input)
        left_layout.addStretch()

        self.subtotal_label = QLabel("المجموع (قبل خصم الفاتورة): 0.00")
        self.subtotal_label.setStyleSheet("font-size: 16px; color: #BDC3C7;")
        left_layout.addWidget(self.subtotal_label)

        self.cart_discount_label = QLabel("خصم الفاتورة الإجمالي: 0.00")
        self.cart_discount_label.setStyleSheet("font-size: 16px; color: #F1C40F;")
        left_layout.addWidget(self.cart_discount_label)

        title = QLabel("الصافي المطلوب")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Times New Roman", 20, QFont.Bold))
        left_layout.addWidget(title)

        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignCenter)
        self.total_label.setStyleSheet("font-size: 44px; color: #2ECC71; font-weight: bold;")
        left_layout.addWidget(self.total_label)
        left_layout.addStretch()

        self.btn_checkout = QPushButton(" إتمام البيع والتخريج")
        self.btn_checkout.setCursor(Qt.PointingHandCursor)
        self.btn_checkout.clicked.connect(self.checkout)
        self.btn_checkout.setStyleSheet(
            "QPushButton { background-color: #27AE60; color: white; font-size: 22px; padding: 15px; border-radius: 10px; font-weight: bold; } "
            "QPushButton:hover { background-color: #219150; } "
            "QPushButton:disabled { background-color: #95A5A6; }"
        )
        left_layout.addWidget(self.btn_checkout)

        layout.addWidget(left_panel, stretch=1)
        self.setLayout(layout)

    # ==========================================
    # تفاعلات الواجهة والإدارة المنطقية للمجموعات
    # ==========================================
    def load_customers(self):
        self.customer_combo.blockSignals(True)
        self.customer_combo.clear()
        self.customer_combo.addItem("عميل نقدي (Walk-in)", None)
        for cust in self.customers_dao.get_all_customers():
            self.customer_combo.addItem(f"{cust[1]} - {cust[2]}", cust[0])
        self.customer_combo.blockSignals(False)

    def check_patient_alerts(self):
        customer_id = self.customer_combo.currentData()
        if not customer_id:
            return False

        alerts = self.refill_dao.get_patient_refill_alerts(customer_id, days_ahead=7)
        if alerts:
            msg = "📌 <b>تنبيه استباقي:</b> هذا المريض لديه أدوية مزمنة مستحقة لإعادة التعبئة قريباً:\n\n"
            for alert in alerts:
                med_name = alert.get('medicine_name', 'غير معروف')
                exhaust_date = alert.get('expected_exhaustion_date', 'غير معروف')
                msg += f"💊 <b>{med_name}</b> (تاريخ النفاد المتوقع: {exhaust_date})\n"

            QMessageBox.information(self, "متابعة الأدوية المزمنة", msg)
            return True

        return False

    def _confirm_hazardous_addition(self, medicine_name, extra_message=""):
        message = (
            f"الصنف ({medicine_name}) مصنف كمادة خطرة ☣️.\n"
            "هل تريد متابعة إضافته إلى السلة؟"
        )
        if extra_message:
            message += f"\n\n{extra_message}"

        reply = QMessageBox.question(
            self,
            "تأكيد إضافة مادة خطرة",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        return reply == QMessageBox.Yes

    def _get_group_current_qty(self, med_id, rx_item_id=None):
        return sum(
            item['qty'] for item in self.cart_lines
            if item['medicine_id'] == med_id and item['prescription_item_id'] == rx_item_id
        )

    def _remove_group_lines(self, med_id, rx_item_id=None):
        self.cart_lines = [
            item for item in self.cart_lines
            if not (item['medicine_id'] == med_id and item['prescription_item_id'] == rx_item_id)
        ]

    def _distribute_and_add_group(self, med_id, name, target_qty, is_controlled, is_hazardous,
                                  rx_item_id=None, rx_remaining_qty=None):
        allocated = self.dao.get_fifo_batches_for_qty(med_id, target_qty)
        if not allocated:
            return False, "لا توجد تشغيلات صالحة أو نفدت الكمية."

        total_allocated = sum(a['taken_qty'] for a in allocated)
        if total_allocated < target_qty:
            return False, f"الكمية المطلوبة ({target_qty}) تتجاوز الرصيد الإجمالي المتاح ({total_allocated})."

        for alloc in allocated:
            max_visual_qty = alloc['max_qty']
            if rx_item_id and rx_remaining_qty is not None:
                max_visual_qty = min(max_visual_qty, rx_remaining_qty)

            self.cart_lines.append({
                'line_id': str(uuid.uuid4()),
                'medicine_id': med_id,
                'batch_id': alloc['batch_id'],
                'name': name,
                'qty': alloc['taken_qty'],
                'prescription_item_id': rx_item_id,
                'is_controlled': is_controlled,
                'is_hazardous': is_hazardous,
                'max_qty': max_visual_qty,
                'rx_remaining_qty': rx_remaining_qty
            })

        return True, ""

    def _get_original_medicine_identity(self, text):
        row = self.dao.get_medicine_identity_by_barcode_or_name(text)
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "barcode": row[2],
            "active_ingredient": row[3],
            "dosage_form": row[4],
            "strength": row[5],
            "is_controlled": row[6],
            "controlled_class": row[7],
            "is_hazardous": row[8]
        }

    def add_free_item(self):
        text = self.search_input.text().strip()
        if not text:
            return

        med_info = self.dao.get_medicine_by_barcode_or_name(text)

        if not med_info:
            original_med = self._get_original_medicine_identity(text)

            if not original_med:
                QMessageBox.warning(self, "خطأ", "الدواء غير موجود في النظام.")
                self.search_input.clear()
                return

            if original_med.get("is_controlled", 0) == 1:
                QMessageBox.critical(
                    self,
                    "منع رقابي",
                    f"الدواء ({original_med['name']}) مصنف رقابياً ولا يمكن صرفه كمبيع حر (OTC)."
                )
                self.search_input.clear()
                return

            self._prompt_alternatives_for_id(
                original_med["id"],
                f"الدواء ({original_med['name']}) موجود في النظام لكنه غير متاح حالياً للبيع من المخزون."
            )
            self.search_input.clear()
            return

        m_id, name, _, stock, barcode, is_ctrl, ctrl_class, is_haz = med_info

        if is_ctrl == 1:
            QMessageBox.critical(self, "منع رقابي", "هذا الدواء مصنف رقابياً ولا يمكن صرفه كمبيع حر (OTC).")
            self.search_input.clear()
            return

        current_qty = self._get_group_current_qty(m_id, rx_item_id=None)

        if is_haz == 1 and current_qty == 0:
            confirmed = self._confirm_hazardous_addition(name)
            if not confirmed:
                self.search_input.clear()
                return

        target_qty = current_qty + 1

        self._remove_group_lines(m_id, rx_item_id=None)
        success, err_msg = self._distribute_and_add_group(
            m_id, name, target_qty,
            is_controlled=0,
            is_hazardous=is_haz,
            rx_item_id=None
        )

        if not success:
            if current_qty > 0:
                self._distribute_and_add_group(
                    m_id, name, current_qty,
                    is_controlled=0,
                    is_hazardous=is_haz,
                    rx_item_id=None
                )
                QMessageBox.warning(self, "تنبيه", err_msg)
            else:
                self._prompt_alternatives_for_id(
                    m_id,
                    f"الصنف ({name}) غير متاح حالياً. {err_msg}"
                )

            self.search_input.clear()
            return

        self.search_input.clear()
        self.refresh_pricing_and_ui()

    def load_prescription(self):
        rx_number = self.rx_input.text().strip()
        if not rx_number:
            return

        success, result = self.rx_dao.get_prescription_for_pos(rx_number)
        if not success:
            QMessageBox.warning(self, "فشل الاستدعاء", result)
            return

        cust_id = result.get('customer_id')
        if not cust_id:
            QMessageBox.critical(self, "خطأ بيانات", "الوصفة لا تحتوي على معرف عميل (customer_id).")
            return

        idx = self.customer_combo.findData(cust_id)
        if idx >= 0:
            self.customer_combo.blockSignals(True)
            self.customer_combo.setCurrentIndex(idx)
            self.customer_combo.blockSignals(False)
            self.check_patient_alerts()
        else:
            QMessageBox.warning(self, "خطأ", "العميل المرتبط بالوصفة غير مسجل أو غير متاح في قائمة العملاء.")
            return

        self.doctor_input.setText(result['doctor_name'])

        loaded_count = 0
        out_of_stock = []
        shortage_items = []
        hazardous_skipped = []

        for rx_item in result['items']:
            med_id = rx_item['medicine_id']
            med_name = rx_item['medicine_name']
            rem_qty = rx_item['remaining_qty']
            rx_item_id = rx_item['prescription_item_id']

            if any(c.get('prescription_item_id') == rx_item_id for c in self.cart_lines):
                continue

            is_ctrl, is_haz = self.dao.get_medicine_flags(med_id)

            if is_haz == 1:
                confirmed = self._confirm_hazardous_addition(
                    med_name,
                    "هذا الصنف وارد ضمن الوصفة الطبية المستدعاة."
                )
                if not confirmed:
                    hazardous_skipped.append(med_name)
                    continue

            success, err_msg = self._distribute_and_add_group(
                med_id,
                med_name,
                target_qty=rem_qty,
                is_controlled=is_ctrl,
                is_hazardous=is_haz,
                rx_item_id=rx_item_id,
                rx_remaining_qty=rem_qty
            )

            if success:
                loaded_count += 1
            else:
                out_of_stock.append(f"{med_name} ({err_msg})")
                shortage_items.append({
                    "medicine_id": med_id,
                    "medicine_name": med_name,
                    "reason": err_msg,
                    "is_controlled": is_ctrl
                })

        self.refresh_pricing_and_ui()
        self.rx_input.clear()

        post_messages = []

        if out_of_stock:
            post_messages.append("نواقص (تعذر استدعاء التالي):\n" + "\n".join(out_of_stock))

        if hazardous_skipped:
            post_messages.append(
                "تم تجاهل الأصناف الخطرة التالية لأن المستخدم رفض إضافتها:\n" +
                "\n".join(hazardous_skipped)
            )

        if post_messages:
            QMessageBox.warning(self, "نتيجة استدعاء الوصفة", "\n\n".join(post_messages))
            if out_of_stock:
                self._offer_alternatives_for_shortages(shortage_items)

        elif loaded_count > 0:
            QMessageBox.information(
                self,
                "نجاح",
                f"تم تحميل {loaded_count} صنف من الوصفة.\n"
                f"تنبيه: يمكنك تقليل الكمية عبر الجدول إذا رغب المريض بصرف جزئي."
            )

    def _offer_alternatives_for_shortages(self, shortage_items):
        for shortage in shortage_items:
            med_id = shortage.get("medicine_id")
            med_name = shortage.get("medicine_name")
            reason = shortage.get("reason", "غير متاح")
            is_controlled = shortage.get("is_controlled", 0)

            if is_controlled == 1:
                continue

            alternatives = self.alt_dao.get_alternatives_for_medicine(med_id)
            if not alternatives:
                continue

            reply = QMessageBox.question(
                self,
                "بدائل دوائية متاحة",
                f"الصنف الموصوف ({med_name}) غير متاح حالياً.\n"
                f"السبب: {reason}\n\n"
                f"يوجد بدائل دوائية مطابقة ومتاحة للبيع.\n"
                f"هل تريد عرضها الآن؟",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self._show_alternatives_dialog(alternatives)

    def _prompt_alternatives_for_id(self, med_id, warning_msg):
        alternatives = self.alt_dao.get_alternatives_for_medicine(med_id)

        if alternatives:
            reply = QMessageBox.question(
                self,
                "تنبيه المخزون",
                warning_msg + "\nيوجد بدائل طبية مطابقة. هل ترغب بعرضها؟",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._show_alternatives_dialog(alternatives)
        else:
            QMessageBox.warning(
                self,
                "تنبيه المخزون",
                warning_msg + "\nلا توجد بدائل متاحة لهذا الدواء حالياً."
            )

    def _show_alternatives_dialog(self, alternatives_list):
        dialog = AlternativesDialog(alternatives_list, self)
        if dialog.exec_():
            selected_alt = dialog.get_selected_alternative()
            if selected_alt:
                self._add_alternative_to_cart(selected_alt)

    def _add_alternative_to_cart(self, alt_dict):
        if alt_dict.get('is_controlled', 0) == 1:
            QMessageBox.critical(self, "منع رقابي", "هذا البديل رقابي/مخدر، يُمنع إضافته كمبيع حر.")
            return

        med_id = alt_dict['id']
        is_haz = alt_dict.get('is_hazardous', 0)
        med_name = alt_dict['name']
        current_qty = self._get_group_current_qty(med_id, rx_item_id=None)

        if is_haz == 1 and current_qty == 0:
            confirmed = self._confirm_hazardous_addition(med_name, "هذا الصنف هو بديل دوائي مقترح.")
            if not confirmed:
                return

        target_qty = current_qty + 1

        self._remove_group_lines(med_id, rx_item_id=None)
        success, err_msg = self._distribute_and_add_group(
            med_id,
            med_name,
            target_qty,
            is_controlled=0,
            is_hazardous=is_haz,
            rx_item_id=None
        )

        if not success:
            if current_qty > 0:
                self._distribute_and_add_group(
                    med_id,
                    med_name,
                    current_qty,
                    is_controlled=0,
                    is_hazardous=is_haz,
                    rx_item_id=None
                )
            QMessageBox.warning(self, "تنبيه", err_msg)
            return

        self.refresh_pricing_and_ui()

    def remove_group(self, med_id, rx_item_id):
        self._remove_group_lines(med_id, rx_item_id)
        self.refresh_pricing_and_ui()

    def update_qty(self, line_id, new_qty):
        if getattr(self, '_is_rendering', False):
            return

        target_line = next((item for item in self.cart_lines if item['line_id'] == line_id), None)
        if not target_line:
            return

        med_id = target_line['medicine_id']
        rx_item_id = target_line.get('prescription_item_id')
        name = target_line['name']
        is_ctrl = target_line.get('is_controlled', 0)
        is_haz = target_line.get('is_hazardous', 0)
        rx_remaining = target_line.get('rx_remaining_qty')

        other_lines_qty = sum(
            item['qty'] for item in self.cart_lines
            if item['medicine_id'] == med_id
            and item['prescription_item_id'] == rx_item_id
            and item['line_id'] != line_id
        )

        target_group_qty = other_lines_qty + new_qty

        if rx_item_id and rx_remaining is not None and target_group_qty > rx_remaining:
            QMessageBox.warning(
                self,
                "تجاوز طبي",
                f"إجمالي الكمية ({target_group_qty}) يتجاوز المتبقي في الوصفة ({rx_remaining})."
            )
            self.render_table()
            return

        self._remove_group_lines(med_id, rx_item_id)
        success, err_msg = self._distribute_and_add_group(
            med_id,
            name,
            target_group_qty,
            is_controlled=is_ctrl,
            is_hazardous=is_haz,
            rx_item_id=rx_item_id,
            rx_remaining_qty=rx_remaining
        )

        if not success:
            old_total = other_lines_qty + target_line['qty']
            if old_total > 0:
                self._distribute_and_add_group(
                    med_id,
                    name,
                    old_total,
                    is_ctrl,
                    is_haz,
                    rx_item_id,
                    rx_remaining
                )
            QMessageBox.warning(self, "تنبيه", err_msg)
            self.render_table()
            return

        self.refresh_pricing_and_ui()

    def clear_cart(self):
        self.cart_lines.clear()
        self.refresh_pricing_and_ui()

        self.customer_combo.blockSignals(True)
        self.customer_combo.setCurrentIndex(0)
        self.customer_combo.blockSignals(False)

        self.doctor_input.clear()
        self.search_input.clear()
        self.rx_input.clear()
        self.search_input.setFocus()

    # ==========================================
    # تحديث التسعير السيادي
    # ==========================================
    def refresh_pricing_and_ui(self):
        if not self.cart_lines:
            self.pricing_cache = {
                "items": {},
                "invalid_lines": {},
                "subtotal_amount": 0.0,
                "cart_discount_amount": 0.0,
                "net_total": 0.0,
                "general_error": None
            }
            self.render_table()
            return

        ui_items_for_quote = [
            {
                'line_id': i['line_id'],
                'medicine_id': i['medicine_id'],
                'batch_id': i['batch_id'],
                'qty': i['qty']
            }
            for i in self.cart_lines
        ]

        quote_result = self.dao.quote_sale(ui_items_for_quote)

        if not quote_result:
            self.pricing_cache = {
                "items": {},
                "invalid_lines": {},
                "subtotal_amount": 0.0,
                "cart_discount_amount": 0.0,
                "net_total": 0.0,
                "general_error": "فشل الاتصال بالنواة."
            }
            self.render_table()
            return

        new_items_cache = {}
        for p_item in quote_result.get('items', []):
            new_items_cache[p_item['line_id']] = p_item

        invalid_map = {}
        for inv in quote_result.get('invalid_lines', []):
            invalid_map[inv['line_id']] = inv['reason']

        self.pricing_cache = {
            "items": new_items_cache,
            "invalid_lines": invalid_map,
            "subtotal_amount": quote_result.get('subtotal_amount', 0.0),
            "cart_discount_amount": quote_result.get('cart_discount_amount', 0.0),
            "net_total": quote_result.get('net_total', 0.0),
            "general_error": quote_result.get('general_error')
        }

        self.render_table()

    def render_table(self):
        self._is_rendering = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        has_invalid = False

        if self.pricing_cache.get('general_error'):
            self.lbl_quote_error.setText(f"⚠️ خطأ عام في التسعير: {self.pricing_cache['general_error']}")
            self.lbl_quote_error.show()
            has_invalid = True
        else:
            self.lbl_quote_error.hide()

        for row, item in enumerate(self.cart_lines):
            l_id = item['line_id']
            m_id = item['medicine_id']
            rx_id = item.get('prescription_item_id')

            priced_item = self.pricing_cache['items'].get(l_id)
            invalid_reason = self.pricing_cache['invalid_lines'].get(l_id)

            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(l_id))

            display_name = item['name']
            if rx_id:
                display_name += " 📜"
            if item.get('is_controlled') == 1:
                display_name += " 🔴"
            elif item.get('is_hazardous') == 1:
                display_name += " ☣️"

            name_widget = QTableWidgetItem(display_name)
            name_widget.setFont(QFont("Times New Roman", 16, QFont.Bold))
            self.table.setItem(row, 1, name_widget)

            spin = QSpinBox()
            spin.setRange(1, item.get('max_qty', 9999))
            spin.setValue(item['qty'])
            spin.valueChanged.connect(lambda val, lid=l_id: self.update_qty(lid, val))
            self.table.setCellWidget(row, 3, spin)

            if invalid_reason:
                has_invalid = True
                name_widget.setForeground(QColor("#C0392B"))
                name_widget.setToolTip(f"مرفوض من النواة: {invalid_reason}")

                err_widget = QTableWidgetItem("خطأ تسعير")
                err_widget.setForeground(QColor("#C0392B"))

                self.table.setItem(row, 2, QTableWidgetItem("مرفوض"))
                self.table.setItem(row, 4, QTableWidgetItem("-"))
                self.table.setItem(row, 5, err_widget)

                for col in range(1, 6):
                    if self.table.item(row, col):
                        self.table.item(row, col).setBackground(QColor("#FDEDEC"))

            elif priced_item:
                orig_price = priced_item.get('original_unit_price', 0.0)
                self.table.setItem(row, 2, QTableWidgetItem(f"{orig_price:.2f}"))

                disc_amount = priced_item.get('discount_amount', 0.0)
                disc_widget = QTableWidgetItem(f"{disc_amount:.2f}")
                if disc_amount > 0:
                    disc_widget.setForeground(QColor("#E74C3C"))
                self.table.setItem(row, 4, disc_widget)

                total_price = priced_item.get('total_item_price', 0.0)
                total_widget = QTableWidgetItem(f"{total_price:.2f}")
                total_widget.setFont(QFont("Times New Roman", 16, QFont.Bold))
                self.table.setItem(row, 5, total_widget)

            else:
                has_invalid = True
                self.table.setItem(row, 2, QTableWidgetItem("فشل التسعير"))
                self.table.setItem(row, 4, QTableWidgetItem("-"))
                self.table.setItem(row, 5, QTableWidgetItem("خطأ غير معروف"))

                for col in range(1, 6):
                    if self.table.item(row, col):
                        self.table.item(row, col).setBackground(QColor("#FDEDEC"))

            btn_rem = QPushButton("❌")
            btn_rem.setStyleSheet("color: red; border: none; font-size: 18px;")
            btn_rem.setCursor(Qt.PointingHandCursor)
            btn_rem.clicked.connect(lambda _, m=m_id, r=rx_id: self.remove_group(m, r))
            self.table.setCellWidget(row, 6, btn_rem)

            for col in [1, 2, 4, 5]:
                if self.table.item(row, col):
                    self.table.item(row, col).setTextAlignment(Qt.AlignCenter)

        self.subtotal_label.setText(f"المجموع (قبل خصم الفاتورة): {self.pricing_cache['subtotal_amount']:,.2f}")
        self.cart_discount_label.setText(f"خصم الفاتورة الإجمالي: {self.pricing_cache['cart_discount_amount']:,.2f}")
        self.total_label.setText(f"{self.pricing_cache['net_total']:,.2f}")

        self.btn_checkout.setEnabled(not has_invalid and len(self.cart_lines) > 0)
        self.table.blockSignals(False)
        self._is_rendering = False

    # ==========================================
    # Requirement 19: PDF Helpers
    # ==========================================
    def _generate_pdf_for_sale(self, sale_id):
        """
        يولد PDF اعتماداً على الحقيقة النهائية القادمة من النواة.
        لا يسمح لفشل الـ PDF بأن يفشل عملية البيع نفسها.
        """
        try:
            if not hasattr(self.dao, "get_sale_receipt_data"):
                logger.error("SalesDAO is missing get_sale_receipt_data(sale_id).")
                return None, "محرك استرجاع بيانات الفاتورة غير موجود في النواة."

            receipt_result = self.dao.get_sale_receipt_data(sale_id)

            if not isinstance(receipt_result, tuple) or len(receipt_result) != 2:
                logger.error(
                    "Unexpected return contract from get_sale_receipt_data for sale_id=%s: %r",
                    sale_id,
                    receipt_result
                )
                return None, "صيغة الإرجاع من محرك الفاتورة غير صحيحة."

            success, payload = receipt_result

            if not success:
                error_message = payload if isinstance(payload, str) else "تعذر جلب بيانات الفاتورة النهائية من النظام."
                logger.error("Receipt data fetch failed for sale_id=%s: %s", sale_id, error_message)
                return None, error_message

            if not isinstance(payload, dict):
                logger.error("Receipt payload is not dict for sale_id=%s: %r", sale_id, payload)
                return None, "بيانات الفاتورة المستلمة من النواة غير صالحة."

            pdf_path = create_invoice_pdf(payload)
            if not pdf_path:
                logger.error("PDF generation returned None for sale_id=%s.", sale_id)
                return None, "فشل توليد ملف PDF."

            return pdf_path, None

        except Exception:
            logger.exception("Unexpected PDF generation failure for sale_id=%s:", sale_id)
            return None, "حدث خطأ داخلي أثناء توليد الفاتورة PDF."

    def _open_pdf_file(self, pdf_path):
        try:
            if not pdf_path:
                return False
            return QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
        except Exception:
            logger.exception("Failed to open PDF file: %s", pdf_path)
            return False

    def _print_pdf_file(self, pdf_path):
        """
        طباعة مباشرة:
        - Windows: باستخدام os.startfile(..., 'print')
        - Linux/macOS: محاولة عبر lpr
        """
        try:
            if not pdf_path or not os.path.exists(pdf_path):
                return False

            if sys.platform.startswith("win"):
                os.startfile(pdf_path, "print")
                return True

            subprocess.run(["lpr", pdf_path], check=True)
            return True

        except Exception:
            logger.exception("Failed to print PDF file: %s", pdf_path)
            return False

    def _show_sale_success_dialog(self, sale_id, actual_total, pdf_path=None, pdf_error=None):
        """
        السلوك الجديد:
        1) إذا وُلد PDF بنجاح -> افتحه تلقائياً أولاً
        2) ثم اسأل المستخدم هل يريد الطباعة الآن
        3) فشل الـ PDF لا يفسد البيع
        """
        main_text = (
            f"تم اعتماد الفاتورة رقم {sale_id} بنجاح.\n"
            f"الإجمالي المعتمد: {actual_total:,.2f}"
        )

        if not pdf_path:
            if pdf_error:
                QMessageBox.information(
                    self,
                    "نجاح البيع",
                    main_text + f"\n\nملاحظة: تمت عملية البيع بنجاح، لكن لم يتم توليد ملف PDF.\nالسبب:\n{pdf_error}"
                )
            else:
                QMessageBox.information(self, "نجاح البيع", main_text)
            return

        opened = self._open_pdf_file(pdf_path)

        if not opened:
            QMessageBox.information(
                self,
                "نجاح البيع",
                main_text + f"\n\nتم توليد ملف PDF بنجاح، لكن تعذر فتحه تلقائياً.\nالمسار:\n{pdf_path}"
            )
            return

        reply = QMessageBox.question(
            self,
            "طباعة الفاتورة",
            main_text + "\n\nتم فتح الفاتورة بنجاح.\nهل تريد إرسالها إلى الطباعة الآن؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            printed = self._print_pdf_file(pdf_path)
            if printed:
                QMessageBox.information(
                    self,
                    "تمت الإحالة للطباعة",
                    "تم إرسال الفاتورة إلى نظام الطباعة بنجاح."
                )
            else:
                QMessageBox.warning(
                    self,
                    "تعذر الطباعة",
                    f"تم فتح الفاتورة لكن تعذر إرسالها للطباعة مباشرة.\nيمكنك طباعتها يدوياً من عارض الـ PDF.\n\nالمسار:\n{pdf_path}"
                )

    # ==========================================
    # إتمام البيع مع الحماية السريرية
    # ==========================================
    def checkout(self):
        if not self.cart_lines:
            return

        self.refresh_session_context()
        current_shift_id = self._get_current_shift_id()

        if not self.user_id or not current_shift_id:
            QMessageBox.critical(self, "خطأ أمني", "بيانات المستخدم أو الوردية غير مكتملة.")
            return

        customer_id = self.customer_combo.itemData(self.customer_combo.currentIndex())
        doctor_name = self.doctor_input.text().strip()

        med_ids_for_check = [item['medicine_id'] for item in self.cart_lines]
        interactions = self.interactions_dao.check_cart_interactions(med_ids_for_check)

        has_contra = len(interactions.get('contraindicated', [])) > 0
        has_major = len(interactions.get('major', [])) > 0
        has_mod_min = len(interactions.get('moderate', [])) > 0 or len(interactions.get('minor', [])) > 0

        if has_contra or has_major or has_mod_min:
            msg = ""

            if has_contra:
                msg += "🚫 تداخلات ممنوعة:\n"
                for i in interactions['contraindicated']:
                    msg += f"- {i['medicine_1']} و {i['medicine_2']}: {i['description']}\n"
                QMessageBox.critical(self, "تداخل خطير (مرفوض)", msg)
                return

            if has_major:
                msg += "⚠️ تداخلات خطيرة:\n"
                for i in interactions['major']:
                    msg += f"- {i['medicine_1']} و {i['medicine_2']}: {i['description']}\n"

                if self.user_role not in ['admin', 'pharmacist']:
                    QMessageBox.critical(self, "تداخل خطير (مرفوض)", msg)
                    return
                else:
                    reply = QMessageBox.warning(
                        self,
                        "تنبيه تداخل عالي",
                        msg + "\nتجاوز؟",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        return

            elif has_mod_min:
                msg += "توجد تداخلات متوسطة/طفيفة. هل تريد المتابعة؟"
                reply = QMessageBox.information(
                    self,
                    "ملاحظة طبية",
                    msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

        has_controlled = any(item.get('is_controlled', 0) == 1 for item in self.cart_lines)
        controlled_data = None

        if has_controlled:
            dialog = ControlledDispensingDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                controlled_data = dialog.get_data()
            else:
                QMessageBox.warning(self, "إلغاء الصرف", "تم إلغاء البيع لعدم إكمال السجل الرقابي.")
                return

        expected_total = self.pricing_cache['net_total']

        success, result = self.dao.process_sale(
            user_id=self.user_id,
            shift_id=current_shift_id,
            customer_id=customer_id,
            doctor_name=doctor_name,
            ui_items=self.cart_lines,
            expected_net_total=expected_total,
            controlled_data=controlled_data
        )

        if success:
            sale_id = result.get("sale_id")
            actual_total = result.get("net_total")

            pdf_path, pdf_error = self._generate_pdf_for_sale(sale_id)

            self._show_sale_success_dialog(
                sale_id=sale_id,
                actual_total=actual_total,
                pdf_path=pdf_path,
                pdf_error=pdf_error
            )

            self.clear_cart()
        else:
            QMessageBox.critical(self, "فشل إتمام البيع", result)
            self.refresh_pricing_and_ui()