"""
وظيفة الملف: طبقة الوصول للبيانات الخاصة بوثائق تأمين العملاء/المرضى
(Customer Insurance Policies DAO).
الطبقة: Data Access Layer

ملاحظات معمارية:
- هذا الملف يمثل الجسر الحقيقي بين العميل ومزود التأمين.
- يعتمد Soft-State عبر status بدلاً من الحذف الفيزيائي.
- جميع عمليات الكتابة تتم داخل معاملات صريحة BEGIN IMMEDIATE.
- يدعم التدقيق (audit_logs) عند الإنشاء والتعديل وتغيير الحالة وتغيير الافتراضية.
- يمنع إنشاء وثيقة غير منطقية (تواريخ غير صحيحة، نسب غير صالحة، كيان غير موجود).
- متوافق بالكامل مع مخطط V27 الفعلي.

العقد الفعلي للجدول customer_insurance_policies في V27:
- id
- customer_id
- provider_id
- policy_number
- member_number
- default_coverage_percent
- default_patient_share_percent
- coverage_limit_amount
- valid_from
- valid_to
- status                  -> active / expired / suspended / cancelled
- is_default              -> 0 / 1
- notes
- created_by_user_id
- updated_by_user_id
- created_at
- updated_at
"""

import json
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Any, Dict, List, Tuple

