"""
وظيفة الملف: واجهة الإقفال اليومي والتقارير المالية المجمعة (Daily Closures Page).
الطبقة: Presentation Layer
ملاحظة معمارية وأمنية:
- [Strict Admin RBAC]: الواجهة تُقفل تماماً وتُمنع من العرض لغير مديري النظام (Admin).
- [State Machine UI]: الشاشة تتغير ديناميكياً بناءً على نتيجة (preview_daily_closure).
- [Preview for Guidance, Create for Truth]: الواجهة لا تثق بالمعاينة كحقيقة نهائية. عند الاعتماد، تتوقع رفض النواة وتتعامل معه.
- [Strong UI Referencing]: تجنب البحث الهش في شجرة العناصر عبر الاعتماد على مراجع صريحة (value_label) للبطاقات.
- [State Hygiene]: تنظيف شامل لحالة الواجهة (Inputs, Tables, Cards) بعد نجاح الإقفال لمنع تسرب البيانات القديمة.
- [Safety Nets]: حماية دوال العرض والتقارير بشبكات أمان (Try/Except) لمنع انهيار أو تجمد النظام.
- [Dumb Dashboard]: لا تقوم بأي عمليات جمع أو طرح. تعرض المخرجات المكمّمة (Quantized) القادمة من الـ DAO فقط.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
                             QMessageBox, QLabel, QFrame, QSplitter, QAbstractItemView,
                             QTabWidget, QDateEdit, QStackedWidget, QDialog, QTextBrowser, QGridLayout)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont, QColor
import logging

from models.daily_closures_dao import DailyClosuresDAO

logger = logging.getLogger(__name__)

class DailyClosuresPage(QWidget):
    def __init__(self, session_data):
        super().__init__()
        self.session = session_data or {}
        self.user_id = self.session.get("user_id")
        self.user_role = self.session.get("role", "pharmacist")

        self.dao = DailyClosuresDAO()

        self.init_ui()

        # [Strict Admin RBAC Guard]: إغلاق الشاشة فوراً لغير المديرين
        if self.user_role != 'admin':
            self.lock_screen_for_non_admins()
        else:
            self.load_history_data()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        title = QLabel("الإقفال اليومي والرقابة المالية (Daily Financial Closure)")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2C3E50; font-family: 'Times New Roman';")
        self.main_layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("font-size: 16px; font-family: 'Times New Roman';")

        self.tab_action = QWidget()
        self.init_action_tab()
        self.tabs.addTab(self.tab_action, " 🔒 تنفيذ الإقفال اليومي")

        self.tab_history = QWidget()
        self.init_history_tab()
        self.tabs.addTab(self.tab_history, " 📚 سجل الإقفالات والتقارير")

        self.main_layout.addWidget(self.tabs)

    def init_action_tab(self):
        layout = QVBoxLayout(self.tab_action)
        layout.setSpacing(20)

        # --- 1. شريط اختيار التاريخ والمعاينة ---
        control_frame = QFrame()
        control_frame.setStyleSheet("background-color: white; border-radius: 10px; border: 1px solid #BDC3C7; padding: 10px;")
        control_layout = QHBoxLayout(control_frame)

        lbl_date = QLabel("اليوم التشغيلي المراد إقفاله:")
        lbl_date.setStyleSheet("font-weight: bold; border: none;")

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setStyleSheet("font-size: 18px; padding: 5px;")

        self.btn_preview = QPushButton(" 🔍 فحص الجاهزية والمعاينة")
        self.btn_preview.setCursor(Qt.PointingHandCursor)
        self.btn_preview.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold; font-size: 16px; padding: 10px 20px; border-radius: 5px;")
        self.btn_preview.clicked.connect(self.handle_preview)

        control_layout.addWidget(lbl_date)
        control_layout.addWidget(self.date_input)
        control_layout.addWidget(self.btn_preview)
        control_layout.addStretch()
        layout.addWidget(control_frame)

        # --- 2. المكدس الديناميكي للحالات (State Machine UI) ---
        self.state_stack = QStackedWidget()

        # State 0: Initial / Empty
        self.page_initial = QLabel("يرجى اختيار التاريخ والضغط على 'فحص الجاهزية' لعرض ملخص الإقفال أو المشاكل العالقة.")
        self.page_initial.setAlignment(Qt.AlignCenter)
        self.page_initial.setStyleSheet("font-size: 18px; color: #7F8C8D; font-style: italic;")
        self.state_stack.addWidget(self.page_initial)

        # State 1: Blocked (Open Shifts)
        self.page_blocked = QWidget()
        blocked_layout = QVBoxLayout(self.page_blocked)
        lbl_blocked = QLabel("⚠️ لا يمكن إقفال هذا اليوم. توجد ورديات ما تزال مفتوحة تمنع التسوية النهائية:")
        lbl_blocked.setStyleSheet("font-size: 18px; font-weight: bold; color: #C0392B;")
        blocked_layout.addWidget(lbl_blocked)

        self.blocking_table = QTableWidget()
        self.blocking_table.setColumnCount(3)
        self.blocking_table.setHorizontalHeaderLabels(["رقم الوردية", "الموظف", "وقت الفتح"])
        self.blocking_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.blocking_table.setStyleSheet("background-color: #FDEDEC; border: 1px solid #E74C3C;")
        blocked_layout.addWidget(self.blocking_table)
        self.state_stack.addWidget(self.page_blocked)

        # State 2: Ready for Closure
        self.page_ready = QWidget()
        ready_layout = QVBoxLayout(self.page_ready)

        lbl_ready = QLabel("✅ اليوم جاهز للإقفال. يرجى مراجعة المجاميع الآتية:")
        lbl_ready.setStyleSheet("font-size: 18px; font-weight: bold; color: #27AE60;")
        ready_layout.addWidget(lbl_ready)

        # Dashboard Cards
        grid = QGridLayout()
        grid.setSpacing(15)

        self.lbl_shifts_count = self._create_dashboard_card("عدد الورديات المشمولة", "0", "#34495E")
        self.lbl_total_opening = self._create_dashboard_card("إجمالي العهد الافتتاحية", "0.00", "#2980B9")
        self.lbl_total_expected = self._create_dashboard_card("إجمالي المتوقع (النظري)", "0.00", "#8E44AD")
        self.lbl_total_actual = self._create_dashboard_card("إجمالي الجرد الفعلي", "0.00", "#D35400")
        self.lbl_total_variance = self._create_dashboard_card("صافي الفروقات (عجز/زيادة)", "0.00", "#C0392B")
        self.lbl_total_drops = self._create_dashboard_card("إجمالي المورد للخزينة", "0.00", "#27AE60")

        grid.addWidget(self.lbl_shifts_count, 0, 0)
        grid.addWidget(self.lbl_total_opening, 0, 1)
        grid.addWidget(self.lbl_total_expected, 0, 2)
        grid.addWidget(self.lbl_total_actual, 1, 0)
        grid.addWidget(self.lbl_total_variance, 1, 1)
        grid.addWidget(self.lbl_total_drops, 1, 2)

        ready_layout.addLayout(grid)

        # التنفيذ
        exec_layout = QHBoxLayout()
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("ملاحظات إدارية على هذا الإقفال (اختياري)...")
        self.notes_input.setStyleSheet("font-size: 16px; padding: 10px; border: 1px solid #BDC3C7; border-radius: 5px;")

        self.btn_commit = QPushButton(" 🔐 اعتماد الإقفال اليومي نهائياً")
        self.btn_commit.setCursor(Qt.PointingHandCursor)
        self.btn_commit.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; font-size: 18px; padding: 10px 30px; border-radius: 5px;")
        self.btn_commit.clicked.connect(self.handle_commit)

        exec_layout.addWidget(self.notes_input, stretch=3)
        exec_layout.addWidget(self.btn_commit, stretch=1)

        ready_layout.addLayout(exec_layout)
        ready_layout.addStretch()
        self.state_stack.addWidget(self.page_ready)

        layout.addWidget(self.state_stack)

    def _create_dashboard_card(self, title, value, color):
        """Helper to create nice looking summary cards with Strong Referencing."""
        card = QFrame()
        card.setStyleSheet(f"background-color: white; border: 2px solid {color}; border-radius: 8px;")
        vbox = QVBoxLayout(card)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 14px; color: #7F8C8D; border: none;")
        lbl_title.setAlignment(Qt.AlignCenter)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color}; border: none;")
        lbl_val.setAlignment(Qt.AlignCenter)

        vbox.addWidget(lbl_title)
        vbox.addWidget(lbl_val)

        # [Architectural Fix 1]: حفظ المرجع بشكل صريح لمنع هشاشة findChildren
        card.value_label = lbl_val
        return card

    def _update_card(self, card_widget, text):
        """Update using the explicit strong reference."""
        card_widget.value_label.setText(text)

    def _reset_dashboard_cards(self):
        """[State Hygiene]: إعادة تعيين بطاقات لوحة القيادة لقيمها الافتراضية."""
        self._update_card(self.lbl_shifts_count, "0")
        self._update_card(self.lbl_total_opening, "0.00")
        self._update_card(self.lbl_total_expected, "0.00")
        self._update_card(self.lbl_total_actual, "0.00")
        self._update_card(self.lbl_total_variance, "0.00")
        self._update_card(self.lbl_total_drops, "0.00")

    def init_history_tab(self):
        layout = QVBoxLayout(self.tab_history)

        header_layout = QHBoxLayout()
        lbl_info = QLabel("انقر نقراً مزدوجاً على أي يوم مقفل لعرض التقرير المالي الشامل.")
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
        headers = ["رقم الإقفال", "اليوم التشغيلي", "عدد الورديات", "إجمالي الجرد",
                   "إجمالي الفروقات", "إجمالي المورد", "اعتمد بواسطة", "تاريخ الاعتماد"]
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setLayoutDirection(Qt.RightToLeft)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.setStyleSheet("font-size: 14px;")

        self.history_table.cellDoubleClicked.connect(self.show_closure_details)
        layout.addWidget(self.history_table)

    def lock_screen_for_non_admins(self):
        """[Security Guard]: تعتيم الواجهة بالكامل إذا لم يكن المستخدم مديراً."""
        self.tabs.setEnabled(False)
        msg = QLabel("⛔ عذراً، لا تملك الصلاحيات الكافية للوصول إلى هذه الشاشة.\nالإقفال اليومي مقتصر على مديري النظام فقط.")
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("font-size: 20px; font-weight: bold; color: #C0392B; margin-top: 50px;")
        self.main_layout.addWidget(msg)

    # ==========================================
    # Logic - Actions (Dumb Client Delegation)
    # ==========================================
    def handle_preview(self):
        """طلب المعاينة من النواة وتوجيه الشاشة بناءً على الرد الهيكلي."""
        if not self.user_id: return

        date_str = self.date_input.date().toString("yyyy-MM-dd")
        self.notes_input.clear()

        success, result = self.dao.preview_daily_closure(self.user_id, date_str)

        if success:
            # State 2: Ready
            self._update_card(self.lbl_shifts_count, str(result["total_shifts_count"]))
            self._update_card(self.lbl_total_opening, f"{result['total_opening_cash']:,.2f}")
            self._update_card(self.lbl_total_expected, f"{result['total_expected_cash']:,.2f}")
            self._update_card(self.lbl_total_actual, f"{result['total_actual_cash']:,.2f}")

            var_val = result['total_variance']
            var_str = f"{var_val:,.2f}"
            if var_val < 0: var_str = f"عجز: {var_str}"
            elif var_val > 0: var_str = f"زيادة: {var_str}"
            self._update_card(self.lbl_total_variance, var_str)

            self._update_card(self.lbl_total_drops, f"{result['total_cash_drops']:,.2f}")

            self.state_stack.setCurrentIndex(2)
            self.notes_input.setFocus()

        else:
            # Handle Structured Rejection
            err_type = result.get("type")
            if err_type == "blocking_shifts":
                # State 1: Blocked
                shifts = result.get("blocking_open_shifts", [])
                self.blocking_table.setRowCount(0)
                for i, s in enumerate(shifts):
                    self.blocking_table.insertRow(i)
                    self.blocking_table.setItem(i, 0, QTableWidgetItem(str(s["shift_id"])))
                    self.blocking_table.setItem(i, 1, QTableWidgetItem(s["username"]))
                    self.blocking_table.setItem(i, 2, QTableWidgetItem(s["opened_at"]))
                self.state_stack.setCurrentIndex(1)
            else:
                # State 0: General Error
                QMessageBox.warning(self, "تعذر المعاينة", result.get("message", "خطأ غير معروف."))
                self.state_stack.setCurrentIndex(0)

    def handle_commit(self):
        """
        [Create for Truth]: يرسل طلب الاعتماد النهائي.
        إذا فشل، يُعلم الواجهة بأن حالة النظام تغيرت، ويجبر المستخدم على إعادة المعاينة.
        """
        date_str = self.date_input.date().toString("yyyy-MM-dd")
        notes = self.notes_input.text().strip()

        confirm = QMessageBox.warning(
            self, "اعتماد نهائي لا رجعة فيه",
            f"هل أنت متأكد من اعتماد الإقفال اليومي لتاريخ ({date_str})؟\n\n"
            "تنبيه: بمجرد الاعتماد سيتم تفعيل حراس الحماية، ولن يمكن إبطال أي مرتجع أو مصروف تابع لهذا اليوم أبداً.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes: return

        # التنفيذ السيادي
        success, result = self.dao.create_daily_closure(self.user_id, date_str, notes)

        if success:
            QMessageBox.information(self, "نجاح الإقفال", result["message"])
            # [Architectural Fix 2]: State Hygiene التنظيف الشامل للحالة بعد النجاح
            self.notes_input.clear()
            self.blocking_table.setRowCount(0)
            self._reset_dashboard_cards()
            self.state_stack.setCurrentIndex(0)
            self.load_history_data()
        else:
            # النواة رفضت الاعتماد (ربما حدث TOCTOU وتم منعه، أو فتحت وردية جديدة)
            QMessageBox.critical(self, "تم حظر الاعتماد", f"تم رفض عملية الإقفال:\n{result}")
            # [Self-Healing UI]: إجبار الواجهة على تحديث الواقع لمنع المستخدم من الاعتماد على معاينة قديمة
            self.handle_preview()

    # ==========================================
    # Logic - History & Reporting
    # ==========================================
    def load_history_data(self):
        """[Safety Net]: حماية تحميل السجل من أي استثناءات داخلية."""
        if self.user_role != 'admin':
            self.history_table.setRowCount(0)
            return

        try:
            closures = self.dao.get_all_daily_closures(self.user_id)
            self.history_table.setRowCount(0)

            for row_idx, c in enumerate(closures):
                self.history_table.insertRow(row_idx)

                items = [
                    str(c['closure_id']),
                    c['business_date'],
                    str(c['total_shifts_count']),
                    f"{c['total_actual_cash']:,.2f}",
                    f"{c['total_variance']:,.2f}",
                    f"{c['total_cash_drops']:,.2f}",
                    c['closed_by'],
                    c['created_at']
                ]

                for col_idx, text in enumerate(items):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.history_table.setItem(row_idx, col_idx, item)

        except Exception as e:
            logger.exception("Daily closures history load failed:")
            self.history_table.setRowCount(0)
            QMessageBox.critical(self, "خطأ", "حدث خطأ غير متوقع أثناء تحميل سجل الإقفالات.")

    def show_closure_details(self, row, column):
        """[Safety Net & Pointer Safety]: حماية الواجهة من الانهيار عند قراءة خلية أو جلب التقرير."""
        try:
            id_item = self.history_table.item(row, 0)
            if not id_item: return

            closure_id = int(id_item.text())
            summary = self.dao.get_daily_closure_summary(self.user_id, closure_id)

            if not summary:
                QMessageBox.warning(self, "خطأ", "تعذر جلب تفاصيل الإقفال المحدد.")
                return

            self._render_rich_report_dialog(summary)

        except Exception as e:
            logger.exception("Daily closures detail view failed:")
            QMessageBox.critical(self, "خطأ", "حدث خطأ غير متوقع أثناء عرض تفاصيل الإقفال.")

    def _render_rich_report_dialog(self, summary):
        """[Rich Report Rendering]: استخدام QDialog لعرض HTML معقد يعرض الرأس والتفاصيل."""
        header = summary["header"]
        shifts = summary["shifts"]

        title = f"تقرير الإقفال اليومي - تاريخ {header['business_date']}"

        var_color = "green" if header['total_variance'] >= 0 else "red"

        # بناء رأس التقرير
        html = f"""
        <div style="font-family: 'Times New Roman', sans-serif; font-size: 16px;">
            <h2 style='color: #2C3E50; text-align: center; margin-bottom: 5px;'>تقرير الإقفال المالي المجمع</h2>
            <h4 style='color: #7F8C8D; text-align: center; margin-top: 0;'>تاريخ العمليات: {header['business_date']} | رقم الإقفال: {header['closure_id']}</h4>
            <hr>
            
            <table width='100%' cellpadding='8' style='border-collapse: collapse; margin-bottom: 20px;'>
                <tr>
                    <td width='50%'><b>اعتمد بواسطة:</b> {header['closed_by']}</td>
                    <td><b>وقت الاعتماد:</b> {header['created_at']}</td>
                </tr>
                <tr style='background-color: #ECF0F1;'>
                    <td><b>عدد الورديات المشمولة:</b> {header['total_shifts_count']}</td>
                    <td><b>إجمالي العهد الافتتاحية:</b> {header['total_opening_cash']:,.2f}</td>
                </tr>
                <tr>
                    <td><b>إجمالي الرصيد النظري:</b> {header['total_expected_cash']:,.2f}</td>
                    <td><b>إجمالي الجرد الفعلي:</b> <b style='color:#2980B9;'>{header['total_actual_cash']:,.2f}</b></td>
                </tr>
                <tr style='background-color: #FADBD8;'>
                    <td><b>صافي الفروقات (عجز/زيادة):</b> <b style='color:{var_color};'>{header['total_variance']:,.2f}</b></td>
                    <td><b>إجمالي المورد للخزينة:</b> <b style='color:#27AE60;'>{header['total_cash_drops']:,.2f}</b></td>
                </tr>
            </table>
            
            <h3 style='color: #2C3E50; border-bottom: 2px solid #3498DB; padding-bottom: 5px;'>تفاصيل الورديات (Lines)</h3>
            <table width='100%' cellpadding='6' border='1' style='border-collapse: collapse; border-color: #BDC3C7;'>
                <tr style='background-color: #34495E; color: white;'>
                    <th>رقم</th>
                    <th>الموظف</th>
                    <th>الفعلي</th>
                    <th>الفارق</th>
                    <th>وقت الفتح</th>
                    <th>وقت الإغلاق</th>
                </tr>
        """

        # بناء أسطر الورديات
        for s in shifts:
            s_var_color = "green" if s['variance'] >= 0 else "red"
            html += f"""
                <tr style='text-align: center;'>
                    <td>{s['shift_id']}</td>
                    <td>{s['username']}</td>
                    <td>{s['actual_cash']:,.2f}</td>
                    <td style='color:{s_var_color}; font-weight:bold;'>{s['variance']:,.2f}</td>
                    <td style='font-size:12px;'>{s['opened_at']}</td>
                    <td style='font-size:12px;'>{s['closed_at']}</td>
                </tr>
            """

        html += f"""
            </table>
            <div style='margin-top: 20px; padding: 10px; background-color: #F9E79F; border-radius: 5px;'>
                <b>ملاحظات إدارية:</b> {header['notes']}
            </div>
        </div>
        """

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(750, 700)

        layout = QVBoxLayout(dialog)

        browser = QTextBrowser()
        browser.setHtml(html)
        browser.setStyleSheet("background-color: white; border: 1px solid #BDC3C7; border-radius: 5px;")
        layout.addWidget(browser)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("إغلاق التقرير")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("background-color: #34495E; color: white; font-weight: bold; font-size: 16px; padding: 10px 30px; border-radius: 5px;")
        btn_close.clicked.connect(dialog.accept)
        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)
        dialog.exec_()