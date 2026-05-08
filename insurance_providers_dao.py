"""
وظيفة الملف: طبقة الوصول للبيانات الخاصة بمزودي التأمين (Insurance Providers DAO).
الطبقة: Data Access Layer

ملاحظات معمارية:
- هذا الملف يخص الكيان الأساسي فقط: insurance_providers.
- يعتمد Soft Delete عبر is_active بدلاً من الحذف الفيزيائي.
- جميع عمليات الكتابة تتم داخل معاملات صريحة BEGIN IMMEDIATE.
- يدعم التدقيق (audit_logs) عند الإنشاء والتعديل والتعطيل/إعادة التفعيل.
- يمنع تعطيل مزود تأمين إذا كان مرتبطاً بوثائق تأمين فعالة.
- لا يحتوي أي منطق واجهات، فقط منطق قواعد البيانات والتحقق السيادي.
"""

import json
import sqlite3
import logging
from typing import Optional, Any, Dict, List, Tuple

from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class InsuranceProvidersDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # Connection Helpers
    # ==========================================
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db.db_name)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _row_to_dict(self, row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row else None

    def _rows_to_dicts(self, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        return [dict(r) for r in rows]

    # ==========================================
    # Normalization / Validation Helpers
    # ==========================================
    def _normalize_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip()
        return value if value else None

    def _normalize_email(self, value: Any) -> Optional[str]:
        value = self._normalize_text(value)
        return value.lower() if value else None

    def _normalize_code(self, value: Any) -> Optional[str]:
        value = self._normalize_text(value)
        return value.upper() if value else None

    def _parse_coverage_percent(self, value: Any) -> float:
        if value is None or str(value).strip() == "":
            return 80.0

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise ValueError("نسبة التغطية الافتراضية يجب أن تكون رقماً صالحاً.")

        if parsed < 0 or parsed > 100:
            raise ValueError("نسبة التغطية الافتراضية يجب أن تكون بين 0 و 100.")

        return round(parsed, 2)

    def _validate_provider_name(self, name: Any) -> str:
        safe_name = self._normalize_text(name)
        if not safe_name:
            raise ValueError("اسم مزود التأمين حقل إلزامي.")
        return safe_name

    def _validate_provider_payload(
        self,
        name: Any,
        code: Any = None,
        contact_person: Any = None,
        phone: Any = None,
        email: Any = None,
        address: Any = None,
        notes: Any = None,
        default_coverage_percent: Any = 80.0
    ) -> Dict[str, Any]:
        return {
            "name": self._validate_provider_name(name),
            "code": self._normalize_code(code),
            "contact_person": self._normalize_text(contact_person),
            "phone": self._normalize_text(phone),
            "email": self._normalize_email(email),
            "address": self._normalize_text(address),
            "notes": self._normalize_text(notes),
            "default_coverage_percent": self._parse_coverage_percent(default_coverage_percent)
        }

    # ==========================================
    # Audit Helper
    # ==========================================
    def _write_audit_log(
        self,
        cursor: sqlite3.Cursor,
        user_id: Optional[int],
        action: str,
        table_name: str,
        record_id: int,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None
    ) -> None:
        cursor.execute("""
            INSERT INTO audit_logs (
                user_id, action, table_name, record_id, old_values, new_values
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            action,
            table_name,
            record_id,
            json.dumps(old_values, ensure_ascii=False) if old_values is not None else None,
            json.dumps(new_values, ensure_ascii=False) if new_values is not None else None
        ))

    # ==========================================
    # Query Helpers
    # ==========================================
    def _get_provider_by_id_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        provider_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                id,
                name,
                code,
                contact_person,
                phone,
                email,
                address,
                notes,
                default_coverage_percent,
                is_active,
                created_at,
                updated_at
            FROM insurance_providers
            WHERE id = ?
        """, (provider_id,))
        row = cursor.fetchone()
        return self._row_to_dict(row)

    def _provider_name_exists(
        self,
        cursor: sqlite3.Cursor,
        name: str,
        exclude_id: Optional[int] = None
    ) -> bool:
        sql = """
            SELECT 1
            FROM insurance_providers
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
              AND is_active = 1
        """
        params: List[Any] = [name]

        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _provider_code_exists(
        self,
        cursor: sqlite3.Cursor,
        code: Optional[str],
        exclude_id: Optional[int] = None
    ) -> bool:
        if not code:
            return False

        sql = """
            SELECT 1
            FROM insurance_providers
            WHERE LOWER(TRIM(code)) = LOWER(TRIM(?))
              AND TRIM(code) <> ''
        """
        params: List[Any] = [code]

        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _has_active_policies(
        self,
        cursor: sqlite3.Cursor,
        provider_id: int
    ) -> bool:
        cursor.execute("""
            SELECT 1
            FROM customer_insurance_policies
            WHERE provider_id = ?
              AND status = 'active'
            LIMIT 1
        """, (provider_id,))
        return cursor.fetchone() is not None

    # ==========================================
    # Read API
    # ==========================================
    def get_all_providers(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    id,
                    name,
                    code,
                    contact_person,
                    phone,
                    email,
                    address,
                    notes,
                    default_coverage_percent,
                    is_active,
                    created_at,
                    updated_at
                FROM insurance_providers
            """
            params: List[Any] = []

            if not include_inactive:
                sql += " WHERE is_active = 1"

            sql += " ORDER BY name COLLATE NOCASE ASC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to load insurance providers.")
            return []
        finally:
            conn.close()

    def get_active_providers(self) -> List[Dict[str, Any]]:
        return self.get_all_providers(include_inactive=False)

    def get_provider_by_id(self, provider_id: Any) -> Optional[Dict[str, Any]]:
        try:
            provider_id = int(provider_id)
        except (TypeError, ValueError):
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            return self._get_provider_by_id_with_cursor(cursor, provider_id)
        except Exception:
            logger.exception("Failed to get insurance provider by id=%s", provider_id)
            return None
        finally:
            conn.close()

    def search_providers(self, keyword: Any, include_inactive: bool = False) -> List[Dict[str, Any]]:
        safe_keyword = self._normalize_text(keyword)
        if not safe_keyword:
            return self.get_all_providers(include_inactive=include_inactive)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    id,
                    name,
                    code,
                    contact_person,
                    phone,
                    email,
                    address,
                    notes,
                    default_coverage_percent,
                    is_active,
                    created_at,
                    updated_at
                FROM insurance_providers
                WHERE (
                    name LIKE ?
                    OR code LIKE ?
                    OR contact_person LIKE ?
                    OR phone LIKE ?
                    OR email LIKE ?
                )
            """
            params: List[Any] = [f"%{safe_keyword}%"] * 5

            if not include_inactive:
                sql += " AND is_active = 1"

            sql += " ORDER BY name COLLATE NOCASE ASC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to search insurance providers with keyword=%s", safe_keyword)
            return []
        finally:
            conn.close()

    # ==========================================
    # Write API
    # ==========================================
    def create_provider(
        self,
        name: Any,
        code: Any = None,
        contact_person: Any = None,
        phone: Any = None,
        email: Any = None,
        address: Any = None,
        notes: Any = None,
        default_coverage_percent: Any = 80.0,
        created_by_user_id: Optional[int] = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            payload = self._validate_provider_payload(
                name=name,
                code=code,
                contact_person=contact_person,
                phone=phone,
                email=email,
                address=address,
                notes=notes,
                default_coverage_percent=default_coverage_percent
            )

            if self._provider_name_exists(cursor, payload["name"]):
                conn.rollback()
                return False, "يوجد مزود تأمين فعّال بنفس الاسم مسبقاً."

            if self._provider_code_exists(cursor, payload["code"]):
                conn.rollback()
                return False, "رمز مزود التأمين مستخدم مسبقاً."

            cursor.execute("""
                INSERT INTO insurance_providers (
                    name, code, contact_person, phone, email, address, notes,
                    default_coverage_percent, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                payload["name"],
                payload["code"],
                payload["contact_person"],
                payload["phone"],
                payload["email"],
                payload["address"],
                payload["notes"],
                payload["default_coverage_percent"]
            ))

            provider_id = cursor.lastrowid
            new_state = self._get_provider_by_id_with_cursor(cursor, provider_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=created_by_user_id,
                action="INSERT",
                table_name="insurance_providers",
                record_id=provider_id,
                old_values=None,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "provider_id": provider_id,
                "message": f"تم إنشاء مزود التأمين ({payload['name']}) بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while creating insurance provider.")
            return False, f"فشل حفظ مزود التأمين بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while creating insurance provider.")
            return False, "حدث خطأ داخلي غير متوقع أثناء إنشاء مزود التأمين."
        finally:
            conn.close()

    def update_provider(
        self,
        provider_id: Any,
        name: Any,
        code: Any = None,
        contact_person: Any = None,
        phone: Any = None,
        email: Any = None,
        address: Any = None,
        notes: Any = None,
        default_coverage_percent: Any = 80.0,
        updated_by_user_id: Optional[int] = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            provider_id = int(provider_id)
        except (TypeError, ValueError):
            return False, "معرف مزود التأمين غير صالح."

        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            old_state = self._get_provider_by_id_with_cursor(cursor, provider_id)
            if not old_state:
                conn.rollback()
                return False, "مزود التأمين المطلوب غير موجود."

            payload = self._validate_provider_payload(
                name=name,
                code=code,
                contact_person=contact_person,
                phone=phone,
                email=email,
                address=address,
                notes=notes,
                default_coverage_percent=default_coverage_percent
            )

            if self._provider_name_exists(cursor, payload["name"], exclude_id=provider_id):
                conn.rollback()
                return False, "يوجد مزود تأمين فعّال آخر بنفس الاسم."

            if self._provider_code_exists(cursor, payload["code"], exclude_id=provider_id):
                conn.rollback()
                return False, "رمز مزود التأمين مستخدم لدى سجل آخر."

            cursor.execute("""
                UPDATE insurance_providers
                SET
                    name = ?,
                    code = ?,
                    contact_person = ?,
                    phone = ?,
                    email = ?,
                    address = ?,
                    notes = ?,
                    default_coverage_percent = ?
                WHERE id = ?
            """, (
                payload["name"],
                payload["code"],
                payload["contact_person"],
                payload["phone"],
                payload["email"],
                payload["address"],
                payload["notes"],
                payload["default_coverage_percent"],
                provider_id
            ))

            new_state = self._get_provider_by_id_with_cursor(cursor, provider_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=updated_by_user_id,
                action="UPDATE",
                table_name="insurance_providers",
                record_id=provider_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "provider_id": provider_id,
                "message": f"تم تحديث مزود التأمين ({payload['name']}) بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while updating insurance provider.")
            return False, f"فشل تحديث مزود التأمين بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while updating insurance provider id=%s", provider_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تحديث مزود التأمين."
        finally:
            conn.close()

    def set_provider_active_state(
        self,
        provider_id: Any,
        is_active: Any,
        updated_by_user_id: Optional[int] = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            provider_id = int(provider_id)
            target_state = 1 if bool(is_active) else 0
        except (TypeError, ValueError):
            return False, "المدخلات الخاصة بحالة مزود التأمين غير صالحة."

        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            old_state = self._get_provider_by_id_with_cursor(cursor, provider_id)
            if not old_state:
                conn.rollback()
                return False, "مزود التأمين المطلوب غير موجود."

            if int(old_state["is_active"]) == target_state:
                conn.rollback()
                return False, "حالة مزود التأمين مطابقة بالفعل ولا يوجد ما يلزم تغييره."

            # عند التعطيل نمنع تعطيل مزود مرتبط بوثائق فعالة
            if target_state == 0 and self._has_active_policies(cursor, provider_id):
                conn.rollback()
                return False, "لا يمكن تعطيل مزود التأمين لأنه مرتبط بوثائق تأمين فعالة حالياً."

            cursor.execute("""
                UPDATE insurance_providers
                SET is_active = ?
                WHERE id = ?
            """, (target_state, provider_id))

            new_state = self._get_provider_by_id_with_cursor(cursor, provider_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=updated_by_user_id,
                action="UPDATE",
                table_name="insurance_providers",
                record_id=provider_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()

            action_text = "إعادة تفعيل" if target_state == 1 else "تعطيل"
            return True, {
                "provider_id": provider_id,
                "message": f"تم {action_text} مزود التأمين ({old_state['name']}) بنجاح."
            }

        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while changing provider active state id=%s", provider_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تغيير حالة مزود التأمين."
        finally:
            conn.close()

    def deactivate_provider(
        self,
        provider_id: Any,
        updated_by_user_id: Optional[int] = None
    ) -> Tuple[bool, Any]:
        return self.set_provider_active_state(
            provider_id=provider_id,
            is_active=False,
            updated_by_user_id=updated_by_user_id
        )

    def reactivate_provider(
        self,
        provider_id: Any,
        updated_by_user_id: Optional[int] = None
    ) -> Tuple[bool, Any]:
        return self.set_provider_active_state(
            provider_id=provider_id,
            is_active=True,
            updated_by_user_id=updated_by_user_id
        )

    # ==========================================
    # Utility API
    # ==========================================
    def get_provider_combo_items(self) -> List[Dict[str, Any]]:
        """
        دالة مساعدة للواجهات:
        ترجع فقط السجلات الفعالة مع الحقول المطلوبة للقوائم المنسدلة.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    id,
                    name,
                    code,
                    default_coverage_percent
                FROM insurance_providers
                WHERE is_active = 1
                ORDER BY name COLLATE NOCASE ASC
            """)
            return self._rows_to_dicts(cursor.fetchall())
        except Exception:
            logger.exception("Failed to load insurance provider combo items.")
            return []
        finally:
            conn.close()