"""
وظيفة الملف: واجهة إدارة الورديات وتسوية العهد النقدية (Shifts Page).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Blind Count Policy]&#58; الواجهة لا تعرض الرصيد المتوقع للكاشير أبداً. تعتمد على الجرد الأعمى.
- [Strict Dumb Client]&#58; لا توجد أي حسابات للعمليات الحسابية (عجز/زيادة) داخل الواجهة. النواة تقرر كل شيء.
- [Contextual State Lock]&#58; الواجهة تعطل قسم الفتح إذا كانت هناك وردية مفتوحة، وتعطل قسم الإغلاق إذا لم تكن هناك وردية، وتحمي نفسها من الاستثناءات.
- [UI/Logic Decoupling]&#58; القرارات البرمجية في الجدول تعتمد على الحالة الخام (Qt.UserRole) وليس على النص المزخرف المعروض.
- [Dynamic UX-RBAC]&#58; يتغير اسم تبويب السجل بناءً على صلاحية المستخدم (إداري أم سجل شخصي).
- [Pointer Safety]&#58; حماية الواجهة من الانهيار (Crash) عند النقر المزدوج على خلايا فارغة أثناء التحديث.
- [Rich Report Rendering]&#58; استخدام QDialog مخصص مع QTextBrowser لضمان عرض التقارير المحاسبية (HTML) بدقة.
- [Live Session Sync]&#58; عند فتح/إغلاق الوردية يتم تحديث session["shift_id"] فوراً وإشعار MainWindow والصفحات النقدية.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QLabel, QFrame, QAbstractItemView,
    QTabWidget, QDialog, QTextBrowser
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
import logging

from models.shifts_dao import ShiftsDAO

logger = logging.getLogger(__name__)


class ShiftsPage(QWidget):
    session_updated = pyqtSignal(object)

    def __init__(self, session_data):
        super().__init__()
        # حماية الجلسة من الـ None
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")
        self.shift_id = self.session.get("shift_id")

        self.shifts_dao = ShiftsDAO()
        self.current_shift_id = None
        self._session_update_callback = None

        self.init_ui()
        self.refresh_ui_state()

    # ==========================================
    # Live Session Sync Hooks
    # ==========================================
    def set_session_update_callback(self, callback):
        self._session_update_callback = callback

    def refresh_session_context(self):
        """
        دالة توافقية يمكن لـ MainWindow استدعاؤها عند تغير session المشتركة.
        """
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", self.user_role)
        self.shift_id = self.session.get("shift_id")
        self.refresh_ui_state()

    def _broadcast_session_change(self, new_shift_id):
        """
        يبث تغير سياق الوردية إلى:
        1) الـ session المشتركة
        2) الإشارة Qt signal
        3) callback اختياري
        4) MainWindow مباشرة إن كانت الدوال موجودة
        """
        old_shift_id = self.session.get("shift_id")
        self.session["shift_id"] = new_shift_id
        self.shift_id = new_shift_id

        # إذا لم يتغير شيء فعلياً لا داعي لإعادة البث
        if old_shift_id == new_shift_id:
            return

        payload = {"shift_id": new_shift_id}

        try:
            self.session_updated.emit(payload)
        except Exception:
            logger.exception("فشل بث session_updated signal من ShiftsPage.")

        if callable(self._session_update_callback):
            try:
                self._session_update_callback(payload)
            except Exception:
                logger.exception("فشل استدعاء session update callback من ShiftsPage.")

        parent_window = self.window()
        if parent_window:
            if hasattr(parent_window, "notify_shift_context_changed"):
                try:
                    parent_window.notify_shift_context_changed(new_shift_id)
                    return
                except Exception:
                    logger.exception("فشل notify_shift_context_changed في MainWindow.")

            if hasattr(parent_window, "handle_session_update"):
                try:
                    parent_window.handle_session_update(payload)
                except Exception:
                    logger.exception("فشل handle_session_update في MainWindow.")

    # ==========================================
    # UI Construction
    # ==========================================
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title = QLabel("إدارة الورديات وتسوية الصندوق (Shift Management)")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';"
        )
        main_layout.addWidget(title)

        # ==========================================
        # استخدام نظام التبويبات لفصل التشغيل عن الإدارة
        # ==========================================
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        # 1. تبويب التشغيل (الفتح والإغلاق)
        self.tab_operation = QWidget()
        self.init_operation_tab()
        self.tabs.addTab(self.tab_operation, " 💼 إدارة الوردية الحالية")

        # 2. تبويب الإدارة والسجل [Dynamic UX-RBAC Fix]
        self.tab_history = QWidget()
        self.init_history_tab()

        history_tab_name = " 📊 السجل والتقارير الإدارية" if self.user_role == 'admin' else " 📊 سجل وردياتي"
        self.tabs.addTab(self.tab_history, history_tab_name)

        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def init_operation_tab(self):
        layout = QVBoxLayout(self.tab_operation)
        layout.setSpacing(20)

        # ------------------------------------------
        # قسم 1: فتح وردية جديدة
        # ------------------------------------------
        self.frame_open = QFrame()
        self.frame_open.setStyleSheet(
            "background-color: white; border-radius: 10px; border: 2px solid #27AE60; padding: 15px;"
        )
        layout_open = QVBoxLayout(self.frame_open)

        lbl_open_title = QLabel("🟢 فتح وردية مالية جديدة")
        lbl_open_title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #27AE60; border: none;"
        )
        layout_open.addWidget(lbl_open_title)

        row_open = QHBoxLayout()
        self.open_cash_input = QLineEdit()
        self.open_cash_input.setPlaceholderText("أدخل مبلغ العهدة الافتتاحية...")
        self.open_cash_input.setStyleSheet(
            "font-size: 18px; padding: 8px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )

        self.open_notes_input = QLineEdit()
        self.open_notes_input.setPlaceholderText("ملاحظات الفتح (اختياري)...")
        self.open_notes_input.setStyleSheet(
            "font-size: 16px; padding: 8px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )

        self.btn_open_shift = QPushButton(" فتح الوردية واستلام الصندوق")
        self.btn_open_shift.setFixedHeight(45)
        self.btn_open_shift.setCursor(Qt.PointingHandCursor)
        self.btn_open_shift.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;"
        )
        self.btn_open_shift.clicked.connect(self.handle_open_shift)

        row_open.addWidget(QLabel("العهدة الافتتاحية:"), stretch=1)
        row_open.addWidget(self.open_cash_input, stretch=2)
        row_open.addWidget(QLabel("ملاحظات:"), stretch=1)
        row_open.addWidget(self.open_notes_input, stretch=3)
        row_open.addWidget(self.btn_open_shift, stretch=2)

        layout_open.addLayout(row_open)
        layout.addWidget(self.frame_open)

        # ------------------------------------------
        # قسم 2: إغلاق الوردية الحالية (Blind Close)
        # ------------------------------------------
        self.frame_close = QFrame()
        self.frame_close.setStyleSheet(
            "background-color: white; border-radius: 10px; border: 2px solid #C0392B; padding: 15px;"
        )
        layout_close = QVBoxLayout(self.frame_close)

        lbl_close_title = QLabel("🔴 إغلاق الوردية الحالية (جرد أعمى)")
        lbl_close_title.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #C0392B; border: none;"
        )
        layout_close.addWidget(lbl_close_title)

        self.lbl_current_shift_info = QLabel("لا توجد بيانات...")
        self.lbl_current_shift_info.setStyleSheet(
            "font-size: 16px; color: #7F8C8D; border: none; font-weight: bold;"
        )
        layout_close.addWidget(self.lbl_current_shift_info)

        row_close_1 = QHBoxLayout()
        self.actual_cash_input = QLineEdit()
        self.actual_cash_input.setPlaceholderText("أدخل النقد الفعلي الموجود في الدرج...")
        self.actual_cash_input.setStyleSheet(
            "font-size: 18px; padding: 8px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )

        self.drop_cash_input = QLineEdit()
        self.drop_cash_input.setPlaceholderText("المبلغ المورد للخزينة...")
        self.drop_cash_input.setStyleSheet(
            "font-size: 18px; padding: 8px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )
        self.drop_cash_input.setText("0")

        row_close_1.addWidget(QLabel("النقد الفعلي (الجرد):"), stretch=1)
        row_close_1.addWidget(self.actual_cash_input, stretch=2)
        row_close_1.addWidget(QLabel("مبلغ التوريد:"), stretch=1)
        row_close_1.addWidget(self.drop_cash_input, stretch=2)

        layout_close.addLayout(row_close_1)

        row_close_2 = QHBoxLayout()
        self.close_notes_input = QLineEdit()
        self.close_notes_input.setPlaceholderText("مبرر العجز/الزيادة (إلزامي في حال وجود فارق)...")
        self.close_notes_input.setStyleSheet(
            "font-size: 16px; padding: 8px; border: 1px solid #BDC3C7; border-radius: 5px;"
        )

        self.btn_close_shift = QPushButton(" إغلاق الوردية وتسوية الصندوق")
        self.btn_close_shift.setFixedHeight(45)
        self.btn_close_shift.setCursor(Qt.PointingHandCursor)
        self.btn_close_shift.setStyleSheet(
            "background-color: #C0392B; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;"
        )
        self.btn_close_shift.clicked.connect(self.handle_close_shift)

        row_close_2.addWidget(QLabel("المبرر/الملاحظات:"), stretch=1)
        row_close_2.addWidget(self.close_notes_input, stretch=4)
        row_close_2.addWidget(self.btn_close_shift, stretch=2)

        layout_close.addLayout(row_close_2)
        layout.addWidget(self.frame_close)

        layout.addStretch()

    def init_history_tab(self):
        layout = QVBoxLayout(self.tab_history)

        header_layout = QHBoxLayout()
        lbl_info = QLabel("انقر نقراً مزدوجاً على أي وردية مغلقة لعرض تقرير الإغلاق المفصل.")
        lbl_info.setStyleSheet("color: #7F8C8D; font-style: italic;")

        btn_refresh = QPushButton(" تحديث السجل")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.load_history_data)
        btn_refresh.setStyleSheet("font-size: 14px; padding: 5px 15px;")

        header_layout.addWidget(lbl_info)
        header_layout.addStretch()
        header_layout.addWidget(btn_refresh)

        layout.addLayout(header_layout)

        self.history_table = QTableWidget()
        headers = [
            "رقم الوردية", "المستخدم", "العهدة الافتتاحية", "المتوقع لحظة الإغلاق",
            "الفعلي (الجرد)", "الفارق", "الحالة", "وقت الفتح", "وقت الإغلاق"
        ]
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setLayoutDirection(Qt.RightToLeft)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet("font-size: 14px;")

        self.history_table.cellDoubleClicked.connect(self.show_shift_details_from_table)

        layout.addWidget(self.history_table)

    # ==========================================
    # State Management (Context Lock)
    # ==========================================
    def refresh_ui_state(self):
        """
        [Context Lock & Error Net]: قفل وتفعيل الأقسام بناءً على حالة المستخدم في النواة.
        تجميد الشاشة بالكامل ومسح السجلات في حال غياب الجلسة لحماية البيانات.
        """
        if not self.user_id:
            self.frame_open.setEnabled(False)
            self.frame_close.setEnabled(False)
            self.history_table.setRowCount(0)
            self.tabs.setTabEnabled(1, False)
            return
        else:
            self.tabs.setTabEnabled(1, True)

        try:
            open_shift = self.shifts_dao.get_open_shift(self.user_id)

            if open_shift:
                self.current_shift_id = open_shift["shift_id"]

                self.open_cash_input.clear()
                self.open_notes_input.clear()
                self.actual_cash_input.clear()
                self.drop_cash_input.setText("0")
                self.close_notes_input.clear()

                self.frame_open.setEnabled(False)
                self.frame_close.setEnabled(True)

                opened_at = open_shift["opened_at"]
                op_cash = open_shift["opening_cash"]

                self.lbl_current_shift_info.setText(
                    f"رقم الوردية: {self.current_shift_id} | وقت الفتح: {opened_at} | العهدة المستلمة: {op_cash:,.2f}"
                )
                self.actual_cash_input.setFocus()

                self._broadcast_session_change(self.current_shift_id)

            else:
                self.current_shift_id = None

                self.actual_cash_input.clear()
                self.drop_cash_input.clear()
                self.close_notes_input.clear()
                self.open_cash_input.clear()

                self.frame_open.setEnabled(True)
                self.frame_close.setEnabled(False)

                self.lbl_current_shift_info.setText("لا توجد وردية مفتوحة. يرجى فتح وردية أولاً.")
                self.open_cash_input.setFocus()

                self._broadcast_session_change(None)

        except RuntimeError as e:
            QMessageBox.critical(self, "خطأ حرج", str(e))
            self.frame_open.setEnabled(False)
            self.frame_close.setEnabled(False)

        except Exception:
            logger.exception("Unexpected UI state refresh error:")
            QMessageBox.critical(self, "خطأ", "حدث خطأ غير متوقع أثناء تحديث حالة الوردية.")
            self.frame_open.setEnabled(False)
            self.frame_close.setEnabled(False)

        self.load_history_data()

    # ==========================================
    # Actions (Dumb Client Delegation)
    # ==========================================
    def handle_open_shift(self):
        opening_cash_str = self.open_cash_input.text().strip()
        if not opening_cash_str:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال مبلغ العهدة الافتتاحية.")
            return

        notes = self.open_notes_input.text().strip()

        success, result = self.shifts_dao.open_shift(self.user_id, opening_cash_str, notes)
        if success:
            QMessageBox.information(self, "نجاح", result["message"])
            self.refresh_ui_state()
        else:
            QMessageBox.critical(self, "رفض سيادي", result)

    def handle_close_shift(self):
        actual_cash_str = self.actual_cash_input.text().strip()
        drop_cash_str = self.drop_cash_input.text().strip()
        notes = self.close_notes_input.text().strip()

        if not actual_cash_str:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال النقد الفعلي (الجرد الأعمى).")
            self.actual_cash_input.setFocus()
            return

        if not drop_cash_str:
            drop_cash_str = "0"

        confirm = QMessageBox.question(
            self,
            "تأكيد الإغلاق والتسوية",
            "هل أنت متأكد من إغلاق الوردية؟\nسيتم احتساب الفروقات وتوليد قيود التسوية آلياً، ولن تتمكن من تعديل هذه الوردية لاحقاً.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        success, result = self.shifts_dao.close_shift(self.user_id, actual_cash_str, drop_cash_str, notes)

        if success:
            self.show_summary_dialog(result["summary"], is_new_close=True)
            self.refresh_ui_state()
        else:
            QMessageBox.critical(self, "فشل الإغلاق", result)

    # ==========================================
    # History & Reporting
    # ==========================================
    def load_history_data(self):
        """
        [Data Leak Prevention Guard]: إفراغ الجدول ورفض الجلب إذا كانت الجلسة مفقودة للمستخدم العادي.
        """
        if not self.user_id and self.user_role != 'admin':
            self.history_table.setRowCount(0)
            return

        target_user = None if self.user_role == 'admin' else self.user_id

        shifts = self.shifts_dao.get_all_shifts(user_id=target_user)
        self.history_table.setRowCount(0)

        for row_idx, s in enumerate(shifts):
            self.history_table.insertRow(row_idx)

            is_open = s['status'] == 'open'
            status_str = "مفتوحة 🟢" if is_open else "مغلقة 🔴"

            items_text = [
                str(s['shift_id']),
                s['username'],
                f"{s['opening_cash']:,.2f}",
                f"{s['expected_cash']:,.2f}" if not is_open else "-",
                f"{s['actual_cash']:,.2f}" if not is_open else "-",
                f"{s['variance']:,.2f}" if not is_open else "-",
                status_str,
                s['opened_at'],
                s['closed_at'] or "-"
            ]

            for col_idx, text in enumerate(items_text):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)

                if col_idx == 6:
                    item.setData(Qt.UserRole, s['status'])

                if is_open:
                    item.setForeground(QColor("#27AE60"))
                else:
                    item.setForeground(QColor("#7F8C8D"))

                self.history_table.setItem(row_idx, col_idx, item)

    def show_shift_details_from_table(self, row, column):
        """[Pointer Safety]: حماية الواجهة من الانهيار عند محاولة قراءة خلية فارغة أثناء التحديث"""
        id_item = self.history_table.item(row, 0)
        status_item = self.history_table.item(row, 6)

        if not id_item or not status_item:
            QMessageBox.warning(self, "خطأ", "تعذر قراءة بيانات الصف المحدد.")
            return

        shift_id_str = id_item.text()
        raw_status = status_item.data(Qt.UserRole)

        if raw_status == 'open':
            QMessageBox.information(self, "معلومة", "الوردية ما زالت مفتوحة. لا يوجد تقرير إغلاق بعد.")
            return

        shift_id = int(shift_id_str)
        summary = self.shifts_dao.get_shift_summary(shift_id)
        if summary:
            self.show_summary_dialog(summary, is_new_close=False)
        else:
            QMessageBox.warning(self, "خطأ", "تعذر جلب تفاصيل الوردية.")

    def show_summary_dialog(self, summary_data, is_new_close=False):
        """[Rich Report Rendering]: استخدام QDialog مخصص مع QTextBrowser لضمان دقة عرض الجداول المحاسبية."""
        title = "نجاح الإغلاق - تقرير الوردية" if is_new_close else f"تقرير وردية مغلقة (رقم {summary_data['shift_id']})"

        var_color = "green" if summary_data['variance'] >= 0 else "red"
        var_text = "زيادة نقدية" if summary_data['variance'] > 0 else ("عجز نقدي" if summary_data['variance'] < 0 else "تطابق تام")

        html_content = f"""
        <div style="font-family: 'Times New Roman', sans-serif; font-size: 16px;">
            <h2 style='color: #2C3E50; text-align: center;'>ملخص التسوية النقدية للوردية</h2>
            <hr>
            <table width='100%' cellpadding='8' style='border-collapse: collapse;'>
                <tr><td width='50%'><b>رقم الوردية:</b></td> <td>{summary_data['shift_id']}</td></tr>
                <tr><td><b>المستخدم:</b></td> <td>{summary_data['username']}</td></tr>
                <tr><td><b>وقت الفتح:</b></td> <td>{summary_data['opened_at']}</td></tr>
                <tr><td><b>وقت الإغلاق:</b></td> <td>{summary_data['closed_at']}</td></tr>
                <tr style='background-color: #ECF0F1; border-top: 1px solid #BDC3C7;'>
                    <td><b>العهدة الافتتاحية:</b></td> <td>{summary_data['opening_cash']:,.2f}</td>
                </tr>
                <tr style='background-color: #ECF0F1;'>
                    <td><b>الرصيد النظري (المتوقع):</b></td> <td>{summary_data['expected_cash']:,.2f}</td>
                </tr>
                <tr style='background-color: #D6EAF8; border-top: 2px solid #3498DB;'>
                    <td><b>الجرد الفعلي (المدخل):</b></td> <td><b>{summary_data['actual_cash']:,.2f}</b></td>
                </tr>
                <tr>
                    <td><b>الفارق (<span style='color:{var_color};'>{var_text}</span>):</b></td>
                    <td><b style='color:{var_color}; font-size: 18px;'>{summary_data['variance']:,.2f}</b></td>
                </tr>
                <tr style='background-color: #FADBD8; border-top: 1px solid #BDC3C7;'>
                    <td><b>المبلغ المورد للخزينة:</b></td> <td>{summary_data['cash_drop_amount']:,.2f}</td>
                </tr>
                <tr style='background-color: #FDEBD0;'>
                    <td><b>الرصيد المتبقي بالدرج:</b></td> <td>{summary_data['remaining_cash_after_drop']:,.2f}</td>
                </tr>
            </table>
            <hr>
            <p><b>ملاحظات الفتح:</b> {summary_data['opening_notes']}</p>
            <p><b>مبررات الإغلاق/الفارق:</b> {summary_data['closing_notes']}</p>
        </div>
        """

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(550, 650)

        layout = QVBoxLayout(dialog)

        browser = QTextBrowser()
        browser.setHtml(html_content)
        browser.setStyleSheet("background-color: white; border: 1px solid #BDC3C7; border-radius: 5px;")
        layout.addWidget(browser)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("إغلاق التقرير")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "background-color: #34495E; color: white; font-weight: bold; font-size: 16px; padding: 10px 30px; border-radius: 5px;"
        )
        btn_close.clicked.connect(dialog.accept)

        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)
        dialog.exec_()