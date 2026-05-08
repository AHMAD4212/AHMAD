"""
وظيفة الملف: كائن الوصول لبيانات المستخدمين (Users DAO).
الطبقة: Data Access Layer / Security
ملاحظة معمارية وأمنية:
- [Deep RBAC]: يتم التحقق من صلاحية (admin) من قاعدة البيانات لكل عملية إدارة.
- [Anti-Lockout]: يمنع النظام تعطيل حساب المدير الأخير، أو قيام المدير بتعطيل نفسه.
- [Soft Delete]: تم منع الحذف الجذري (DELETE) حمايةً للتكامل المرجعي. يُستبدل بتعطيل الحساب (is_active = 0).
- [Audit Trails]: تسجيل كافة التعديلات الأمنية ومحاولات الاختراق.
- [تكامل أمني]: تم إزالة خوارزمية SHA256 كلياً واعتماد PasswordUtils للتحقق والتشفير الموحد.
- [منع التكرار]: لا يسمح النظام للمستخدم باستخدام كلمة المرور السابقة عند التغيير.
"""

from database.db_manager import DatabaseManager
from core.security.password_utils import PasswordUtils
import json

class UsersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    def _log_breach(self, cursor, user_id, action_desc):
        """توثيق محاولة التجاوز الأمني"""
        breach_payload = json.dumps({"SECURITY_BREACH": action_desc})
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, table_name, old_values)
            VALUES (?, 'UPDATE', 'users', ?)
        """, (user_id, breach_payload))

    def get_all_users(self, requester_id):
        """جلب جميع المستخدمين (للمدراء فقط)"""
        if not requester_id: return []

        conn = self.db.connect()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                return []  # صمت أمني للمتطفلين

            cursor.execute("SELECT id, username, role, is_active, created_at FROM users ORDER BY id ASC")
            return cursor.fetchall()
        finally:
            conn.close()

    def add_user(self, requester_id, username, password, role):
        """إضافة مستخدم جديد"""
        if not requester_id: return False, "المستخدم غير محدد."

        clean_user = username.strip()
        if not clean_user or not password:
            return False, "اسم المستخدم وكلمة المرور حقول إلزامية."

        allowed_roles = ('admin', 'pharmacist', 'cashier')
        if role not in allowed_roles:
            return False, "الصلاحية المحددة غير صحيحة."

        # التحقق من قوة كلمة المرور الجديدة عبر الطبقة المركزية
        is_strong, msg = PasswordUtils.validate_password_strength(password)
        if not is_strong:
            return False, msg

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال بقاعدة البيانات."

        try:
            cursor = conn.cursor()

            # التحقق العميق من الصلاحية
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized attempt to create user {clean_user}")
                conn.commit()
                raise Exception("صلاحيات غير كافية لإدارة المستخدمين.")

            # التحقق من عدم التكرار
            cursor.execute("SELECT id FROM users WHERE username = ?", (clean_user,))
            if cursor.fetchone():
                raise Exception("اسم المستخدم موجود مسبقاً.")

            # التشفير الموحد عبر الخدمة المركزية
            hashed_pass = PasswordUtils.hash_password(password)

            cursor.execute("""
                INSERT INTO users (username, password_hash, role, is_active, must_change_password) 
                VALUES (?, ?, ?, 1, 1)
            """, (clean_user, hashed_pass, role))

            new_user_id = cursor.lastrowid

            audit_payload = json.dumps({"username": clean_user, "role": role})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'INSERT', 'users', ?, ?)
            """, (requester_id, new_user_id, audit_payload))

            conn.commit()
            return True, "تم إضافة المستخدم بنجاح."
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def toggle_user_status(self, requester_id, target_user_id, make_active: bool):
        """تفعيل أو تعطيل مستخدم (بديل الحذف النهائي)"""
        if not requester_id or not target_user_id:
            return False, "بيانات غير مكتملة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            # 1. التحقق من الصلاحية
            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized toggle status for user {target_user_id}")
                conn.commit()
                raise Exception("صلاحيات غير كافية.")

            # 2. منع المدير من تعطيل نفسه (Lockout Prevention)
            if requester_id == target_user_id and not make_active:
                raise Exception("لا يمكنك تعطيل حسابك الشخصي أثناء الدخول.")

            # 3. التحقق من المستهدف وقاعدة المدير الأخير
            cursor.execute("SELECT username, role, is_active FROM users WHERE id = ?", (target_user_id,))
            target = cursor.fetchone()
            if not target:
                raise Exception("المستخدم المستهدف غير موجود.")

            target_username, target_role, current_status = target
            new_status_int = 1 if make_active else 0

            if current_status == new_status_int:
                return True, "الحالة مطابقة بالفعل."

            if target_role == 'admin' and not make_active:
                cursor.execute("SELECT COUNT(id) FROM users WHERE role = 'admin' AND is_active = 1")
                admin_count = cursor.fetchone()[0]
                if admin_count <= 1:
                    raise Exception("لا يمكن تعطيل حساب المدير الأخير النشط في النظام حمايةً للمشروع.")

            # 4. تنفيذ التعديل
            cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status_int, target_user_id))

            audit_payload = json.dumps(
                {"action": "Account Enabled" if make_active else "Account Disabled", "target": target_username})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'users', ?, ?)
            """, (requester_id, target_user_id, audit_payload))

            conn.commit()
            return True, f"تم {'تفعيل' if make_active else 'تعطيل'} حساب ({target_username}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def change_user_role(self, requester_id, target_user_id, new_role):
        """تغيير صلاحية المستخدم (ترقية/تجريد)"""
        if not requester_id or not target_user_id:
            return False, "بيانات غير مكتملة."

        allowed_roles = ('admin', 'pharmacist', 'cashier')
        if new_role not in allowed_roles:
            return False, "الصلاحية المحددة غير صحيحة."

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized role change for user {target_user_id}")
                conn.commit()
                raise Exception("صلاحيات غير كافية.")

            cursor.execute("SELECT username, role FROM users WHERE id = ?", (target_user_id,))
            target = cursor.fetchone()
            if not target:
                raise Exception("المستخدم المستهدف غير موجود.")

            target_username, old_role = target

            if old_role == new_role:
                return True, "المستخدم يملك هذه الصلاحية بالفعل."

            # قاعدة المدير الأخير (إذا تم تجريده من الإدارة)
            if old_role == 'admin' and new_role != 'admin':
                cursor.execute("SELECT COUNT(id) FROM users WHERE role = 'admin' AND is_active = 1")
                admin_count = cursor.fetchone()[0]
                if admin_count <= 1:
                    raise Exception("لا يمكن تجريد المدير الأخير النشط من صلاحياته حمايةً للمشروع.")

            cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, target_user_id))

            audit_payload = json.dumps({"target": target_username, "old_role": old_role, "new_role": new_role})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'users', ?, ?)
            """, (requester_id, target_user_id, audit_payload))

            conn.commit()
            return True, f"تم تغيير صلاحية ({target_username}) إلى ({new_role}) بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def reset_user_password(self, requester_id, target_user_id, new_password):
        """إعادة تعيين كلمة مرور لمستخدم آخر (للمدراء فقط)"""
        if not new_password: return False, "كلمة المرور لا يمكن أن تكون فارغة."

        is_strong, msg = PasswordUtils.validate_password_strength(new_password)
        if not is_strong:
            return False, msg

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            cursor.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (requester_id,))
            req_user = cursor.fetchone()
            if not req_user or req_user[0] != 'admin':
                self._log_breach(cursor, requester_id, f"Unauthorized password reset for user {target_user_id}")
                conn.commit()
                raise Exception("صلاحيات غير كافية.")

            # التشفير الموحد
            hashed_pass = PasswordUtils.hash_password(new_password)

            # إجبار المستخدم على تغيير كلمة المرور في الدخول القادم
            cursor.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                           (hashed_pass, target_user_id))

            # التحقق من أن الصف تم تحديثه فعلاً
            if cursor.rowcount == 0:
                 raise Exception("المستخدم المستهدف غير موجود.")

            audit_payload = json.dumps({"action": "Admin Reset Password"})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'users', ?, ?)
            """, (requester_id, target_user_id, audit_payload))

            conn.commit()
            return True, "تم إعادة تعيين كلمة المرور بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    def change_own_password(self, user_id, old_password, new_password):
        """تغيير كلمة المرور الشخصية للمستخدم نفسه مع منع استخدام الكلمة القديمة"""
        if not old_password or not new_password:
            return False, "يجب إدخال الكلمة القديمة والجديدة."

        is_strong, msg = PasswordUtils.validate_password_strength(new_password)
        if not is_strong:
            return False, msg

        conn = self.db.connect()
        if not conn: return False, "فشل الاتصال."

        try:
            cursor = conn.cursor()

            cursor.execute("SELECT password_hash FROM users WHERE id = ? AND is_active = 1", (user_id,))
            user = cursor.fetchone()
            if not user:
                raise Exception("حساب المستخدم غير فعال أو غير موجود.")

            current_hash = user[0]

            # 1. التحقق من أن كلمة المرور القديمة صحيحة
            if not PasswordUtils.verify_password(old_password, current_hash):
                # إذا فشل التحقق الحديث، نحاول التحقق القديم لمرة أخيرة قبل الرفض
                if not PasswordUtils.is_legacy_sha256_hash(old_password, current_hash):
                    raise Exception("كلمة المرور القديمة غير صحيحة.")

            # 2. [التحديث الأمني]: منع إعادة استخدام نفس كلمة المرور الحالية
            if PasswordUtils.verify_password(new_password, current_hash) or PasswordUtils.is_legacy_sha256_hash(new_password, current_hash):
                raise Exception("لا يمكنك إعادة استخدام كلمة المرور الحالية. الرجاء اختيار كلمة مرور جديدة.")

            new_hash = PasswordUtils.hash_password(new_password)

            # رفع علم must_change_password لأن المستخدم غيّرها بنفسه
            cursor.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                           (new_hash, user_id))

            audit_payload = json.dumps({"action": "User Changed Own Password"})
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, table_name, record_id, new_values)
                VALUES (?, 'UPDATE', 'users', ?, ?)
            """, (user_id, user_id, audit_payload))

            conn.commit()
            return True, "تم تغيير كلمة المرور بنجاح."

        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()