"""
وظيفة الملف: كائن الوصول لبيانات البدائل الدوائية (Drug Alternatives DAO).
الطبقة: Data Access Layer / Business Logic
ملاحظة معمارية وسريرية:
- [Clinical Accuracy]: البديل لا يُقترح بناءً على الفئة أو المادة الفعالة فقط، بل يشترط التطابق التام في: (المادة الفعالة، الشكل الصيدلاني، والتركيز).
- [Stock Verification]: يتم استبعاد الأدوية التي لا تمتلك رصيداً فعالاً قابلاً للبيع (عبر الربط مع جدول batches).
- [Canonical Match]: يتم توحيد النصوص برمجياً (LOWER و TRIM) قبل المقارنة لتجاوز أخطاء الإدخال النصي.
- [V11 Patch - Controlled Drugs]: يقوم بإرجاع الحالة الرقابية (is_controlled) لمنع الالتفاف على الحظر في المبيعات الحرة (OTC).
- [V13 Patch - Hazardous Guard]: يرجع حقول المواد الخطرة (is_hazardous, hazard_class) لضمان تمريرها للـ POS وتطبيق الوسم البصري، التحذير التشغيلي، والعزل المحاسبي (Triple Guard).
"""

from database.db_manager import DatabaseManager


class AlternativesDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _get_medicine_base_info(self, cursor, medicine_id):
        """جلب الخصائص الأساسية للدواء لغايات مطابقة البدائل"""
        cursor.execute("""
            SELECT active_ingredient, dosage_form, strength 
            FROM medicines 
            WHERE id = ?
        """, (medicine_id,))
        return cursor.fetchone()

    def get_alternatives_for_medicine(self, medicine_id):
        """
        جلب البدائل الطبية الدقيقة (نفس المادة، الشكل، والتركيز) المتوفرة في المخزون.
        مرتبة من الأرخص ثم الأعلى كمية.
        """
        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()

            base_info = self._get_medicine_base_info(cursor, medicine_id)
            if not base_info:
                return []

            active_ingredient, dosage_form, strength = base_info

            # Fail-Safe: إذا كانت الحقول المرجعية فارغة، نرفض تقديم بديل لمنع الاجتهادات الخطرة
            if not active_ingredient or not dosage_form or not strength:
                return []

            # استعلام يجلب البدائل المطابقة بدقة والتي تملك دفعات نشطة ورصيداً حقيقياً
            # [V11 & V13 Patch]: تمرير الحقول الرقابية والخطرة
            query = """
                SELECT 
                    m.id, 
                    m.barcode, 
                    m.name, 
                    m.active_ingredient, 
                    m.dosage_form, 
                    m.strength, 
                    m.sell_price, 
                    SUM(b.quantity) as available_qty,
                    m.is_controlled,
                    m.controlled_class,
                    m.is_hazardous,
                    m.hazard_class
                FROM medicines m
                JOIN batches b ON m.id = b.medicine_id
                WHERE LOWER(TRIM(m.active_ingredient)) = LOWER(TRIM(?))
                  AND LOWER(TRIM(m.dosage_form)) = LOWER(TRIM(?))
                  AND LOWER(TRIM(m.strength)) = LOWER(TRIM(?))
                  AND m.id != ?
                  AND b.status = 'active'
                  AND b.quantity > 0
                  AND b.expiry_date >= date('now')
                GROUP BY m.id
                ORDER BY m.sell_price ASC, available_qty DESC
            """

            cursor.execute(query, (active_ingredient, dosage_form, strength, medicine_id))

            alternatives = []
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                # سيتم تحويل m.is_controlled و m.is_hazardous تلقائياً
                # إلى alt['is_controlled'] و alt['is_hazardous']
                alternatives.append(dict(zip(columns, row)))

            return alternatives

        except Exception as e:
            print(f"Error fetching alternatives: {e}")
            return []
        finally:
            conn.close()

    def get_alternatives_by_barcode_or_name(self, text):
        """البحث عن الدواء أولاً بالنص/الباركود، ثم إرجاع بدائله المتاحة"""
        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()
            search_term = f"%{text}%"
            cursor.execute("""
                SELECT id FROM medicines 
                WHERE barcode = ? OR name LIKE ? 
                LIMIT 1
            """, (text, search_term))

            row = cursor.fetchone()
            if not row:
                return []

            return self.get_alternatives_for_medicine(row[0])

        except Exception as e:
            print(f"Error fetching alternatives by text: {e}")
            return []
        finally:
            conn.close()

    def get_cheaper_alternatives(self, medicine_id):
        """تصفية قائمة البدائل وإرجاع الأصناف الأرخص من الدواء الأصلي فقط"""
        conn = self.db.connect()
        if not conn: return []

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT sell_price FROM medicines WHERE id = ?", (medicine_id,))
            row = cursor.fetchone()
            if not row:
                return []

            original_price = row[0]
            all_alternatives = self.get_alternatives_for_medicine(medicine_id)

            # تصفية برمجية
            cheaper_alternatives = [alt for alt in all_alternatives if alt['sell_price'] < original_price]
            return cheaper_alternatives

        except Exception as e:
            print(f"Error fetching cheaper alternatives: {e}")
            return []
        finally:
            conn.close()

    def has_available_alternative(self, medicine_id):
        """فحص سريع وفعال (بولياني) لمعرفة ما إذا كان الدواء يملك بديلاً متاحاً للبيع"""
        conn = self.db.connect()
        if not conn: return False

        try:
            cursor = conn.cursor()

            base_info = self._get_medicine_base_info(cursor, medicine_id)
            if not base_info:
                return False

            active_ingredient, dosage_form, strength = base_info
            if not active_ingredient or not dosage_form or not strength:
                return False

            query = """
                SELECT 1
                FROM medicines m
                JOIN batches b ON m.id = b.medicine_id
                WHERE LOWER(TRIM(m.active_ingredient)) = LOWER(TRIM(?))
                  AND LOWER(TRIM(m.dosage_form)) = LOWER(TRIM(?))
                  AND LOWER(TRIM(m.strength)) = LOWER(TRIM(?))
                  AND m.id != ?
                  AND b.status = 'active'
                  AND b.quantity > 0
                  AND b.expiry_date >= date('now')
                LIMIT 1
            """

            cursor.execute(query, (active_ingredient, dosage_form, strength, medicine_id))
            return cursor.fetchone() is not None

        except Exception as e:
            print(f"Error checking alternative existence: {e}")
            return False
        finally:
            conn.close()