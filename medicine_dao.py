"""
وظيفة الملف: كائن الوصول لبيانات الأدوية والمخزون (Medicine DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية وأمنية:
- تم تطبيق (Deep RBAC) لمنع أي إضافة، تعديل، حذف، أو تصفير للكمية إلا بصلاحية (admin).
- يمنع الحذف الجذري (DELETE) لأي دواء ارتبط بحركات تشغيلية لحماية التاريخ المالي.
- [V9 Update]: تم دمج (الشكل الصيدلاني) و (التركيز) في عمليات الحفظ.
- [V11 Update - Controlled Drugs]: تم دمج الحقول الرقابية.
- [V13 Update - Hazardous Materials]: تم دمج حقول المواد الخطرة (is_hazardous, hazard_class, hazard_notes) في عمليات الإضافة والتعديل والاستعلام لدعم سياسات السلامة البيئية والمهنية. كما تم تحديث دوال العرض للجرد لترجع الحقول الرقابية والخطرة لتمكين الوسم البصري.
"""

from database.db_manager import DatabaseManager
import sqlite3
import json

class MedicineDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _sanitize_text(self, text):
        """تنظيف النصوص (إزالة الفراغات الزائدة) لضمان تطابق محرك البدائل لاحقاً"""
        if not text:
            return ""
        return " ".join(str(text).strip().split())

    def get_active_suppliers(self):
        """جلب الموردين لربطهم بالأدوية في واجهة الإضافة/التعديل."""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM suppliers ORDER BY name ASC")
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching suppliers: {e}")
            return []
        finally:
            conn.close()

    def get_medicine_info(self, medicine_id):
        """جلب البيانات الأساسية لدواء محدد (مفيدة لواجهة التعديل)."""
        conn = self.db.connect()
        if not conn: return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT barcode, name, active_ingredient, supplier_id, dosage_form, strength,
                       is_controlled, controlled_class, controlled_notes,
                       is_hazardous, hazard_class, hazard_notes,
                       description, min_stock_alert, buy_price, sell_price
                FROM medicines WHERE id = ?
            """, (medicine_id,))
            return cursor.fetchone()
        except Exception as e:
            print(f"Error fetching medicine info: {e}")
            return None
        finally:
            conn.close()

    def add_medicine(self, barcode, name, active_ingredient, dosage_form, strength, buy_price, sell_price, quantity, expiry, user_id, supplier_id=None, description="", min_stock_alert=10, is_controlled=0, controlled_class="", controlled_notes="", is_hazardous=0, hazard_class="", hazard_notes=""):
        """
        إضافة دواء جديد مع التشغيلة الافتتاحية (فقط إذا كانت الكمية > 0).
        [Deep RBAC]: يمنع الإضافة لغير المدراء (Admin).
        """
        if not user_id:
            return False, "تعذر تحديد المستخدم الحالي. العملية مرفوضة."

        conn = self.db.connect()
        if not conn:
            return False, "تعذر الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()

            # 1. التحقق العميق من الصلاحية (Deep RBAC)
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()

            if not user_row or user_row[0] != 'admin':
                raise Exception("صلاحيات غير كافية. إضافة الأدوية تتطلب صلاحية 'مدير النظام' (Admin).")

            # 2. التحققات المنطقية والتنظيف
            if buy_price < 0 or sell_price < 0 or quantity < 0:
                raise Exception("الأسعار والكميات يجب أن تكون قيماً موجبة.")

            clean_barcode = self._sanitize_text(barcode)
            clean_name = self._sanitize_text(name)
            clean_dosage = self._sanitize_text(dosage_form)
            clean_strength = self._sanitize_text(strength)
            clean_active_ing = self._sanitize_text(active_ingredient)
            clean_desc = self._sanitize_text(description)

            safe_is_controlled = 1 if int(is_controlled) == 1 else 0
            clean_ctrl_class = self._sanitize_text(controlled_class)
            clean_ctrl_notes = self._sanitize_text(controlled_notes)

            safe_is_hazardous = 1 if int(is_hazardous) == 1 else 0
            clean_haz_class = self._sanitize_text(hazard_class)
            clean_haz_notes = self._sanitize_text(hazard_notes)

            if not clean_barcode or not clean_name:
                raise Exception("الباركود واسم الدواء حقول إلزامية.")

            # 3. إدراج الدواء في المرآة الرئيسية
            query_med = """INSERT INTO medicines 
                           (barcode, name, active_ingredient, dosage_form, strength, buy_price, sell_price, quantity, expiry_date, supplier_id, description, min_stock_alert, is_controlled, controlled_class, controlled_notes, is_hazardous, hazard_class, hazard_notes) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            cursor.execute(query_med, (clean_barcode, clean_name, clean_active_ing, clean_dosage, clean_strength, buy_price, sell_price, quantity, expiry, supplier_id, clean_desc, min_stock_alert, safe_is_controlled, clean_ctrl_class, clean_ctrl_notes, safe_is_hazardous, clean_haz_class, clean_haz_notes))
            medicine_id = cursor.lastrowid

            # 4. إدراج التشغيلة الافتتاحية فقط إذا كانت الكمية أكبر من الصفر
            batch_created = False
            if quantity > 0:
                query_batch = """INSERT INTO batches 
                                 (medicine_id, batch_number, expiry_date, buy_price, sell_price, quantity) 
                                 VALUES (?, ?, ?, ?, ?, ?)"""
                cursor.execute(query_batch, (medicine_id, "OPENING_STOCK", expiry, buy_price, sell_price, quantity))
                batch_created = True

            # 5. التوثيق الأمني (Audit Log)
            audit_payload = json.dumps({
                "barcode": clean_barcode,
                "name": clean_name,
                "dosage_form": clean_dosage,
                "strength": clean_strength,
                "description": clean_desc,
                "min_stock_alert": min_stock_alert,
                "is_controlled": safe_is_controlled,
                "controlled_class": clean_ctrl_class,
                "is_hazardous": safe_is_hazardous,
                "hazard_class": clean_haz_class,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "opening_quantity": quantity,
                "batch_created": batch_created
            })
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'INSERT', 'medicines', ?, '{}', ?)
            """, (user_id, medicine_id, audit_payload))

            conn.commit()
            return True, "تمت إضافة الدواء بنجاح."

        except sqlite3.IntegrityError:
            conn.rollback()
            return False, "الباركود موجود مسبقاً! يرجى التحقق من البيانات لمنع التكرار."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def update_medicine_info(self, medicine_id, barcode, name, active_ingredient, dosage_form, strength, supplier_id, user_id, buy_price, sell_price, description, min_stock_alert, is_controlled=0, controlled_class="", controlled_notes="", is_hazardous=0, hazard_class="", hazard_notes=""):
        """
        تعديل البيانات الأساسية للدواء.
        """
        if not user_id:
            return False, "تعذر تحديد المستخدم الحالي. العملية مرفوضة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()

            # 1. التحقق العميق (Deep RBAC)
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()

            if not user_row or user_row[0] != 'admin':
                breach_payload = json.dumps({"SECURITY_BREACH": "Unauthorized UPDATE attempt on medicine info"})
                cursor.execute("""
                    INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                    VALUES (?, 'UPDATE', 'medicines', ?, '{}', ?)
                """, (user_id, medicine_id, breach_payload))
                conn.commit()
                return False, "صلاحيات غير كافية. تعديل بيانات الأدوية يتطلب صلاحية 'مدير النظام'."

            clean_barcode = self._sanitize_text(barcode)
            clean_name = self._sanitize_text(name)
            clean_dosage = self._sanitize_text(dosage_form)
            clean_strength = self._sanitize_text(strength)
            clean_active_ing = self._sanitize_text(active_ingredient)
            clean_desc = self._sanitize_text(description)

            safe_is_controlled = 1 if int(is_controlled) == 1 else 0
            clean_ctrl_class = self._sanitize_text(controlled_class)
            clean_ctrl_notes = self._sanitize_text(controlled_notes)

            safe_is_hazardous = 1 if int(is_hazardous) == 1 else 0
            clean_haz_class = self._sanitize_text(hazard_class)
            clean_haz_notes = self._sanitize_text(hazard_notes)

            if not clean_barcode or not clean_name:
                return False, "الباركود واسم الدواء حقول إلزامية."

            # 2. جلب القيم القديمة للتوثيق
            cursor.execute("""SELECT barcode, name, active_ingredient, dosage_form, strength, supplier_id,
                                     is_controlled, controlled_class, controlled_notes,
                                     is_hazardous, hazard_class, hazard_notes,
                                     buy_price, sell_price, description, min_stock_alert
                              FROM medicines WHERE id = ?""", (medicine_id,))
            old_data = cursor.fetchone()
            if not old_data:
                return False, "الدواء غير موجود."

            old_payload = json.dumps({
                "barcode": old_data[0],
                "name": old_data[1],
                "active_ingredient": old_data[2],
                "dosage_form": old_data[3],
                "strength": old_data[4],
                "supplier_id": old_data[5],
                "is_controlled": old_data[6],
                "controlled_class": old_data[7],
                "controlled_notes": old_data[8],
                "is_hazardous": old_data[9],
                "hazard_class": old_data[10],
                "hazard_notes": old_data[11],
                "buy_price": old_data[12],
                "sell_price": old_data[13],
                "description": old_data[14],
                "min_stock_alert": old_data[15]
            })

            # 3. تحديث البيانات
            query = """UPDATE medicines 
                       SET barcode = ?, name = ?, active_ingredient = ?, dosage_form = ?, strength = ?, supplier_id = ?,
                           is_controlled = ?, controlled_class = ?, controlled_notes = ?,
                           is_hazardous = ?, hazard_class = ?, hazard_notes = ?,
                           buy_price = ?, sell_price = ?, description = ?, min_stock_alert = ?
                       WHERE id = ?"""
            cursor.execute(query, (clean_barcode, clean_name, clean_active_ing, clean_dosage, clean_strength, supplier_id, safe_is_controlled, clean_ctrl_class, clean_ctrl_notes, safe_is_hazardous, clean_haz_class, clean_haz_notes, buy_price, sell_price, clean_desc, min_stock_alert, medicine_id))

            # 4. التوثيق الأمني (Audit Log)
            new_payload = json.dumps({
                "barcode": clean_barcode,
                "name": clean_name,
                "active_ingredient": clean_active_ing,
                "dosage_form": clean_dosage,
                "strength": clean_strength,
                "supplier_id": supplier_id,
                "is_controlled": safe_is_controlled,
                "controlled_class": clean_ctrl_class,
                "controlled_notes": clean_ctrl_notes,
                "is_hazardous": safe_is_hazardous,
                "hazard_class": clean_haz_class,
                "hazard_notes": clean_haz_notes,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "description": clean_desc,
                "min_stock_alert": min_stock_alert
            })
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'medicines', ?, ?, ?)
            """, (user_id, medicine_id, old_payload, new_payload))

            conn.commit()
            return True, "تم تحديث بيانات الدواء بنجاح."

        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "unique" in error_msg or "barcode" in error_msg:
                return False, "الباركود الجديد مستخدم مسبقاً لدواء آخر."
            elif "foreign key" in error_msg:
                return False, "المورد المحدد غير صالح أو تم حذفه."
            return False, "خطأ في تكامل البيانات أثناء التعديل."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    # ==========================================
    # استعلامات العرض لـ InventoryPage
    # ==========================================

    def get_all_medicines(self):
        """
        [V11 & V13 Patch]: ترجع 12 عموداً لتشمل is_controlled و is_hazardous
        لتمكين الوسم البصري في الجرد دون كسر بنية البيانات.
        """
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    m.id, m.barcode, m.name, m.active_ingredient, 
                    m.dosage_form, m.strength, 
                    m.buy_price, m.sell_price,
                    COALESCE(SUM(b.quantity), 0) AS aggregated_qty,
                    MIN(b.expiry_date) AS nearest_expiry,
                    m.is_controlled,
                    m.is_hazardous
                FROM medicines m
                LEFT JOIN batches b ON m.id = b.medicine_id AND b.status = 'active' AND b.quantity > 0
                GROUP BY m.id
                ORDER BY m.id DESC
            """
            cursor.execute(query)
            return cursor.fetchall()
        finally:
            conn.close()

    def search_medicine(self, text):
        """
        [V11 & V13 Patch]: ترجع 12 عموداً لتشمل الحقول الرقابية والخطرة.
        """
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            query = """
                SELECT 
                    m.id, m.barcode, m.name, m.active_ingredient, 
                    m.dosage_form, m.strength, 
                    m.buy_price, m.sell_price,
                    COALESCE(SUM(b.quantity), 0) AS aggregated_qty,
                    MIN(b.expiry_date) AS nearest_expiry,
                    m.is_controlled,
                    m.is_hazardous
                FROM medicines m
                LEFT JOIN batches b ON m.id = b.medicine_id AND b.status = 'active' AND b.quantity > 0
                WHERE m.name LIKE ? OR m.barcode LIKE ? OR m.active_ingredient LIKE ?
                GROUP BY m.id
            """
            search_term = f"%{text}%"
            cursor.execute(query, (search_term, search_term, search_term))
            return cursor.fetchall()
        finally:
            conn.close()

    def get_low_stock_medicines(self):
        """جلب الأدوية التي وصلت للحد الأدنى بحقول وترتيب مضمون للواجهات"""
        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, barcode, name, buy_price, quantity, min_stock_alert 
                FROM medicines 
                WHERE quantity <= min_stock_alert
            """)
            return cursor.fetchall()
        except Exception as e:
            return []
        finally:
            conn.close()

    # ==========================================
    # عمليات الحذف والتصفير
    # ==========================================

    def delete_medicine(self, medicine_id, user_id):
        if not user_id:
            return False, "تعذر تحديد المستخدم الحالي. العملية مرفوضة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()

            if not user_row or user_row[0] != 'admin':
                raise Exception("صلاحيات غير كافية. هذه العملية تتطلب صلاحية 'مدير النظام' (Admin).")

            # فحص ارتباطات البيع والمشتريات والمرتجعات الأساسية
            cursor.execute("SELECT COUNT(id) FROM sale_items WHERE medicine_id = ?", (medicine_id,))
            sales_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM purchase_items WHERE medicine_id = ?", (medicine_id,))
            purchases_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM return_items WHERE medicine_id = ?", (medicine_id,))
            returns_count = cursor.fetchone()[0]

            # الفحوصات الإضافية للارتباطات الممتدة
            cursor.execute("SELECT COUNT(id) FROM prescription_items WHERE medicine_id = ?", (medicine_id,))
            presc_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM disposal_items WHERE medicine_id = ?", (medicine_id,))
            disp_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(medicine_id) FROM offer_medicines WHERE medicine_id = ?", (medicine_id,))
            offer_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(id) FROM purchase_order_items WHERE medicine_id = ?", (medicine_id,))
            po_count = cursor.fetchone()[0]

            if sales_count > 0 or purchases_count > 0 or returns_count > 0 or presc_count > 0 or disp_count > 0 or offer_count > 0 or po_count > 0:
                raise Exception(
                    "رفض أمني: لا يمكن حذف الدواء جذرياً لارتباطه بحركات مالية أو تشغيلية "
                    "(فواتير، وصفات، إتلاف، عروض، أو أوامر شراء). "
                    "تم الحفاظ على السجل لحماية التدقيق المحاسبي. يرجى استخدام (تصفير الكمية) بدلاً من الحذف."
                )

            cursor.execute("SELECT name, barcode FROM medicines WHERE id = ?", (medicine_id,))
            med_info = cursor.fetchone()
            if not med_info:
                raise Exception("الدواء غير موجود في قاعدة البيانات.")

            med_name, med_barcode = med_info

            cursor.execute("DELETE FROM medicines WHERE id = ?", (medicine_id,))

            audit_payload = json.dumps({
                "deleted_medicine_name": med_name,
                "barcode": med_barcode,
                "reason": "Hard Delete (No Financial/Operational History)"
            })
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'DELETE', 'medicines', ?, '{}', ?)
            """, (user_id, medicine_id, audit_payload))

            conn.commit()
            return True, f"تم حذف الدواء ({med_name}) وسجلاته بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def clear_medicine_stock(self, medicine_id, user_id):
        if not user_id:
            return False, "تعذر تحديد المستخدم الحالي. العملية مرفوضة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات"

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user_row = cursor.fetchone()

            if not user_row or user_row[0] != 'admin':
                raise Exception("صلاحيات غير كافية. هذه العملية تتطلب صلاحية 'مدير النظام' (Admin).")

            cursor.execute("SELECT name FROM medicines WHERE id = ?", (medicine_id,))
            med_info = cursor.fetchone()
            if not med_info:
                raise Exception("الدواء غير موجود في قاعدة البيانات.")
            med_name = med_info[0]

            cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM batches WHERE medicine_id = ?", (medicine_id,))
            real_cleared_qty = cursor.fetchone()[0]

            cursor.execute("""
                UPDATE batches 
                SET quantity = 0, 
                    status = CASE 
                        WHEN status = 'active' THEN 'depleted' 
                        ELSE status 
                    END 
                WHERE medicine_id = ?
            """, (medicine_id,))

            cursor.execute("UPDATE medicines SET quantity = 0 WHERE id = ?", (medicine_id,))

            audit_payload = json.dumps({
                "medicine_name": med_name,
                "cleared_quantity_from_batches": real_cleared_qty,
                "action": "Clear Stock to Zero (Preserved Statuses)"
            })
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
                VALUES (?, 'UPDATE', 'medicines', ?, '{}', ?)
            """, (user_id, medicine_id, audit_payload))

            conn.commit()
            return True, f"تم تصفير كمية الدواء ({med_name}) بنجاح (أصبح خارج المخزون التشغيلي)."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()