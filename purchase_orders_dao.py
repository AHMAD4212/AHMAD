"""
وظيفة الملف: كائن الوصول لبيانات أوامر الشراء (Purchase Orders DAO).
الطبقة: Data Access Layer / Business Logic
- [RBAC Fix]: تم تطبيق تحكم صارم بالصلاحيات على مستوى الصف (Row-level Security). المدير يملك صلاحية مطلقة، الصيدلي يعدل/يحذف مسوداته فقط.
- [Robust ID]: تم التخلي عن التوليد التسلسلي، واستخدام المايكروثانية لضمان الفرادة.
- [UI Helper]: تم إضافة حقل (remaining_qty) مباشرة في دالة الجلب لتسهيل عمل الواجهة.
"""

from database.db_manager import DatabaseManager
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class PurchaseOrdersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _get_user_role(self, cursor, user_id):
        cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def _generate_po_number(self, cursor):
        """توليد رقم فريد لأمر الشراء مع حماية من التصادم (Collision Retry)"""
        for _ in range(3):
            po_number = f"PO-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"
            cursor.execute("SELECT id FROM purchase_orders WHERE po_number = ?", (po_number,))
            if not cursor.fetchone():
                return po_number
        raise ValueError("فشل النظام في توليد رقم فريد لأمر الشراء بعد عدة محاولات.")

    def _validate_po_data(self, cursor, supplier_id, items):
        """التحقق الاستباقي من صحة المورد والأدوية وعدم التكرار"""
        if supplier_id:
            cursor.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,))
            if not cursor.fetchone():
                raise ValueError("المورد المحدد غير موجود في قاعدة البيانات.")

        seen_medicines = set()
        for item in items:
            med_id = item.get('medicine_id')
            req_qty = item.get('requested_qty', 0)
            est_cost = item.get('estimated_unit_cost', 0.0)

            if not med_id:
                raise ValueError("يوجد صنف غير معرف (بدون ID).")
            if req_qty <= 0:
                raise ValueError(f"الكمية المطلوبة للصنف {med_id} يجب أن تكون أكبر من الصفر.")
            if est_cost < 0:
                raise ValueError(f"التكلفة التقديرية للصنف {med_id} لا يمكن أن تكون سالبة.")
            if med_id in seen_medicines:
                raise ValueError(f"الدواء ذو المعرف {med_id} مكرر في نفس الطلب. الرجاء دمج الكميات.")

            cursor.execute("SELECT id FROM medicines WHERE id = ?", (med_id,))
            if not cursor.fetchone():
                raise ValueError(f"الدواء ذو المعرف {med_id} غير موجود في قاعدة البيانات.")

            seen_medicines.add(med_id)

    def create_draft(self, supplier_id, expected_date, items, user_id, notes=""):
        if not user_id: return False, "تعذر تحديد المستخدم."
        if not items or len(items) == 0: return False, "أمر الشراء فارغ. يجب إضافة أصناف."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            role = self._get_user_role(cursor, user_id)
            if role not in ['admin', 'pharmacist']:
                logger.warning(f"محاولة غير مصرحة لإنشاء أمر شراء من المستخدم {user_id}")
                return False, "صلاحيات غير كافية لإنشاء أوامر شراء."

            self._validate_po_data(cursor, supplier_id, items)
            po_number = self._generate_po_number(cursor)

            cursor.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, status, order_date, expected_date, created_by_user_id, notes)
                VALUES (?, ?, 'draft', CURRENT_DATE, ?, ?, ?)
            """, (po_number, supplier_id, expected_date, user_id, notes))

            po_id = cursor.lastrowid

            for item in items:
                cursor.execute("""
                    INSERT INTO purchase_order_items (purchase_order_id, medicine_id, requested_qty, estimated_unit_cost, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (po_id, item.get('medicine_id'), item.get('requested_qty'), item.get('estimated_unit_cost', 0.0), item.get('notes', "")))

            audit_json = json.dumps({"po_number": po_number, "items_count": len(items)}, ensure_ascii=False)
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'purchase_orders', ?, ?)
            """, (user_id, po_id, audit_json))

            conn.commit()
            logger.info(f"تم إنشاء مسودة طلب شراء بنجاح: {po_number}")
            return True, f"تم إنشاء مسودة الطلب بنجاح: {po_number}"

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception("خطأ داخلي حرج أثناء إنشاء أمر الشراء:")
            return False, "حدث خطأ داخلي أثناء حفظ أمر الشراء. راجع السجلات."
        finally:
            conn.close()

    def update_draft(self, po_id, supplier_id, expected_date, items, user_id, notes=""):
        if not user_id or not items: return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()
            role = self._get_user_role(cursor, user_id)

            cursor.execute("SELECT status, created_by_user_id FROM purchase_orders WHERE id = ?", (po_id,))
            row = cursor.fetchone()
            if not row: raise ValueError("أمر الشراء غير موجود.")

            status, created_by_user_id = row
            if status != 'draft': raise ValueError("لا يمكن تعديل أمر شراء إلا إذا كان في حالة 'مسودة'.")

            # [إصلاح حرج 2]: تطبيق RBAC صارم على مستوى الصف
            if role == 'admin':
                pass
            elif role == 'pharmacist' and created_by_user_id == user_id:
                pass
            else:
                raise ValueError("صلاحيات غير كافية لتعديل هذه المسودة. لا يمكنك تعديل مسودات المستخدمين الآخرين.")

            self._validate_po_data(cursor, supplier_id, items)

            cursor.execute("""
                UPDATE purchase_orders 
                SET supplier_id = ?, expected_date = ?, notes = ? 
                WHERE id = ?
            """, (supplier_id, expected_date, notes, po_id))

            cursor.execute("DELETE FROM purchase_order_items WHERE purchase_order_id = ?", (po_id,))
            for item in items:
                cursor.execute("""
                    INSERT INTO purchase_order_items (purchase_order_id, medicine_id, requested_qty, estimated_unit_cost, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (po_id, item.get('medicine_id'), item.get('requested_qty'), item.get('estimated_unit_cost', 0.0), item.get('notes', "")))

            audit_json = json.dumps({"action": "update_draft", "items_count": len(items)}, ensure_ascii=False)
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'purchase_orders', ?, ?)
            """, (user_id, po_id, audit_json))

            conn.commit()
            return True, "تم تحديث المسودة بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception(f"خطأ داخلي حرج أثناء تحديث مسودة {po_id}:")
            return False, "فشل تحديث المسودة لخطأ داخلي."
        finally:
            conn.close()

    def delete_draft(self, po_id, user_id):
        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."
        try:
            cursor = conn.cursor()
            role = self._get_user_role(cursor, user_id)

            cursor.execute("SELECT status, created_by_user_id, po_number FROM purchase_orders WHERE id = ?", (po_id,))
            row = cursor.fetchone()
            if not row: raise ValueError("أمر الشراء غير موجود.")

            status, created_by_user_id, po_number = row
            if status != 'draft': raise ValueError("لا يمكن حذف أمر شراء إلا إذا كان في حالة 'مسودة'.")

            # [إصلاح حرج 2]: تطبيق RBAC للحذف
            if role == 'admin':
                pass
            elif role == 'pharmacist' and created_by_user_id == user_id:
                pass
            else:
                raise ValueError("صلاحيات غير كافية لحذف هذه المسودة.")

            cursor.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))

            audit_json = json.dumps({"po_number": po_number, "action": "delete_draft"}, ensure_ascii=False)
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values)
                VALUES (?, 'DELETE', 'purchase_orders', ?, ?)
            """, (user_id, po_id, audit_json))

            conn.commit()
            return True, "تم حذف المسودة بنجاح."
        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception(f"خطأ داخلي أثناء حذف أمر الشراء {po_id}:")
            return False, "فشل الحذف لخطأ داخلي."
        finally:
            conn.close()

    def update_po_status(self, po_id, new_status, user_id):
        """
        آلة الحالة (State Machine) مع ربط الانتقال بالصلاحية.
        لا يسمح بتغيير الحالة يدوياً إلى (partially_received, received).
        """
        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            role = self._get_user_role(cursor, user_id)
            if not role: raise ValueError("مستخدم غير صالح.")

            cursor.execute("SELECT status, supplier_id FROM purchase_orders WHERE id = ?", (po_id,))
            row = cursor.fetchone()
            if not row: raise ValueError("أمر الشراء غير موجود.")

            current_status, supplier_id = row[0], row[1]

            # [إصلاح 4]: إزالة partially_received و received من الانتقالات اليدوية
            valid_role_transitions = {
                'admin': {
                    'draft': ['submitted', 'cancelled'],
                    'submitted': ['approved', 'cancelled'],
                    'approved': ['cancelled']
                },
                'pharmacist': {
                    'draft': ['submitted', 'cancelled'],
                    'submitted': ['cancelled']
                }
            }

            role_transitions = valid_role_transitions.get(role, {})
            allowed_new_statuses = role_transitions.get(current_status, [])

            if new_status not in allowed_new_statuses:
                raise ValueError(f"صلاحياتك لا تسمح لك بتغيير الحالة من '{current_status}' إلى '{new_status}'.")

            if new_status in ['submitted', 'approved'] and not supplier_id:
                raise ValueError("يجب تحديد المورد (Supplier) قبل إرسال أو اعتماد الطلب.")

            if new_status == 'approved':
                cursor.execute("""
                    UPDATE purchase_orders 
                    SET status = ?, approved_by_user_id = ?, approved_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_status, user_id, po_id))
            else:
                cursor.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new_status, po_id))

            audit_json = json.dumps({"old_status": current_status, "new_status": new_status}, ensure_ascii=False)
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'purchase_orders', ?, ?)
            """, (user_id, po_id, audit_json))

            conn.commit()
            return True, f"تم تحديث حالة الطلب إلى {new_status} بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception as e:
            conn.rollback()
            logger.exception(f"خطأ أثناء تحديث حالة أمر الشراء {po_id}:")
            return False, "فشل تحديث حالة الطلب لخطأ داخلي."
        finally:
            conn.close()

    def list_purchase_orders(self, status_filter=None):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT p.id, p.po_number, s.name, p.status, p.order_date, p.expected_date, u.username,
                       (SELECT COUNT(*) FROM purchase_order_items WHERE purchase_order_id = p.id) as items_count
                FROM purchase_orders p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                LEFT JOIN users u ON p.created_by_user_id = u.id
            """
            params = ()
            if status_filter:
                query += " WHERE p.status = ?"
                params = (status_filter,)
            query += " ORDER BY p.id DESC"

            cursor.execute(query, params)
            return cursor.fetchall()
        except Exception:
            logger.exception("خطأ في جلب قائمة أوامر الشراء:")
            return []
        finally:
            conn.close()

    def get_importable_orders(self):
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.po_number, s.name, p.status, p.expected_date
                FROM purchase_orders p
                JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.status IN ('approved', 'partially_received')
                ORDER BY p.expected_date ASC
            """)
            return cursor.fetchall()
        except Exception:
            logger.exception("خطأ في جلب الأوامر القابلة للاستيراد:")
            return []
        finally:
            conn.close()

    def get_po_with_items(self, po_id):
        conn = self.db.connect()
        if not conn: return None, []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT p.id, p.po_number, p.supplier_id, s.name, p.status, p.notes, 
                                   p.order_date, p.expected_date, p.created_at, p.approved_at,
                                   p.created_by_user_id  -- [تمت الإضافة هنا]
                            FROM purchase_orders p
                            LEFT JOIN suppliers s ON p.supplier_id = s.id
                            WHERE p.id = ?
                        """, (po_id,))
            header = cursor.fetchone()

            if not header: return None, []

            # [إصلاح مستحسن]: إرجاع الكمية المتبقية جاهزة للواجهة
            cursor.execute("""
                SELECT 
                    poi.id as po_item_id,
                    poi.medicine_id,
                    m.name,
                    m.barcode,
                    poi.requested_qty,
                    poi.estimated_unit_cost,
                    COALESCE((SELECT SUM(quantity) FROM purchase_items WHERE purchase_order_item_id = poi.id), 0) as received_qty,
                    (poi.requested_qty - COALESCE((SELECT SUM(quantity) FROM purchase_items WHERE purchase_order_item_id = poi.id), 0)) as remaining_qty
                FROM purchase_order_items poi
                JOIN medicines m ON poi.medicine_id = m.id
                WHERE poi.purchase_order_id = ?
            """, (po_id,))
            items = cursor.fetchall()

            return header, items
        except Exception:
            logger.exception(f"خطأ أثناء جلب تفاصيل أمر الشراء {po_id}:")
            return None, []
        finally:
            conn.close()