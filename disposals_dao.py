"""
وظيفة الملف: كائن الوصول لبيانات تسوية وإتلاف الأدوية (Disposals DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية ومحاسبية:
- يطبق (Deep RBAC): العمليات محصورة بمدير النظام (admin) فقط.
- يعالج ثغرة (Double-Spend) بتجميع الكميات المطلوبة لنفس الرزمة قبل التحقق من الرصيد.
- يطبق (Zero-Trust) بصرامة: يرفض إتلاف رزمة غير منتهية الصلاحية إذا كان سبب الإتلاف (expired).
- يمثل تسوية جردية دقيقة تخصم الكمية وتسجل التكلفة كخسارة هدر (out) في transactions.
- [V13 Patch - Hazardous Disposal]:
    1. يفرض التحقق من البيانات الإلزامية (آلية الإتلاف) لأي مادة خطرة.
    2. يُدرج سجلاً مستقلاً مفصلاً في `hazardous_disposal_log` ضمن نفس المعاملة الذرية لضمان الامتثال البيئي.
"""

from database.db_manager import DatabaseManager
from datetime import datetime
import json
import sqlite3

class DisposalsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def get_disposable_batches(self, reason='expired'):
        """
        جلب الرزم المتاحة للإتلاف.
        [V13 Patch]: إرجاع حقول المواد الخطرة لتمكين الواجهة من طلب بيانات الإتلاف الخاص.
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            query = """
                SELECT b.id, m.barcode, m.name, b.batch_number, b.expiry_date, b.quantity, b.buy_price, b.status,
                       m.is_hazardous, m.hazard_class
                FROM batches b
                JOIN medicines m ON b.medicine_id = m.id
                WHERE b.quantity > 0
            """
            params = []

            if reason == 'expired':
                query += " AND b.expiry_date < date('now')"

            query += " ORDER BY b.expiry_date ASC"

            cursor.execute(query, params)
            batches = []
            for row in cursor.fetchall():
                batches.append({
                    "batch_id": row[0],
                    "barcode": row[1],
                    "medicine_name": row[2],
                    "batch_number": row[3],
                    "expiry_date": row[4],
                    "available_qty": row[5],
                    "unit_cost": row[6],
                    "status": row[7],
                    "is_hazardous": row[8],
                    "hazard_class": row[9]
                })
            return batches
        except Exception as e:
            print(f"Error fetching disposable batches: {e}")
            return []
        finally:
            conn.close()

    def process_disposal(self, user_id, items_to_dispose, reason='expired', notes='', hazard_data=None):
        """
        تنفيذ عملية الإتلاف بشكل ذري (Atomic).
        [V13 Patch]: يستقبل `hazard_data` لتعبئة السجل البيئي الخاص إذا تضمنت القائمة مواد خطرة.
        """
        if not user_id:
            return False, "تعذر تحديد المستخدم الحالي. العملية مرفوضة."

        if not items_to_dispose or not isinstance(items_to_dispose, list):
            return False, "قائمة الأدوية المراد إتلافها فارغة أو غير صالحة."

        allowed_reasons = ('expired', 'damaged', 'recalled', 'other')
        if reason not in allowed_reasons:
            return False, "سبب الإتلاف غير صالح."

        # تهيئة hazard_data لتفادي أخطاء الـ None
        if hazard_data is None:
            hazard_data = {}

        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # 1. التحقق العميق (Deep RBAC)
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()
            if not user_row or user_row[0] != 'admin':
                breach_payload = json.dumps({"SECURITY_BREACH": "Unauthorized Disposal Attempt"})
                cursor.execute("""
                    INSERT INTO audit_logs (user_id, action, table_name, old_values)
                    VALUES (?, 'INSERT', 'disposals', ?)
                """, (user_id, breach_payload))
                conn.commit()
                raise Exception("صلاحيات غير كافية. إتلاف الأدوية وتسوية الخسائر يتطلب صلاحية 'مدير النظام'.")

            today_str = datetime.now().strftime("%Y-%m-%d")
            total_disposal_cost = 0.0
            processed_items = []

            # 2. تجميع الكميات المطلوبة لنفس التشغيلة (Anti Double-Spend Patch)
            aggregated_items = {}
            for item in items_to_dispose:
                b_id = item.get('batch_id')
                qty = item.get('quantity')

                if not b_id or not qty or qty <= 0:
                    raise Exception("بيانات الإتلاف لأحد الأصناف غير صالحة (الكمية يجب أن تكون موجبة).")

                aggregated_items[b_id] = aggregated_items.get(b_id, 0) + qty

            # 3. التحقق الدقيق من كل رزمة (Zero-Trust + Hazardous Guard Patch)
            for batch_id, total_dispose_qty in aggregated_items.items():
                cursor.execute("""
                    SELECT b.medicine_id, b.quantity, b.buy_price, b.status, b.expiry_date, 
                           m.is_hazardous, m.hazard_class, m.name 
                    FROM batches b
                    JOIN medicines m ON b.medicine_id = m.id
                    WHERE b.id = ?
                """, (batch_id,))
                batch_row = cursor.fetchone()

                if not batch_row:
                    raise Exception(f"التشغيلة رقم {batch_id} غير موجودة في قاعدة البيانات.")

                med_id, current_qty, unit_cost, current_status, expiry_date, is_haz, haz_class, med_name = batch_row

                # التحقق من الرصيد المتاح
                if current_qty < total_dispose_qty:
                    raise Exception(f"الكمية الإجمالية المراد إتلافها ({total_dispose_qty}) تتجاوز المتاح ({current_qty}) للتشغيلة رقم {batch_id} (الدواء: {med_name}).")

                # إعادة التحقق الصارم من سبب الانتهاء (Zero-Trust Expiry Check)
                if reason == 'expired' and expiry_date >= today_str:
                    raise Exception(f"رفض أمني: محاولة إتلاف دواء كـ 'منتهي الصلاحية' وتاريخه صالح حتى ({expiry_date}) (الدواء: {med_name}).")

                # [V13 Guard]: التحقق من توفر بيانات الإتلاف الخاص للمواد الخطرة
                if is_haz == 1:
                    haz_method = hazard_data.get(str(batch_id), {}).get('disposal_method', '').strip()
                    if not haz_method:
                        raise Exception(f"العملية مرفوضة: الدواء ({med_name}) مصنف كمادة خطرة ☣️. يجب تحديد 'آلية الإتلاف' بشكل إلزامي لتوثيق السجل البيئي.")

                item_total_cost = total_dispose_qty * unit_cost
                total_disposal_cost += item_total_cost

                processed_items.append({
                    "medicine_id": med_id,
                    "batch_id": batch_id,
                    "quantity": total_dispose_qty,
                    "unit_cost": unit_cost,
                    "total_item_cost": item_total_cost,
                    "current_status": current_status,
                    "new_qty": current_qty - total_dispose_qty,
                    "is_hazardous": is_haz,
                    "hazard_class": haz_class,
                    "medicine_name": med_name
                })

            if total_disposal_cost < 0:
                raise Exception("حسبة التكلفة غير منطقية.")

            # 4. بناء الرأس (Header) لعملية الإتلاف
            cursor.execute("""
                INSERT INTO disposals (user_id, disposal_date, total_cost, reason, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, today_str, total_disposal_cost, reason, notes))
            disposal_id = cursor.lastrowid

            # 5. معالجة التفاصيل وتحديث المخزون والتوثيق الخطر
            for p_item in processed_items:
                # إدراج سطر الإتلاف العام
                cursor.execute("""
                    INSERT INTO disposal_items (disposal_id, medicine_id, batch_id, quantity, unit_cost, total_item_cost)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (disposal_id, p_item['medicine_id'], p_item['batch_id'], p_item['quantity'], p_item['unit_cost'], p_item['total_item_cost']))
                disposal_item_id = cursor.lastrowid

                # تحديث المخزون
                new_status = p_item['current_status']
                if p_item['new_qty'] == 0 and new_status == 'active':
                    new_status = 'depleted'

                cursor.execute("""
                    UPDATE batches SET quantity = ?, status = ? WHERE id = ?
                """, (p_item['new_qty'], new_status, p_item['batch_id']))

                cursor.execute("""
                    UPDATE medicines SET quantity = quantity - ? WHERE id = ?
                """, (p_item['quantity'], p_item['medicine_id']))

                # ==========================================
                # [V13 Patch]: إنشاء سجل الإتلاف الخطر الموازي (Hazardous Disposal Log)
                # ==========================================
                if p_item['is_hazardous'] == 1:
                    batch_str = str(p_item['batch_id'])
                    haz_method = hazard_data.get(batch_str, {}).get('disposal_method', '').strip()
                    haz_receiver = hazard_data.get(batch_str, {}).get('receiver_entity', '').strip()
                    haz_manifest = hazard_data.get(batch_str, {}).get('manifest_number', '').strip()
                    haz_notes = hazard_data.get(batch_str, {}).get('notes', '').strip()

                    cursor.execute("""
                        INSERT INTO hazardous_disposal_log 
                        (disposal_id, disposal_item_id, medicine_id, batch_id, user_id, 
                         quantity, hazard_class, disposal_reason, disposal_method, 
                         receiver_entity, manifest_number, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        disposal_id, disposal_item_id, p_item['medicine_id'], p_item['batch_id'], user_id,
                        p_item['quantity'], p_item['hazard_class'], reason, haz_method,
                        haz_receiver, haz_manifest, haz_notes
                    ))
                # ==========================================

            # 6. الأثر المالي في (transactions) كخسارة هدر
            trans_notes = f"إتلاف/تسوية جردية - رقم العملية: {disposal_id} | السبب: {reason}"
            cursor.execute("""
                INSERT INTO transactions (transaction_type, reference_type, reference_id, amount, user_id, notes)
                VALUES ('out', 'disposal', ?, ?, ?, ?)
            """, (disposal_id, total_disposal_cost, user_id, trans_notes))

            # 7. التوثيق الأمني للعملية
            audit_payload = json.dumps({
                "disposal_reason": reason,
                "total_cost_loss": total_disposal_cost,
                "items_count": len(processed_items),
                "hazardous_items_included": any(p['is_hazardous'] == 1 for p in processed_items)
            })
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'INSERT', 'disposals', ?, '{}', ?)
            """, (user_id, disposal_id, audit_payload))

            conn.commit()
            return True, {
                "disposal_id": disposal_id,
                "total_cost": total_disposal_cost,
                "message": "تم اعتماد الإتلاف وتسوية المخزون وتوثيق الخسارة بنجاح."
            }

        except Exception as e:
            conn.rollback()
            return False, f"فشل عملية الإتلاف: {e}"
        finally:
            conn.close()

    def get_all_disposals(self, start_date=None, end_date=None):
        """
        جلب السجل التاريخي لعمليات الإتلاف.
        """
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT d.id, u.username, d.disposal_date, d.total_cost, d.reason, d.notes, d.created_at
                FROM disposals d
                JOIN users u ON d.user_id = u.id
            """
            params = []
            if start_date and end_date:
                query += " WHERE date(d.disposal_date) BETWEEN date(?) AND date(?)"
                params.extend([start_date, end_date])

            query += " ORDER BY d.disposal_date DESC, d.id DESC"
            cursor.execute(query, params)
            disposals = []
            for row in cursor.fetchall():
                disposals.append({
                    "id": row[0],
                    "username": row[1],
                    "disposal_date": row[2],
                    "total_cost": row[3],
                    "reason": row[4],
                    "notes": row[5],
                    "created_at": row[6]
                })
            return disposals
        finally:
            conn.close()

    def get_disposal_details(self, disposal_id):
        """
        جلب تفاصيل الأدوية لرقم إتلاف محدد للواجهة.
        [V13 Patch]: إضافة مؤشر الخطورة للواجهة التاريخية.
        """
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT m.barcode, m.name, b.batch_number, di.quantity, di.unit_cost, di.total_item_cost,
                       m.is_hazardous, hdl.id
                FROM disposal_items di
                JOIN medicines m ON di.medicine_id = m.id
                JOIN batches b ON di.batch_id = b.id
                LEFT JOIN hazardous_disposal_log hdl ON di.id = hdl.disposal_item_id
                WHERE di.disposal_id = ?
            """
            cursor.execute(query, (disposal_id,))
            details = []
            for row in cursor.fetchall():
                details.append({
                    "barcode": row[0],
                    "medicine_name": row[1],
                    "batch_number": row[2],
                    "quantity": row[3],
                    "unit_cost": row[4],
                    "total_item_cost": row[5],
                    "is_hazardous": row[6],
                    "has_hazardous_log": True if row[7] else False
                })
            return details
        finally:
            conn.close()