"""
وظيفة الملف: كائن الوصول لبيانات العروض ومحرك التسعير (Offers DAO & Pricing Engine).
الطبقة: Data Access Layer / Business Logic

ملاحظات معمارية ومالية:
- [Financial Math]&#58; استبدال الحساب المباشر بالاشتقاق العكسي (Reverse Derivation)
  من الفروق المقربة لضمان تطابق الأطراف المحاسبية.
- [Zero-Trust Input]&#58; منع تسرب رسائل بايثون الخام عند تحويل الأسعار،
  والمنع الصارم لتمرير bool ككميات أو قيم غير منطقية.
- [Decimal Boundary Rule]&#58; الحساب الداخلي يتم بـ Decimal بدقة،
  ويتم التصدير للواجهة بـ float آمن فقط عند الخروج النهائي.
- [Scope Guard]&#58; مقيد بـ (simple_discount) و (cart_discount) فقط
  لحماية النواة من أي تداخل مستقبلي.
- [Admin RBAC]&#58; جميع عمليات إنشاء/تعديل/إيقاف/حذف العروض محصورة إدارياً بمدير النظام.
- [Sensitive Medicines Guard]&#58; يمنع إدخال الأدوية الرقابية أو الخطرة في عروض الأصناف.
- [Cart Overlap Guard]&#58; يمنع تداخل خصمين فعالين على إجمالي السلة في نفس المجال الزمني.
- [Safe Delete Guard]&#58; يمنع حذف أي عرض تم استخدامه تاريخياً داخل sale_items أو sales
  لحماية النزاهة المرجعية والسجل المالي.
- [UI Integration]&#58; هذا الملف متوافق مع الواجهة الجديدة التي تميز بين:
  1) عرض على أصناف محددة
  2) خصم على إجمالي السلة
"""

from database.db_manager import DatabaseManager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import logging

logger = logging.getLogger(__name__)

D_0 = Decimal("0.00")
D_4 = Decimal("0.0000")


class OffersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # 1) أدوات داخلية مساعدة
    # ==========================================
    def _normalize_text(self, value):
        """تطبيع نصي آمن: trim وتحويل None إلى سلسلة فارغة."""
        if value is None:
            return ""
        return str(value).strip()

    def _to_decimal(self, value, field_name="القيمة"):
        """تحويل آمن إلى Decimal مع رسالة عربية واضحة."""
        try:
            dec_val = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"{field_name} غير صالحة رياضياً.")
        return dec_val

    def _try_log_breach(self, user_id, action_desc):
        """محاولة توثيق محاولة تجاوز أمني دون كسر التدفق الرئيسي."""
        audit_conn = self.db.connect()
        if not audit_conn:
            return

        try:
            audit_cursor = audit_conn.cursor()
            breach_payload = json.dumps(
                {"SECURITY_BREACH": action_desc},
                ensure_ascii=False
            )
            audit_cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, old_values)
                VALUES (?, 'UPDATE', 'offers', ?)
            """, (user_id, breach_payload))
            audit_conn.commit()
        except Exception:
            logger.exception("فشل تسجيل محاولة تجاوز أمني في offers.")
        finally:
            audit_conn.close()

    def _check_admin_rbac(self, cursor, user_id):
        """تحقق إداري صارم من صلاحيات الوصول لمحرك العروض."""
        cursor.execute(
            "SELECT role FROM users WHERE id = ? AND is_active = 1",
            (user_id,)
        )
        user_row = cursor.fetchone()

        if not user_row or user_row[0] != 'admin':
            self._try_log_breach(user_id, "Unauthorized pricing/offers engine access")
            raise ValueError("صلاحيات غير كافية. إدارة العروض والتسعير تتطلب صلاحية 'مدير النظام'.")
        return True

    def _log_audit(self, cursor, user_id, action, record_id, new_values_dict=None, old_values_dict=None):
        """تسجيل أثر تدقيقي موحد."""
        old_payload = old_values_dict if old_values_dict is not None else {}
        new_payload = new_values_dict if new_values_dict is not None else {}

        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, record_id, old_values, new_values)
            VALUES (?, ?, 'offers', ?, ?, ?)
        """, (
            user_id,
            action,
            record_id,
            json.dumps(old_payload, ensure_ascii=False),
            json.dumps(new_payload, ensure_ascii=False)
        ))

    def _validate_offer_inputs(self, name, discount_type, discount_value, start_date, end_date):
        """التحقق المركزي من مدخلات العرض."""
        clean_name = self._normalize_text(name)
        if not clean_name:
            raise ValueError("اسم العرض مطلوب ولا يمكن أن يكون فارغاً.")

        if discount_type not in ['percent', 'fixed']:
            raise ValueError("نوع الخصم غير مدعوم. المسموح فقط: percent أو fixed.")

        val = self._to_decimal(discount_value, "قيمة الخصم")

        if val <= 0:
            raise ValueError("قيمة الخصم يجب أن تكون أكبر من الصفر.")

        if discount_type == 'percent' and val > Decimal("100"):
            raise ValueError("نسبة الخصم لا يمكن أن تتجاوز 100%.")

        try:
            start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("صيغة التاريخ غير صالحة. يجب أن تكون بالشكل YYYY-MM-DD.")

        if start_d > end_d:
            raise ValueError("تاريخ بداية العرض لا يمكن أن يكون بعد تاريخ النهاية.")

    def _check_cart_overlap(self, cursor, start_date, end_date, exclude_offer_id=None):
        """
        يمنع وجود أكثر من خصم فعّال على إجمالي السلة ضمن نفس المجال الزمني.
        """
        query = """
            SELECT name
            FROM offers
            WHERE scope_type = 'cart'
              AND offer_type = 'cart_discount'
              AND is_active = 1
              AND start_date <= ?
              AND end_date >= ?
        """
        params = [end_date, start_date]

        if exclude_offer_id is not None:
            query += " AND id != ?"
            params.append(exclude_offer_id)

        cursor.execute(query, tuple(params))
        conflicts = cursor.fetchall()

        if conflicts:
            names = ", ".join(r[0] for r in conflicts)
            raise ValueError(
                f"يوجد تداخل زمني مع خصومات فعالة أخرى على إجمالي السلة: ({names})."
            )

    def _validate_medicines(self, cursor, medicine_ids):
        """
        التحقق من أن قائمة الأدوية:
        - غير فارغة
        - موجودة فعلاً
        - لا تحتوي أدوية رقابية أو خطرة
        """
        unique_ids = list(set(medicine_ids))
        if not unique_ids:
            raise ValueError("لم يتم تمرير أي أدوية صحيحة للعرض.")

        placeholders = ",".join(["?"] * len(unique_ids))
        cursor.execute(f"""
            SELECT id, name, is_controlled, is_hazardous
            FROM medicines
            WHERE id IN ({placeholders})
        """, tuple(unique_ids))
        rows = cursor.fetchall()

        found_ids = [r[0] for r in rows]
        missing = set(unique_ids) - set(found_ids)
        if missing:
            raise ValueError(f"توجد أدوية غير معرفة في قاعدة البيانات (IDs: {sorted(missing)}).")

        controlled_names = [r[1] for r in rows if int(r[2]) == 1]
        hazardous_names = [r[1] for r in rows if int(r[3]) == 1]

        if controlled_names or hazardous_names:
            msg = "يُمنع شمول الأصناف التالية لأنها حساسة رقابياً أو خطرة:\n"
            if controlled_names:
                msg += f"- رقابية: {', '.join(controlled_names)}\n"
            if hazardous_names:
                msg += f"- خطرة: {', '.join(hazardous_names)}\n"
            raise ValueError(msg.strip())

        return unique_ids

    def _get_offer_usage_counts(self, cursor, offer_id):
        """
        فحص الاستخدام التاريخي للعرض داخل:
        - sale_items.applied_offer_id
        - sales.applied_cart_offer_id
        """
        cursor.execute(
            "SELECT COUNT(*) FROM sale_items WHERE applied_offer_id = ?",
            (offer_id,)
        )
        sale_items_count = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            "SELECT COUNT(*) FROM sales WHERE applied_cart_offer_id = ?",
            (offer_id,)
        )
        sales_count = int(cursor.fetchone()[0] or 0)

        return sale_items_count, sales_count

    def _get_offer_snapshot(self, cursor, offer_id):
        """
        لقطة موحدة للعرض من أجل السجل التدقيقي والرسائل.
        """
        cursor.execute("""
            SELECT id, name, offer_type, discount_type, discount_value,
                   scope_type, start_date, end_date, is_active
            FROM offers
            WHERE id = ?
        """, (offer_id,))
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "offer_type": row[2],
            "discount_type": row[3],
            "discount_value": str(row[4]),
            "scope_type": row[5],
            "start_date": row[6],
            "end_date": row[7],
            "is_active": int(row[8]) if row[8] is not None else 0
        }

    def _scope_display_name(self, scope_type):
        if scope_type == 'item':
            return "عرض على أصناف محددة"
        if scope_type == 'cart':
            return "خصم على إجمالي السلة"
        return "عرض غير معروف"

    # ==========================================
    # 2) واجهات القراءة للواجهة الرسومية
    # ==========================================
    def get_offerable_medicines(self):
        """
        جلب الأدوية المؤهلة للدخول ضمن عروض الأصناف.
        يتم استبعاد:
        - الأدوية الرقابية
        - الأدوية الخطرة
        """
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, barcode
                FROM medicines
                WHERE is_controlled = 0
                  AND is_hazardous = 0
                ORDER BY name ASC
            """)
            return cursor.fetchall()
        except Exception:
            logger.exception("خطأ أثناء جلب الأدوية المؤهلة للعروض.")
            return []
        finally:
            conn.close()

    def get_all_offers(self):
        """جلب جميع العروض المتوافقة مع واجهة الإدارة الجديدة."""
        conn = self.db.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT o.id,
                       o.name,
                       o.offer_type,
                       o.discount_type,
                       o.discount_value,
                       o.scope_type,
                       o.start_date,
                       o.end_date,
                       o.is_active,
                       u.username
                FROM offers o
                JOIN users u ON o.created_by_user_id = u.id
                WHERE o.offer_type IN ('simple_discount', 'cart_discount')
                ORDER BY o.is_active DESC, o.id DESC
            """)
            return cursor.fetchall()
        except Exception:
            logger.exception("خطأ أثناء جلب قائمة العروض.")
            return []
        finally:
            conn.close()

    def get_offer_details(self, offer_id):
        """
        جلب تفاصيل عرض واحد:
        - الرأس
        - الأصناف المرتبطة به إذا كان عرض أصناف
        """
        conn = self.db.connect()
        if not conn:
            return None, []

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id,
                       name,
                       offer_type,
                       discount_type,
                       discount_value,
                       scope_type,
                       start_date,
                       end_date,
                       is_active
                FROM offers
                WHERE id = ?
                  AND offer_type IN ('simple_discount', 'cart_discount')
            """, (offer_id,))
            header = cursor.fetchone()

            if not header:
                return None, []

            medicines = []
            if header[5] == 'item':
                cursor.execute("""
                    SELECT m.id, m.name, m.barcode
                    FROM offer_medicines om
                    JOIN medicines m ON om.medicine_id = m.id
                    WHERE om.offer_id = ?
                    ORDER BY m.name ASC
                """, (offer_id,))
                medicines = cursor.fetchall()

            return header, medicines
        except Exception:
            logger.exception("خطأ أثناء جلب تفاصيل العرض.")
            return None, []
        finally:
            conn.close()

    # ==========================================
    # 3) إنشاء وتعديل عروض الأصناف
    # ==========================================
    def add_item_offer(self, name, discount_type, discount_value, start_date, end_date, user_id, medicine_ids):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال بقاعدة البيانات.", None

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            clean_name = self._normalize_text(name)
            self._validate_offer_inputs(clean_name, discount_type, discount_value, start_date, end_date)
            unique_meds = self._validate_medicines(cursor, medicine_ids)

            cursor.execute("""
                INSERT INTO offers (
                    name, offer_type, discount_type, discount_value,
                    scope_type, start_date, end_date, created_by_user_id
                )
                VALUES (?, 'simple_discount', ?, ?, 'item', ?, ?, ?)
            """, (
                clean_name,
                discount_type,
                float(self._to_decimal(discount_value, "قيمة الخصم")),
                start_date,
                end_date,
                user_id
            ))

            offer_id = cursor.lastrowid

            for med_id in unique_meds:
                cursor.execute("""
                    INSERT INTO offer_medicines (offer_id, medicine_id)
                    VALUES (?, ?)
                """, (offer_id, med_id))

            self._log_audit(
                cursor,
                user_id,
                'INSERT',
                offer_id,
                {
                    "name": clean_name,
                    "scope": "item",
                    "discount_type": discount_type,
                    "discount_value": str(discount_value),
                    "medicines_count": len(unique_meds)
                }
            )

            conn.commit()
            return True, f"تم إنشاء عرض الأصناف ({clean_name}) بنجاح.", offer_id

        except ValueError as ve:
            conn.rollback()
            return False, str(ve), None
        except Exception:
            conn.rollback()
            logger.exception("خطأ في add_item_offer.")
            return False, "فشل داخلي أثناء إنشاء عرض الأصناف.", None
        finally:
            conn.close()

    def update_item_offer(self, offer_id, name, discount_type, discount_value, start_date, end_date, user_id, medicine_ids):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            old_snapshot = self._get_offer_snapshot(cursor, offer_id)
            if not old_snapshot or old_snapshot["scope_type"] != 'item' or old_snapshot["offer_type"] != 'simple_discount':
                raise ValueError("العرض غير موجود أو ليس عرض أصناف متوافقاً.")

            clean_name = self._normalize_text(name)
            self._validate_offer_inputs(clean_name, discount_type, discount_value, start_date, end_date)
            unique_meds = self._validate_medicines(cursor, medicine_ids)

            cursor.execute("""
                UPDATE offers
                SET name = ?, discount_type = ?, discount_value = ?, start_date = ?, end_date = ?
                WHERE id = ?
            """, (
                clean_name,
                discount_type,
                float(self._to_decimal(discount_value, "قيمة الخصم")),
                start_date,
                end_date,
                offer_id
            ))

            cursor.execute("DELETE FROM offer_medicines WHERE offer_id = ?", (offer_id,))
            for med_id in unique_meds:
                cursor.execute("""
                    INSERT INTO offer_medicines (offer_id, medicine_id)
                    VALUES (?, ?)
                """, (offer_id, med_id))

            self._log_audit(
                cursor,
                user_id,
                'UPDATE',
                offer_id,
                {
                    "action": "update_item_offer",
                    "name": clean_name,
                    "discount_type": discount_type,
                    "discount_value": str(discount_value),
                    "medicines_count": len(unique_meds)
                },
                old_values_dict=old_snapshot
            )

            conn.commit()
            return True, f"تم تحديث عرض الأصناف ({clean_name}) بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ في update_item_offer.")
            return False, "فشل داخلي أثناء تحديث عرض الأصناف."
        finally:
            conn.close()

    # ==========================================
    # 4) إنشاء وتعديل خصومات إجمالي السلة
    # ==========================================
    def add_cart_offer(self, name, discount_type, discount_value, start_date, end_date, user_id):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال.", None

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            clean_name = self._normalize_text(name)
            self._validate_offer_inputs(clean_name, discount_type, discount_value, start_date, end_date)
            self._check_cart_overlap(cursor, start_date, end_date)

            cursor.execute("""
                INSERT INTO offers (
                    name, offer_type, discount_type, discount_value,
                    scope_type, start_date, end_date, created_by_user_id
                )
                VALUES (?, 'cart_discount', ?, ?, 'cart', ?, ?, ?)
            """, (
                clean_name,
                discount_type,
                float(self._to_decimal(discount_value, "قيمة الخصم")),
                start_date,
                end_date,
                user_id
            ))

            offer_id = cursor.lastrowid

            self._log_audit(
                cursor,
                user_id,
                'INSERT',
                offer_id,
                {
                    "name": clean_name,
                    "scope": "cart",
                    "discount_type": discount_type,
                    "discount_value": str(discount_value)
                }
            )

            conn.commit()
            return True, f"تم إنشاء خصم على إجمالي السلة ({clean_name}) بنجاح.", offer_id

        except ValueError as ve:
            conn.rollback()
            return False, str(ve), None
        except Exception:
            conn.rollback()
            logger.exception("خطأ في add_cart_offer.")
            return False, "فشل داخلي أثناء إنشاء خصم إجمالي السلة.", None
        finally:
            conn.close()

    def update_cart_offer(self, offer_id, name, discount_type, discount_value, start_date, end_date, user_id):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            old_snapshot = self._get_offer_snapshot(cursor, offer_id)
            if not old_snapshot or old_snapshot["scope_type"] != 'cart' or old_snapshot["offer_type"] != 'cart_discount':
                raise ValueError("العرض غير موجود أو ليس خصماً على إجمالي السلة متوافقاً.")

            clean_name = self._normalize_text(name)
            self._validate_offer_inputs(clean_name, discount_type, discount_value, start_date, end_date)
            self._check_cart_overlap(cursor, start_date, end_date, exclude_offer_id=offer_id)

            cursor.execute("""
                UPDATE offers
                SET name = ?, discount_type = ?, discount_value = ?, start_date = ?, end_date = ?
                WHERE id = ?
            """, (
                clean_name,
                discount_type,
                float(self._to_decimal(discount_value, "قيمة الخصم")),
                start_date,
                end_date,
                offer_id
            ))

            self._log_audit(
                cursor,
                user_id,
                'UPDATE',
                offer_id,
                {
                    "action": "update_cart_offer",
                    "name": clean_name,
                    "discount_type": discount_type,
                    "discount_value": str(discount_value)
                },
                old_values_dict=old_snapshot
            )

            conn.commit()
            return True, f"تم تحديث خصم إجمالي السلة ({clean_name}) بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ في update_cart_offer.")
            return False, "فشل داخلي أثناء تحديث خصم إجمالي السلة."
        finally:
            conn.close()

    # ==========================================
    # 5) تفعيل / إيقاف / حذف العرض
    # ==========================================
    def toggle_offer_status(self, offer_id, user_id):
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            snapshot = self._get_offer_snapshot(cursor, offer_id)
            if not snapshot:
                raise ValueError("العرض غير موجود.")

            offer_name = snapshot["name"]
            current_status = snapshot["is_active"]
            scope_type = snapshot["scope_type"]
            start_date = snapshot["start_date"]
            end_date = snapshot["end_date"]
            offer_type = snapshot["offer_type"]

            if offer_type not in ['simple_discount', 'cart_discount']:
                raise ValueError(f"لا يمكن تغيير حالة عرض من النوع '{offer_type}' في هذه المرحلة.")

            new_status = 0 if int(current_status) == 1 else 1

            # تحققات إضافية قبل إعادة التفعيل
            if new_status == 1:
                if scope_type == 'item' and offer_type == 'simple_discount':
                    cursor.execute("""
                        SELECT medicine_id
                        FROM offer_medicines
                        WHERE offer_id = ?
                    """, (offer_id,))
                    med_ids = [r[0] for r in cursor.fetchall()]
                    if med_ids:
                        self._validate_medicines(cursor, med_ids)

                elif scope_type == 'cart' and offer_type == 'cart_discount':
                    self._check_cart_overlap(cursor, start_date, end_date, exclude_offer_id=offer_id)

            cursor.execute("""
                UPDATE offers
                SET is_active = ?
                WHERE id = ?
            """, (new_status, offer_id))

            self._log_audit(
                cursor,
                user_id,
                'UPDATE',
                offer_id,
                {
                    "action": "toggle_offer_status",
                    "offer_name": offer_name,
                    "new_status": new_status
                },
                old_values_dict=snapshot
            )

            conn.commit()

            if new_status == 1:
                return True, f"تم تفعيل العرض ({offer_name}) بنجاح."
            return True, f"تم إيقاف العرض ({offer_name}) بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ في toggle_offer_status.")
            return False, "فشل داخلي أثناء تغيير حالة العرض."
        finally:
            conn.close()

    def delete_offer(self, offer_id, user_id):
        """
        حذف إداري آمن للعرض.
        يُمنع الحذف إذا كان العرض مستخدماً في أي بيع تاريخي.
        """
        conn = self.db.connect()
        if not conn:
            return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()
            self._check_admin_rbac(cursor, user_id)

            snapshot = self._get_offer_snapshot(cursor, offer_id)
            if not snapshot:
                raise ValueError("العرض غير موجود أو تم حذفه مسبقاً.")

            sale_items_count, sales_count = self._get_offer_usage_counts(cursor, offer_id)

            if sale_items_count > 0 or sales_count > 0:
                details = []
                if sale_items_count > 0:
                    details.append(f"استُخدم على بنود مبيعات: {sale_items_count}")
                if sales_count > 0:
                    details.append(f"استُخدم كخصم سلة: {sales_count}")

                details_text = "، ".join(details)
                raise ValueError(
                    "رفض مرجعي/محاسبي: لا يمكن حذف هذا العرض لأنه مستخدم في عمليات بيع تاريخية "
                    f"({details_text})."
                )

            # تنظيف الربط الخاص بعروض الأصناف قبل الحذف
            cursor.execute("DELETE FROM offer_medicines WHERE offer_id = ?", (offer_id,))
            cursor.execute("DELETE FROM offers WHERE id = ?", (offer_id,))

            self._log_audit(
                cursor,
                user_id,
                'DELETE',
                offer_id,
                {
                    "deleted": True,
                    "scope_display": self._scope_display_name(snapshot["scope_type"])
                },
                old_values_dict=snapshot
            )

            conn.commit()
            return True, f"تم حذف العرض ({snapshot['name']}) بنجاح."

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("خطأ في delete_offer.")
            return False, "فشل داخلي أثناء حذف العرض."
        finally:
            conn.close()

    # ==========================================
    # 6) محرك التسعير المالي
    # ==========================================
    def evaluate_cart(self, cart_items):
        """
        المحرك السيادي لتسعير السلة (Zero-Trust POS Engine).

        العقد المتوقع لكل بند داخل cart_items:
        {
            "line_id": "unique-row-id",
            "medicine_id": 5,
            "qty": 2,
            "price": 35.0
        }

        [Architectural Fix]:
        - يفرض وجود line_id فريد لكل بند لضمان المطابقة القطعية
          مع التشغيلات (Batches) داخل نقطة البيع.
        """
        if not cart_items:
            return {
                "items": [],
                "gross_subtotal": 0.0,
                "subtotal_amount": 0.0,
                "total_item_discounts": 0.0,
                "cart_discount_amount": 0.0,
                "applied_cart_offer_id": None,
                "net_total": 0.0
            }

        conn = self.db.connect()
        if not conn:
            raise Exception("فشل الاتصال بالمحرك السعري.")

        try:
            cursor = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")

            med_ids = []
            parsed_cart = []
            line_ids_set = set()

            for item in cart_items:
                line_id = item.get('line_id')
                m_id = item.get('medicine_id')
                qty = item.get('qty')
                price = item.get('price')

                if not line_id:
                    raise ValueError(f"كل بند يجب أن يحتوي على 'line_id' صريح. الصنف المفقود هويته: {m_id}")

                if line_id in line_ids_set:
                    raise ValueError(f"معرف السطر '{line_id}' مكرر في السلة. يجب أن يكون فريداً.")
                line_ids_set.add(line_id)

                if not m_id:
                    raise ValueError(f"يوجد صنف غير معرف (بدون medicine_id) في السطر {line_id}.")

                if isinstance(qty, bool) or type(qty) is not int or qty <= 0:
                    raise ValueError(f"الكمية غير صالحة للسطر {line_id}. يجب أن تكون عدداً صحيحاً موجباً.")

                try:
                    price_dec = Decimal(str(price))
                except (InvalidOperation, ValueError, TypeError):
                    raise ValueError(f"السعر غير صالح للسطر {line_id}. يجب أن يكون رقماً صالحاً.")

                if price_dec < D_0:
                    raise ValueError(f"السعر غير صالح للسطر {line_id}. يجب أن يكون صفراً أو أكثر.")

                med_ids.append(m_id)
                parsed_cart.append({
                    'line_id': line_id,
                    'medicine_id': m_id,
                    'qty': Decimal(qty),
                    'price_dec': price_dec
                })

            placeholders = ",".join(["?"] * len(med_ids))
            cursor.execute(f"""
                SELECT id, is_controlled, is_hazardous
                FROM medicines
                WHERE id IN ({placeholders})
            """, tuple(med_ids))
            rows = cursor.fetchall()

            found_ids = {r[0] for r in rows}
            missing = set(med_ids) - found_ids
            if missing:
                raise ValueError(f"الأدوية التالية غير موجودة في قاعدة البيانات: {sorted(missing)}")

            med_flags = {
                row[0]: {
                    'ctrl': int(row[1]),
                    'haz': int(row[2])
                }
                for row in rows
            }

            # عروض الأصناف الفعالة
            cursor.execute(f"""
                SELECT om.medicine_id, o.id, o.discount_type, o.discount_value
                FROM offers o
                JOIN offer_medicines om ON o.id = om.offer_id
                WHERE om.medicine_id IN ({placeholders})
                  AND o.scope_type = 'item'
                  AND o.offer_type = 'simple_discount'
                  AND o.is_active = 1
                  AND ? BETWEEN o.start_date AND o.end_date
                ORDER BY o.id ASC
            """, tuple(med_ids) + (today_str,))
            active_item_offers = cursor.fetchall()

            # خصم إجمالي السلة الفعال
            cursor.execute("""
                SELECT id, discount_type, discount_value
                FROM offers
                WHERE scope_type = 'cart'
                  AND offer_type = 'cart_discount'
                  AND is_active = 1
                  AND ? BETWEEN start_date AND end_date
                ORDER BY id ASC
                LIMIT 1
            """, (today_str,))
            cart_offer = cursor.fetchone()

            evaluated_items = []
            eligible_cart_subtotal = D_0

            for item in parsed_cart:
                line_id = item['line_id']
                m_id = item['medicine_id']
                qty = item['qty']
                original_price = item['price_dec'].quantize(D_4, rounding=ROUND_HALF_UP)
                original_total = (qty * original_price).quantize(D_0, rounding=ROUND_HALF_UP)

                flags = med_flags.get(m_id, {'ctrl': 0, 'haz': 0})
                is_excluded = (flags['ctrl'] == 1 or flags['haz'] == 1)

                best_discount_val_per_unit = D_0
                applied_item_offer_id = None

                if not is_excluded:
                    best_saving = Decimal("-1.00")
                    medicine_offers = [o for o in active_item_offers if o[0] == m_id]

                    for off in medicine_offers:
                        offer_id = off[1]
                        d_type = off[2]
                        d_val = Decimal(str(off[3]))
                        saving = D_0

                        if d_type == 'percent':
                            ratio = min(d_val / Decimal("100.0"), Decimal("1.0"))
                            saving = original_price * ratio
                        elif d_type == 'fixed':
                            saving = min(d_val, original_price)

                        if saving > best_saving:
                            best_saving = saving
                            best_discount_val_per_unit = saving
                            applied_item_offer_id = offer_id

                unit_price_after_item = max(original_price - best_discount_val_per_unit, D_0).quantize(
                    D_4, rounding=ROUND_HALF_UP
                )
                total_after_item = (unit_price_after_item * qty).quantize(D_0, rounding=ROUND_HALF_UP)
                item_discount_amount = (original_total - total_after_item).quantize(D_0, rounding=ROUND_HALF_UP)

                is_cart_eligible = (not is_excluded and total_after_item > D_0)
                if is_cart_eligible:
                    eligible_cart_subtotal += total_after_item

                evaluated_items.append({
                    "line_id": line_id,
                    "medicine_id": m_id,
                    "qty": qty,
                    "original_unit_price": original_price,
                    "original_total": original_total,
                    "item_discount_amount": item_discount_amount,
                    "applied_offer_id": applied_item_offer_id,
                    "is_cart_eligible": is_cart_eligible,
                    "temp_total_after_item": total_after_item,
                    "cart_discount_share": D_0,
                    "final_total": total_after_item,
                    "final_unit_price": unit_price_after_item
                })

            cart_discount_total = D_0
            applied_cart_offer_id = None

            if cart_offer and eligible_cart_subtotal > D_0:
                applied_cart_offer_id = cart_offer[0]
                c_d_type = cart_offer[1]
                c_d_val = Decimal(str(cart_offer[2]))

                if c_d_type == 'percent':
                    ratio = min(c_d_val / Decimal("100.0"), Decimal("1.0"))
                    cart_discount_total = (eligible_cart_subtotal * ratio).quantize(D_0, rounding=ROUND_HALF_UP)
                elif c_d_type == 'fixed':
                    cart_discount_total = min(c_d_val, eligible_cart_subtotal).quantize(D_0, rounding=ROUND_HALF_UP)

                remaining_cart_discount = cart_discount_total
                eligible_items = [i for i in evaluated_items if i['is_cart_eligible']]

                for idx, e_item in enumerate(eligible_items):
                    if idx == len(eligible_items) - 1:
                        share = remaining_cart_discount
                    else:
                        ratio = e_item['temp_total_after_item'] / eligible_cart_subtotal
                        share = (cart_discount_total * ratio).quantize(D_0, rounding=ROUND_HALF_UP)
                        remaining_cart_discount -= share

                    e_item['cart_discount_share'] = share
                    e_item['final_total'] = (e_item['temp_total_after_item'] - share).quantize(
                        D_0, rounding=ROUND_HALF_UP
                    )
                    e_item['final_unit_price'] = (e_item['final_total'] / e_item['qty']).quantize(
                        D_4, rounding=ROUND_HALF_UP
                    )

            final_contract_items = []
            for item in evaluated_items:
                line_cart_discount = (item['temp_total_after_item'] - item['final_total']).quantize(
                    D_0, rounding=ROUND_HALF_UP
                )
                line_total_discount = (item['original_total'] - item['final_total']).quantize(
                    D_0, rounding=ROUND_HALF_UP
                )

                final_contract_items.append({
                    "line_id": item['line_id'],
                    "medicine_id": item['medicine_id'],
                    "qty": int(item['qty']),
                    "original_unit_price": float(item['original_unit_price']),
                    "item_discount_amount": float(item['item_discount_amount']),
                    "cart_discount_share": float(line_cart_discount),
                    "discount_amount": float(line_total_discount),
                    "final_unit_price": float(item['final_unit_price']),
                    "total_item_price": float(item['final_total']),
                    "applied_offer_id": item['applied_offer_id']
                })

            gross_subtotal = sum(i['original_total'] for i in evaluated_items)
            subtotal_amount = sum(i['temp_total_after_item'] for i in evaluated_items)
            net_total = sum(i['final_total'] for i in evaluated_items)
            total_item_discounts = sum(i['item_discount_amount'] for i in evaluated_items)

            return {
                "items": final_contract_items,
                "gross_subtotal": float(gross_subtotal),
                "subtotal_amount": float(subtotal_amount),
                "total_item_discounts": float(total_item_discounts),
                "cart_discount_amount": float(cart_discount_total),
                "applied_cart_offer_id": applied_cart_offer_id,
                "net_total": float(net_total)
            }

        except ValueError:
            raise
        except Exception:
            logger.exception("انهيار داخلي في محرك التسعير.")
            raise Exception("تعذر تسعير السلة لخلل داخلي في المحرك.")
        finally:
            conn.close()