from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class CustomerInsurancePoliciesDAO:
    ALLOWED_STATUSES = {"active", "suspended", "expired", "cancelled"}

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

    def _normalize_policy_number(self, value: Any) -> str:
        value = self._normalize_text(value)
        if not value:
            raise ValueError("رقم الوثيقة حقل إلزامي.")
        return value.upper()

    def _normalize_member_number(self, value: Any) -> Optional[str]:
        value = self._normalize_text(value)
        return value.upper() if value else None

    def _parse_int_id(self, value: Any, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} غير صالح.")

        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً موجباً.")
        return parsed

    def _parse_percent(self, value: Any, field_name: str) -> Optional[float]:
        if value is None or str(value).strip() == "":
            return None

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن تكون رقماً صالحاً.")

        if parsed < 0 or parsed > 100:
            raise ValueError(f"{field_name} يجب أن تكون بين 0 و 100.")

        return round(parsed, 2)

    def _parse_nonnegative_amount(
        self,
        value: Any,
        field_name: str = "حد التغطية"
    ) -> Optional[float]:
        if value is None or str(value).strip() == "":
            return None

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون رقماً صالحاً.")

        if parsed < 0:
            raise ValueError(f"{field_name} لا يجوز أن يكون سالباً.")

        return round(parsed, 2)

    def _parse_bool_flag(self, value: Any) -> int:
        if isinstance(value, bool):
            return 1 if value else 0

        if value in (1, "1", "true", "True", "yes", "YES", "on"):
            return 1

        return 0

    def _parse_optional_date(self, value: Any, field_name: str) -> Optional[str]:
        if value is None or str(value).strip() == "":
            return None

        value = str(value).strip()

        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{field_name} يجب أن يكون بصيغة YYYY-MM-DD.")

        return value

    def _validate_date_range(self, valid_from: Optional[str], valid_to: Optional[str]) -> None:
        if not valid_from or not valid_to:
            return

        start_obj = datetime.strptime(valid_from, "%Y-%m-%d").date()
        end_obj = datetime.strptime(valid_to, "%Y-%m-%d").date()

        if start_obj > end_obj:
            raise ValueError("تاريخ بداية التغطية يجب أن يكون أقدم من أو مساوياً لتاريخ النهاية.")

    def _validate_status(self, status: Any) -> str:
        safe_status = self._normalize_text(status)
        if not safe_status:
            raise ValueError("حالة الوثيقة حقل إلزامي.")

        safe_status = safe_status.lower()
        if safe_status not in self.ALLOWED_STATUSES:
            raise ValueError("حالة الوثيقة غير صالحة.")
        return safe_status

    def _resolve_coverage_pair(
        self,
        default_coverage_percent: Any,
        default_patient_share_percent: Any
    ) -> Tuple[float, float]:
        safe_coverage = self._parse_percent(default_coverage_percent, "نسبة تغطية شركة التأمين")
        safe_patient_share = self._parse_percent(default_patient_share_percent, "نسبة مساهمة المريض")

        if safe_coverage is None and safe_patient_share is None:
            safe_coverage = 80.0
            safe_patient_share = 20.0
        elif safe_coverage is not None and safe_patient_share is None:
            safe_patient_share = round(100.0 - safe_coverage, 2)
        elif safe_coverage is None and safe_patient_share is not None:
            safe_coverage = round(100.0 - safe_patient_share, 2)

        if safe_coverage is None or safe_patient_share is None:
            raise ValueError("تعذر احتساب نسب التغطية التأمينية.")

        if safe_coverage + safe_patient_share > 100:
            raise ValueError("مجموع نسبة تغطية الشركة ونسبة مساهمة المريض لا يجوز أن يتجاوز 100%.")

        return safe_coverage, safe_patient_share

    def _validate_payload(
        self,
        customer_id: Any,
        provider_id: Any,
        policy_number: Any,
        member_number: Any = None,
        default_coverage_percent: Any = None,
        default_patient_share_percent: Any = None,
        coverage_limit_amount: Any = None,
        valid_from: Any = None,
        valid_to: Any = None,
        status: Any = "active",
        is_default: Any = 0,
        notes: Any = None
    ) -> Dict[str, Any]:
        safe_customer_id = self._parse_int_id(customer_id, "معرف العميل")
        safe_provider_id = self._parse_int_id(provider_id, "معرف مزود التأمين")
        safe_policy_number = self._normalize_policy_number(policy_number)
        safe_member_number = self._normalize_member_number(member_number)

        safe_coverage, safe_patient_share = self._resolve_coverage_pair(
            default_coverage_percent,
            default_patient_share_percent
        )

        safe_coverage_limit = self._parse_nonnegative_amount(coverage_limit_amount, "سقف التغطية")
        safe_valid_from = self._parse_optional_date(valid_from, "تاريخ بداية التغطية")
        safe_valid_to = self._parse_optional_date(valid_to, "تاريخ نهاية التغطية")
        safe_status = self._validate_status(status)
        safe_is_default = self._parse_bool_flag(is_default)
        safe_notes = self._normalize_text(notes)

        self._validate_date_range(safe_valid_from, safe_valid_to)

        # لا معنى لوثيقة غير فعالة وموسومة كوثيقة افتراضية
        if safe_status != "active":
            safe_is_default = 0

        return {
            "customer_id": safe_customer_id,
            "provider_id": safe_provider_id,
            "policy_number": safe_policy_number,
            "member_number": safe_member_number,
            "default_coverage_percent": safe_coverage,
            "default_patient_share_percent": safe_patient_share,
            "coverage_limit_amount": safe_coverage_limit,
            "valid_from": safe_valid_from,
            "valid_to": safe_valid_to,
            "status": safe_status,
            "is_default": safe_is_default,
            "notes": safe_notes
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
            json.dumps(old_values, ensure_ascii=False, default=str) if old_values is not None else None,
            json.dumps(new_values, ensure_ascii=False, default=str) if new_values is not None else None
        ))

    # ==========================================
    # Existence / Integrity Helpers
    # ==========================================
    def _customer_exists(self, cursor: sqlite3.Cursor, customer_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM customers
            WHERE id = ?
              AND COALESCE(is_active, 1) = 1
            LIMIT 1
        """, (customer_id,))
        return cursor.fetchone() is not None

    def _provider_exists_and_active(self, cursor: sqlite3.Cursor, provider_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM insurance_providers
            WHERE id = ?
              AND is_active = 1
            LIMIT 1
        """, (provider_id,))
        return cursor.fetchone() is not None

    def _user_exists(self, cursor: sqlite3.Cursor, user_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM users
            WHERE id = ?
            LIMIT 1
        """, (user_id,))
        return cursor.fetchone() is not None

    def _policy_number_exists(
        self,
        cursor: sqlite3.Cursor,
        provider_id: int,
        policy_number: str,
        exclude_id: Optional[int] = None
    ) -> bool:
        sql = """
            SELECT 1
            FROM customer_insurance_policies
            WHERE provider_id = ?
              AND UPPER(TRIM(policy_number)) = UPPER(TRIM(?))
        """
        params: List[Any] = [provider_id, policy_number]

        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _member_number_exists(
        self,
        cursor: sqlite3.Cursor,
        provider_id: int,
        member_number: Optional[str],
        exclude_id: Optional[int] = None
    ) -> bool:
        if not member_number:
            return False

        sql = """
            SELECT 1
            FROM customer_insurance_policies
            WHERE provider_id = ?
              AND UPPER(TRIM(member_number)) = UPPER(TRIM(?))
        """
        params: List[Any] = [provider_id, member_number]

        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _unset_other_default_policies(
        self,
        cursor: sqlite3.Cursor,
        customer_id: int,
        exclude_policy_id: Optional[int] = None,
        updated_by_user_id: Optional[int] = None
    ) -> None:
        sql = """
            UPDATE customer_insurance_policies
            SET is_default = 0
        """
        params: List[Any] = []

        if updated_by_user_id is not None:
            sql += ", updated_by_user_id = ?"
            params.append(updated_by_user_id)

        sql += """
            WHERE customer_id = ?
              AND is_default = 1
              AND status = 'active'
        """
        params.append(customer_id)

        if exclude_policy_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_policy_id)

        cursor.execute(sql, params)

    def _get_policy_by_id_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        policy_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                p.id,
                p.customer_id,
                c.name AS customer_name,
                COALESCE(c.is_active, 1) AS customer_is_active,
                p.provider_id,
                ip.name AS provider_name,
                ip.code AS provider_code,
                ip.is_active AS provider_is_active,
                p.policy_number,
                p.member_number,
                p.default_coverage_percent,
                p.default_patient_share_percent,
                p.coverage_limit_amount,
                p.valid_from,
                p.valid_to,
                p.status,
                p.is_default,
                p.notes,
                p.created_by_user_id,
                cu.username AS created_by_username,
                p.updated_by_user_id,
                uu.username AS updated_by_username,
                p.created_at,
                p.updated_at
            FROM customer_insurance_policies p
            JOIN customers c ON p.customer_id = c.id
            JOIN insurance_providers ip ON p.provider_id = ip.id
            LEFT JOIN users cu ON p.created_by_user_id = cu.id
            LEFT JOIN users uu ON p.updated_by_user_id = uu.id
            WHERE p.id = ?
        """, (policy_id,))
        return self._row_to_dict(cursor.fetchone())

    def _is_policy_currently_valid(self, policy_row: Dict[str, Any]) -> bool:
        """
        الصلاحية التشغيلية:
        - الحالة active
        - العميل فعال
        - مزود التأمين فعال
        - التاريخ الحالي ضمن مدى الوثيقة إذا كانت التواريخ موجودة
        """
        if not policy_row:
            return False

        if str(policy_row.get("status", "")).lower() != "active":
            return False

        if int(policy_row.get("customer_is_active", 0) or 0) != 1:
            return False

        if int(policy_row.get("provider_is_active", 0) or 0) != 1:
            return False

        today = date.today()

        try:
            valid_from = policy_row.get("valid_from")
            valid_to = policy_row.get("valid_to")

            if valid_from:
                start_obj = datetime.strptime(valid_from, "%Y-%m-%d").date()
                if today < start_obj:
                    return False

            if valid_to:
                end_obj = datetime.strptime(valid_to, "%Y-%m-%d").date()
                if today > end_obj:
                    return False

        except Exception:
            return False

        return True

    # ==========================================
    # Read API
    # ==========================================
    def get_policy_by_id(self, policy_id: Any) -> Optional[Dict[str, Any]]:
        try:
            policy_id = int(policy_id)
        except (TypeError, ValueError):
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            return self._get_policy_by_id_with_cursor(cursor, policy_id)
        except Exception:
            logger.exception("Failed to get policy by id=%s", policy_id)
            return None
        finally:
            conn.close()

    def get_all_policies(
        self,
        customer_id: Optional[Any] = None,
        provider_id: Optional[Any] = None,
        status: Optional[str] = None,
        default_only: bool = False
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    p.id,
                    p.customer_id,
                    c.name AS customer_name,
                    COALESCE(c.is_active, 1) AS customer_is_active,
                    p.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ip.is_active AS provider_is_active,
                    p.policy_number,
                    p.member_number,
                    p.default_coverage_percent,
                    p.default_patient_share_percent,
                    p.coverage_limit_amount,
                    p.valid_from,
                    p.valid_to,
                    p.status,
                    p.is_default,
                    p.notes,
                    p.created_by_user_id,
                    cu.username AS created_by_username,
                    p.updated_by_user_id,
                    uu.username AS updated_by_username,
                    p.created_at,
                    p.updated_at
                FROM customer_insurance_policies p
                JOIN customers c ON p.customer_id = c.id
                JOIN insurance_providers ip ON p.provider_id = ip.id
                LEFT JOIN users cu ON p.created_by_user_id = cu.id
                LEFT JOIN users uu ON p.updated_by_user_id = uu.id
                WHERE 1 = 1
            """
            params: List[Any] = []

            if customer_id is not None:
                try:
                    params.append(int(customer_id))
                    sql += " AND p.customer_id = ?"
                except (TypeError, ValueError):
                    return []

            if provider_id is not None:
                try:
                    params.append(int(provider_id))
                    sql += " AND p.provider_id = ?"
                except (TypeError, ValueError):
                    return []

            if status:
                safe_status = self._validate_status(status)
                sql += " AND p.status = ?"
                params.append(safe_status)

            if default_only:
                sql += " AND p.is_default = 1"

            sql += """
                ORDER BY
                    p.is_default DESC,
                    COALESCE(p.valid_to, '9999-12-31') ASC,
                    p.created_at DESC,
                    p.id DESC
            """

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to load insurance policies.")
            return []
        finally:
            conn.close()

    def get_customer_policies(self, customer_id: Any, active_only: bool = False) -> List[Dict[str, Any]]:
        status = "active" if active_only else None
        return self.get_all_policies(customer_id=customer_id, status=status)

    def get_customer_active_policies(self, customer_id: Any) -> List[Dict[str, Any]]:
        return self.get_customer_policies(customer_id=customer_id, active_only=True)

    def get_customer_default_policy(
        self,
        customer_id: Any,
        currently_usable_only: bool = False
    ) -> Optional[Dict[str, Any]]:
        policies = self.get_all_policies(customer_id=customer_id, default_only=True)

        if currently_usable_only:
            policies = [p for p in policies if self._is_policy_currently_valid(p)]

        return policies[0] if policies else None

    def get_currently_usable_policies_for_customer(self, customer_id: Any) -> List[Dict[str, Any]]:
        policies = self.get_customer_active_policies(customer_id)
        usable = [p for p in policies if self._is_policy_currently_valid(p)]

        usable.sort(
            key=lambda x: (
                0 if int(x.get("is_default", 0) or 0) == 1 else 1,
                x.get("valid_to") or "9999-12-31",
                -(x.get("id") or 0)
            )
        )
        return usable

    def get_policy_combo_items_for_customer(self, customer_id: Any) -> List[Dict[str, Any]]:
        """
        دالة مساعدة للواجهات:
        ترجع الوثائق الفعالة والقابلة للاستخدام حالياً فقط.
        """
        items = self.get_currently_usable_policies_for_customer(customer_id)

        return [
            {
                "id": item["id"],
                "provider_name": item["provider_name"],
                "provider_code": item.get("provider_code"),
                "policy_number": item["policy_number"],
                "member_number": item.get("member_number"),
                "default_coverage_percent": item["default_coverage_percent"],
                "default_patient_share_percent": item["default_patient_share_percent"],
                "coverage_limit_amount": item.get("coverage_limit_amount"),
                "is_default": item["is_default"]
            }
            for item in items
        ]

    def search_policies(
        self,
        keyword: Any,
        customer_id: Optional[Any] = None,
        provider_id: Optional[Any] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        safe_keyword = self._normalize_text(keyword)
        if not safe_keyword:
            return self.get_all_policies(
                customer_id=customer_id,
                provider_id=provider_id,
                status=status
            )

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    p.id,
                    p.customer_id,
                    c.name AS customer_name,
                    COALESCE(c.is_active, 1) AS customer_is_active,
                    p.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ip.is_active AS provider_is_active,
                    p.policy_number,
                    p.member_number,
                    p.default_coverage_percent,
                    p.default_patient_share_percent,
                    p.coverage_limit_amount,
                    p.valid_from,
                    p.valid_to,
                    p.status,
                    p.is_default,
                    p.notes,
                    p.created_by_user_id,
                    cu.username AS created_by_username,
                    p.updated_by_user_id,
                    uu.username AS updated_by_username,
                    p.created_at,
                    p.updated_at
                FROM customer_insurance_policies p
                JOIN customers c ON p.customer_id = c.id
                JOIN insurance_providers ip ON p.provider_id = ip.id
                LEFT JOIN users cu ON p.created_by_user_id = cu.id
                LEFT JOIN users uu ON p.updated_by_user_id = uu.id
                WHERE (
                    p.policy_number LIKE ?
                    OR COALESCE(p.member_number, '') LIKE ?
                    OR c.name LIKE ?
                    OR ip.name LIKE ?
                    OR COALESCE(ip.code, '') LIKE ?
                    OR COALESCE(p.notes, '') LIKE ?
                )
            """
            params: List[Any] = [f"%{safe_keyword}%"] * 6

            if customer_id is not None:
                try:
                    sql += " AND p.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            if provider_id is not None:
                try:
                    sql += " AND p.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if status:
                safe_status = self._validate_status(status)
                sql += " AND p.status = ?"
                params.append(safe_status)

            sql += """
                ORDER BY
                    p.is_default DESC,
                    COALESCE(p.valid_to, '9999-12-31') ASC,
                    p.created_at DESC,
                    p.id DESC
            """

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to search insurance policies with keyword=%s", safe_keyword)
            return []
        finally:
            conn.close()

    # ==========================================
    # Write API
    # ==========================================
    def create_policy(
        self,
        customer_id: Any,
        provider_id: Any,
        policy_number: Any,
        member_number: Any = None,
        default_coverage_percent: Any = None,
        default_patient_share_percent: Any = None,
        coverage_limit_amount: Any = None,
        valid_from: Any = None,
        valid_to: Any = None,
        status: Any = "active",
        is_default: Any = 0,
        notes: Any = None,
        created_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_created_by_user_id = self._parse_int_id(created_by_user_id, "معرف المستخدم المنشئ")

            payload = self._validate_payload(
                customer_id=customer_id,
                provider_id=provider_id,
                policy_number=policy_number,
                member_number=member_number,
                default_coverage_percent=default_coverage_percent,
                default_patient_share_percent=default_patient_share_percent,
                coverage_limit_amount=coverage_limit_amount,
                valid_from=valid_from,
                valid_to=valid_to,
                status=status,
                is_default=is_default,
                notes=notes
            )

            if not self._user_exists(cursor, safe_created_by_user_id):
                conn.rollback()
                return False, "المستخدم المنشئ غير موجود في النظام."

            if not self._customer_exists(cursor, payload["customer_id"]):
                conn.rollback()
                return False, "العميل/المريض المرتبط بالوثيقة غير موجود أو غير فعال."

            if not self._provider_exists_and_active(cursor, payload["provider_id"]):
                conn.rollback()
                return False, "مزود التأمين غير موجود أو غير فعال."

            if self._policy_number_exists(cursor, payload["provider_id"], payload["policy_number"]):
                conn.rollback()
                return False, "رقم الوثيقة مستخدم مسبقاً لدى مزود التأمين نفسه."

            if self._member_number_exists(cursor, payload["provider_id"], payload["member_number"]):
                conn.rollback()
                return False, "رقم العضوية مستخدم مسبقاً لدى مزود التأمين نفسه."

            if payload["is_default"] == 1 and payload["status"] == "active":
                self._unset_other_default_policies(
                    cursor=cursor,
                    customer_id=payload["customer_id"],
                    exclude_policy_id=None,
                    updated_by_user_id=safe_created_by_user_id
                )

            cursor.execute("""
                INSERT INTO customer_insurance_policies (
                    customer_id,
                    provider_id,
                    policy_number,
                    member_number,
                    default_coverage_percent,
                    default_patient_share_percent,
                    coverage_limit_amount,
                    valid_from,
                    valid_to,
                    status,
                    is_default,
                    notes,
                    created_by_user_id,
                    updated_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                payload["customer_id"],
                payload["provider_id"],
                payload["policy_number"],
                payload["member_number"],
                payload["default_coverage_percent"],
                payload["default_patient_share_percent"],
                payload["coverage_limit_amount"],
                payload["valid_from"],
                payload["valid_to"],
                payload["status"],
                payload["is_default"],
                payload["notes"],
                safe_created_by_user_id,
                None
            ))

            policy_id = cursor.lastrowid
            new_state = self._get_policy_by_id_with_cursor(cursor, policy_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_created_by_user_id,
                action="INSERT",
                table_name="customer_insurance_policies",
                record_id=policy_id,
                old_values=None,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "policy_id": policy_id,
                "message": f"تم إنشاء وثيقة التأمين ({payload['policy_number']}) بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while creating customer insurance policy.")
            return False, f"فشل حفظ الوثيقة بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while creating customer insurance policy.")
            return False, "حدث خطأ داخلي غير متوقع أثناء إنشاء وثيقة التأمين."
        finally:
            conn.close()

    def update_policy(
        self,
        policy_id: Any,
        customer_id: Any,
        provider_id: Any,
        policy_number: Any,
        member_number: Any = None,
        default_coverage_percent: Any = None,
        default_patient_share_percent: Any = None,
        coverage_limit_amount: Any = None,
        valid_from: Any = None,
        valid_to: Any = None,
        status: Any = "active",
        is_default: Any = 0,
        notes: Any = None,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            policy_id = int(policy_id)
        except (TypeError, ValueError):
            return False, "معرف الوثيقة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = None
            if updated_by_user_id is not None:
                safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
                if not self._user_exists(cursor, safe_updated_by_user_id):
                    conn.rollback()
                    return False, "المستخدم المعدّل غير موجود في النظام."

            old_state = self._get_policy_by_id_with_cursor(cursor, policy_id)
            if not old_state:
                conn.rollback()
                return False, "وثيقة التأمين المطلوبة غير موجودة."

            payload = self._validate_payload(
                customer_id=customer_id,
                provider_id=provider_id,
                policy_number=policy_number,
                member_number=member_number,
                default_coverage_percent=default_coverage_percent,
                default_patient_share_percent=default_patient_share_percent,
                coverage_limit_amount=coverage_limit_amount,
                valid_from=valid_from,
                valid_to=valid_to,
                status=status,
                is_default=is_default,
                notes=notes
            )

            if not self._customer_exists(cursor, payload["customer_id"]):
                conn.rollback()
                return False, "العميل/المريض المرتبط بالوثيقة غير موجود أو غير فعال."

            if not self._provider_exists_and_active(cursor, payload["provider_id"]):
                conn.rollback()
                return False, "مزود التأمين غير موجود أو غير فعال."

            if self._policy_number_exists(
                cursor,
                payload["provider_id"],
                payload["policy_number"],
                exclude_id=policy_id
            ):
                conn.rollback()
                return False, "رقم الوثيقة مستخدم لدى وثيقة أخرى ضمن مزود التأمين نفسه."

            if self._member_number_exists(
                cursor,
                payload["provider_id"],
                payload["member_number"],
                exclude_id=policy_id
            ):
                conn.rollback()
                return False, "رقم العضوية مستخدم لدى وثيقة أخرى ضمن مزود التأمين نفسه."

            if payload["is_default"] == 1 and payload["status"] == "active":
                self._unset_other_default_policies(
                    cursor=cursor,
                    customer_id=payload["customer_id"],
                    exclude_policy_id=policy_id,
                    updated_by_user_id=safe_updated_by_user_id
                )

            cursor.execute("""
                UPDATE customer_insurance_policies
                SET
                    customer_id = ?,
                    provider_id = ?,
                    policy_number = ?,
                    member_number = ?,
                    default_coverage_percent = ?,
                    default_patient_share_percent = ?,
                    coverage_limit_amount = ?,
                    valid_from = ?,
                    valid_to = ?,
                    status = ?,
                    is_default = ?,
                    notes = ?,
                    updated_by_user_id = ?
                WHERE id = ?
            """, (
                payload["customer_id"],
                payload["provider_id"],
                payload["policy_number"],
                payload["member_number"],
                payload["default_coverage_percent"],
                payload["default_patient_share_percent"],
                payload["coverage_limit_amount"],
                payload["valid_from"],
                payload["valid_to"],
                payload["status"],
                payload["is_default"],
                payload["notes"],
                safe_updated_by_user_id,
                policy_id
            ))

            new_state = self._get_policy_by_id_with_cursor(cursor, policy_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="customer_insurance_policies",
                record_id=policy_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "policy_id": policy_id,
                "message": f"تم تحديث وثيقة التأمين ({payload['policy_number']}) بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while updating customer insurance policy.")
            return False, f"فشل تحديث الوثيقة بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while updating customer insurance policy id=%s", policy_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تحديث وثيقة التأمين."
        finally:
            conn.close()

    def set_policy_status(
        self,
        policy_id: Any,
        new_status: Any,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            policy_id = int(policy_id)
        except (TypeError, ValueError):
            return False, "معرف الوثيقة غير صالح."

        try:
            safe_status = self._validate_status(new_status)
        except ValueError as ve:
            return False, str(ve)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = None
            if updated_by_user_id is not None:
                safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
                if not self._user_exists(cursor, safe_updated_by_user_id):
                    conn.rollback()
                    return False, "المستخدم المعدّل غير موجود في النظام."

            old_state = self._get_policy_by_id_with_cursor(cursor, policy_id)
            if not old_state:
                conn.rollback()
                return False, "وثيقة التأمين المطلوبة غير موجودة."

            if old_state["status"] == safe_status:
                conn.rollback()
                return False, "حالة الوثيقة مطابقة بالفعل ولا يوجد تغيير مطلوب."

            if safe_status != "active":
                cursor.execute("""
                    UPDATE customer_insurance_policies
                    SET
                        status = ?,
                        is_default = 0,
                        updated_by_user_id = ?
                    WHERE id = ?
                """, (safe_status, safe_updated_by_user_id, policy_id))
            else:
                cursor.execute("""
                    UPDATE customer_insurance_policies
                    SET
                        status = ?,
                        updated_by_user_id = ?
                    WHERE id = ?
                """, (safe_status, safe_updated_by_user_id, policy_id))

            new_state = self._get_policy_by_id_with_cursor(cursor, policy_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="customer_insurance_policies",
                record_id=policy_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "policy_id": policy_id,
                "message": f"تم تحديث حالة الوثيقة إلى ({safe_status}) بنجاح."
            }

        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while changing customer insurance policy status id=%s", policy_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تغيير حالة الوثيقة."
        finally:
            conn.close()

    def set_default_policy(
        self,
        policy_id: Any,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            policy_id = int(policy_id)
        except (TypeError, ValueError):
            return False, "معرف الوثيقة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = None
            if updated_by_user_id is not None:
                safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
                if not self._user_exists(cursor, safe_updated_by_user_id):
                    conn.rollback()
                    return False, "المستخدم المعدّل غير موجود في النظام."

            old_state = self._get_policy_by_id_with_cursor(cursor, policy_id)
            if not old_state:
                conn.rollback()
                return False, "وثيقة التأمين المطلوبة غير موجودة."

            if old_state["status"] != "active":
                conn.rollback()
                return False, "لا يمكن جعل وثيقة غير فعالة وثيقة افتراضية."

            self._unset_other_default_policies(
                cursor=cursor,
                customer_id=int(old_state["customer_id"]),
                exclude_policy_id=policy_id,
                updated_by_user_id=safe_updated_by_user_id
            )

            cursor.execute("""
                UPDATE customer_insurance_policies
                SET
                    is_default = 1,
                    updated_by_user_id = ?
                WHERE id = ?
            """, (safe_updated_by_user_id, policy_id))

            new_state = self._get_policy_by_id_with_cursor(cursor, policy_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="customer_insurance_policies",
                record_id=policy_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "policy_id": policy_id,
                "message": "تم تعيين الوثيقة كوثيقة افتراضية بنجاح."
            }

        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while setting default insurance policy id=%s", policy_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تعيين الوثيقة الافتراضية."
        finally:
            conn.close()

    def clear_default_policy(
        self,
        policy_id: Any,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            policy_id = int(policy_id)
        except (TypeError, ValueError):
            return False, "معرف الوثيقة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = None
            if updated_by_user_id is not None:
                safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
                if not self._user_exists(cursor, safe_updated_by_user_id):
                    conn.rollback()
                    return False, "المستخدم المعدّل غير موجود في النظام."

            old_state = self._get_policy_by_id_with_cursor(cursor, policy_id)
            if not old_state:
                conn.rollback()
                return False, "وثيقة التأمين المطلوبة غير موجودة."

            if int(old_state.get("is_default", 0) or 0) != 1:
                conn.rollback()
                return False, "هذه الوثيقة ليست افتراضية أصلاً."

            cursor.execute("""
                UPDATE customer_insurance_policies
                SET
                    is_default = 0,
                    updated_by_user_id = ?
                WHERE id = ?
            """, (safe_updated_by_user_id, policy_id))

            new_state = self._get_policy_by_id_with_cursor(cursor, policy_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="customer_insurance_policies",
                record_id=policy_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "policy_id": policy_id,
                "message": "تم إلغاء وسم الوثيقة كوثيقة افتراضية."
            }

        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while clearing default insurance policy id=%s", policy_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء إلغاء الوثيقة الافتراضية."
        finally:
            conn.close()

    def suspend_policy(self, policy_id: Any, updated_by_user_id: Any = None) -> Tuple[bool, Any]:
        return self.set_policy_status(policy_id, "suspended", updated_by_user_id)

    def expire_policy(self, policy_id: Any, updated_by_user_id: Any = None) -> Tuple[bool, Any]:
        return self.set_policy_status(policy_id, "expired", updated_by_user_id)

    def cancel_policy(self, policy_id: Any, updated_by_user_id: Any = None) -> Tuple[bool, Any]:
        return self.set_policy_status(policy_id, "cancelled", updated_by_user_id)

    def activate_policy(self, policy_id: Any, updated_by_user_id: Any = None) -> Tuple[bool, Any]:
        return self.set_policy_status(policy_id, "active", updated_by_user_id)

    # ==========================================
    # Operational Helper for Future Claims Flow
    # ==========================================
    def resolve_usable_policy(
        self,
        customer_id: Any,
        policy_id: Optional[Any] = None,
        provider_id: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        دالة عملية ستفيدنا لاحقاً في مسار المطالبات:
        - إذا تم تمرير policy_id: نتحقق منها مباشرة
        - إذا تم تمرير provider_id فقط: نبحث عن وثيقة صالحة لهذا المزود
        - إذا لم يُمرر شيء: نعيد الوثيقة الافتراضية الصالحة إن وجدت، وإلا أول وثيقة صالحة
        """
        try:
            customer_id = int(customer_id)
        except (TypeError, ValueError):
            return None

        if provider_id is not None:
            try:
                provider_id = int(provider_id)
            except (TypeError, ValueError):
                return None

        if policy_id is not None:
            policy = self.get_policy_by_id(policy_id)
            if not policy:
                return None
            if int(policy["customer_id"]) != customer_id:
                return None
            if provider_id is not None and int(policy["provider_id"]) != provider_id:
                return None
            if not self._is_policy_currently_valid(policy):
                return None
            return policy

        usable_policies = self.get_currently_usable_policies_for_customer(customer_id)

        if provider_id is not None:
            usable_policies = [
                p for p in usable_policies
                if int(p["provider_id"]) == provider_id
            ]

        if not usable_policies:
            return None

        default_policy = next(
            (p for p in usable_policies if int(p.get("is_default", 0) or 0) == 1),
            None
        )
        return default_policy or usable_policies[0]