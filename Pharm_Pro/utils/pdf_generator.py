from fpdf import FPDF
import os
from datetime import datetime


def create_invoice_pdf(items, total_amount, invoice_id=None, cashier_name="Admin", date=None):
    """
    توليد ملف PDF للفاتورة.
    يمكن استخدامها لنقطة البيع (بدون ID في البداية) أو للتقارير (مع ID وتاريخ محدد).
    """

    # التأكد من وجود مجلد الفواتير
    if not os.path.exists("invoices"):
        os.makedirs("invoices")

    # إعداد البيانات الافتراضية إذا لم ترسل
    if invoice_id is None:
        invoice_id = datetime.now().strftime("%Y%m%d%H%M%S")  # رقم مؤقت بناء على الوقت

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # تحويل total_amount إلى نص إذا كان رقماً
    if isinstance(total_amount, (float, int)):
        total_str = f"{total_amount:.2f}"
    else:
        total_str = str(total_amount).replace("الإجمالي: ", "").strip()

    file_name = f"invoices/invoice_{invoice_id}.pdf"

    # إعداد ملف PDF
    pdf = FPDF()
    pdf.add_page()

    # 1. العنوان (Header)
    pdf.set_font("helvetica", "B", 20)
    pdf.cell(0, 15, "PHARMACY INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "", 12)
    pdf.cell(0, 8, f"Invoice #: {invoice_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Date: {date}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Cashier: {cashier_name}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)  # مسافة فارغة

    # 2. ترويسة الجدول
    col_widths = [80, 30, 40, 40]  # عرض الأعمدة

    pdf.set_font("helvetica", "B", 12)
    pdf.set_fill_color(220, 220, 220)  # لون رمادي للخلفية

    headers = ["Item Name", "Qty", "Price", "Total"]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, align="C", fill=True)
    pdf.ln()

    # 3. بيانات الجدول
    pdf.set_font("helvetica", "", 11)

    for item in items:
        # التعامل مع اختلاف هيكلية البيانات بين POS (قاموس) و Reports (قائمة)
        if isinstance(item, dict):
            # قادمة من POSPage
            name = str(item['name'])
            qty = str(item['quantity'])
            price = f"{item['price']:.2f}"
            total_item = f"{item['total']:.2f}"
        else:
            # قادمة من ReportsPage (tuple/list)
            # الترتيب المتوقع من الاستعلام: Name, Qty, Price, Total
            name = str(item[0])
            qty = str(item[1])
            price = f"{item[2]:.2f}"
            total_item = f"{item[3]:.2f}"

        data = [name, qty, price, total_item]

        for i, datum in enumerate(data):
            # قص النصوص الطويلة جداً
            cell_text = str(datum)
            if len(cell_text) > 30:
                cell_text = cell_text[:27] + "..."
            pdf.cell(col_widths[i], 10, cell_text, border=1, align="C")
        pdf.ln()

    # 4. المجموع النهائي
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(150, 10, "GRAND TOTAL:", align="R")
    pdf.cell(40, 10, total_str, border=1, align="C")

    # 5. التذييل (Footer)
    pdf.set_y(-30)
    pdf.set_font("helvetica", "I", 10)
    pdf.cell(0, 10, "Thank you for dealing with Pharma Pro System.", align="C")

    # حفظ الملف
    try:
        pdf.output(file_name)
        return os.path.abspath(file_name)
    except Exception as e:
        print(f"PDF Error: {e}")
        return None