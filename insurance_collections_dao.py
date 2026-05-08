"""
وظيفة الملف: طبقة الوصول للبيانات الخاصة بتحصيلات المطالبات التأمينية
(Insurance Collections DAO).
الطبقة: Data Access Layer

ملاحظات معمارية:
- هذا الملف يدير تسجيل التحصيلات التأمينية وربطها بالمطالبة وبجدول transactions.
- متوافق مع مخطط V27 الفعلي فقط.
- جميع عمليات الكتابة تتم ضمن BEGIN IMMEDIATE.
- يعتمد مبدأ عدم القابلية للتلاعب (Immutability): لا يوجد تعديل أو حذف للتحصيل بعد اعتماده.
- التحصيل النقدي (cash) يتطلب وردية مفتوحة صالحة.
- التحصيل غير النقدي يمكن تسجيله بدون shift_id، مع السماح بربطه بورديّة إذا لزم.
- كل عملية تحصيل تنشئ قيد حركة مالية واردة في transactions:
    transaction_type = 'in'
    reference_type   = 'insurance_collection'
- بعد كل تحصيل يتم فحص الرصيد المتبقي على المطالبة:
    إذا اكتمل التحصيل المعتمد -> تتحول حالة المطالبة إلى collected
- يدعم التدقيق audit_logs على:
    1) insurance_collections
    2) transactions
    3) insurance_claims عند تغير حالتها
"""

import json
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Any, Dict, List, Tuple

from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class InsuranceCollectionsDAO:
    ALLOWED_PAYMENT_METHODS = {"cash", "bank_transfer", "check", "other"}
    COLLECTIBLE_CLAIM_STATUSES = {"approved", "partially_approved", "collected"}

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
    # Generic Normalization / Validation
    # ==========================================
    def _normalize_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip()
        return value if value else None

    def _normalize_reference(self, value: Any) -> Optional[str]:
        safe = self._normalize_text(value)
        return safe.upper() if safe else None

    def _parse_int_id(self, value: Any, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} غير صالح.")
        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً موجباً.")
        return parsed

    def _parse_positive_amount(self, value: Any, field_name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون رقماً صالحاً.")
        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون أكبر من الصفر.")
        return round(parsed, 2)

    def _parse_optional_shift_id(self, value: Any) -> Optional[int]:
        if value is None or str(value).strip() == "":
            return None
        return self._parse_int_id(value, "معرف الوردية")

    def _parse_collection_date(self, value: Any) -> str:
        if value is None or str(value).strip() == "":
            return date.today().strftime("%Y-%m-%d")

        value = str(value).strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("تاريخ التحصيل يجب أن يكون بصيغة YYYY-MM-DD.")

        return value

    def _validate_payment_method(self, value: Any) -> str:
        safe = self._normalize_text(value)
        if not safe:
            return "bank_transfer"
        safe = safe.lower()
        if safe not in self.ALLOWED_PAYMENT_METHODS:
            raise ValueError("طريقة التحصيل غير صالحة.")
        return safe

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
    def _user_exists(self, cursor: sqlite3.Cursor, user_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM users
            WHERE id = ?
            LIMIT 1
        """, (user_id,))
        return cursor.fetchone() is not None

    def _shift_exists_and_open(self, cursor: sqlite3.Cursor, shift_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM shifts
            WHERE id = ?
              AND status = 'open'
            LIMIT 1
        """, (shift_id,))
        return cursor.fetchone() is not None

    def _collection_reference_exists(
        self,
        cursor: sqlite3.Cursor,
        collection_reference: str
    ) -> bool:
        cursor.execute("""
            SELECT 1
            FROM insurance_collections
            WHERE UPPER(TRIM(collection_reference)) = UPPER(TRIM(?))
            LIMIT 1
        """, (collection_reference,))
        return cursor.fetchone() is not None

    def _get_claim_row(self, cursor: sqlite3.Cursor, claim_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                ic.*,
                ip.name AS provider_name,
                ip.code AS provider_code,
                c.name AS customer_name,
                cip.policy_number,
                cip.member_number
            FROM insurance_claims ic
            JOIN insurance_providers ip ON ic.provider_id = ip.id
            JOIN customers c ON ic.customer_id = c.id
            JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
            WHERE ic.id = ?
            LIMIT 1
        """, (claim_id,))
        return self._row_to_dict(cursor.fetchone())

    def _claim_allows_collection(self, claim_row: Dict[str, Any]) -> bool:
        if not claim_row:
            return False

        status = str(claim_row.get("status", "")).lower()
        if status not in self.COLLECTIBLE_CLAIM_STATUSES:
            return False

        approved_amount = round(float(claim_row.get("approved_amount") or 0.0), 2)
        collected_amount = round(float(claim_row.get("collected_amount") or 0.0), 2)

        if approved_amount <= 0:
            return False

        if collected_amount >= approved_amount:
            return False

        return True

    def _get_collection_by_id_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        collection_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                col.id,
                col.claim_id,
                ic.claim_number,
                ic.status AS claim_status,
                ic.provider_id,
                ip.name AS provider_name,
                ip.code AS provider_code,
                ic.customer_id,
                c.name AS customer_name,
                ic.policy_id,
                cip.policy_number,
                cip.member_number,
                col.collection_reference,
                col.collection_date,
                col.amount,
                col.payment_method,
                col.user_id,
                u.username,
                col.shift_id,
                col.notes,
                col.created_at
            FROM insurance_collections col
            JOIN insurance_claims ic ON col.claim_id = ic.id
            JOIN insurance_providers ip ON ic.provider_id = ip.id
            JOIN customers c ON ic.customer_id = c.id
            JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
            JOIN users u ON col.user_id = u.id
            WHERE col.id = ?
            LIMIT 1
        """, (collection_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_transaction_by_id_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        transaction_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                id,
                transaction_type,
                reference_type,
                reference_id,
                amount,
                user_id,
                shift_id,
                notes,
                created_at
            FROM transactions
            WHERE id = ?
            LIMIT 1
        """, (transaction_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_claim_remaining_collectible_amount(
        self,
        claim_row: Dict[str, Any]
    ) -> float:
        approved_amount = round(float(claim_row.get("approved_amount") or 0.0), 2)
        collected_amount = round(float(claim_row.get("collected_amount") or 0.0), 2)
        remaining = round(approved_amount - collected_amount, 2)
        return max(remaining, 0.0)

    def _sync_claim_collection_status(
        self,
        cursor: sqlite3.Cursor,
        claim_id: int,
        updated_by_user_id: int
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        old_claim = self._get_claim_row(cursor, claim_id)
        if not old_claim:
            return None, None, False

        approved_amount = round(float(old_claim.get("approved_amount") or 0.0), 2)
        collected_amount = round(float(old_claim.get("collected_amount") or 0.0), 2)

        target_status = old_claim["status"]
        if approved_amount > 0 and collected_amount >= approved_amount:
            target_status = "collected"
        else:
            if old_claim["status"] == "collected":
                # حماية من أي حالة شاذة لو كانت البيانات قد تغيرت لاحقاً
                if collected_amount < approved_amount:
                    target_status = "approved" if approved_amount == float(old_claim.get("insurer_amount") or 0.0) else "partially_approved"

        if target_status == old_claim["status"]:
            return old_claim, old_claim, False

        cursor.execute("""
            UPDATE insurance_claims
            SET
                status = ?,
                updated_by_user_id = ?
            WHERE id = ?
        """, (
            target_status,
            updated_by_user_id,
            claim_id
        ))

        new_claim = self._get_claim_row(cursor, claim_id)
        return old_claim, new_claim, True

    # ==========================================
    # Read API
    # ==========================================
    def get_collection_by_id(self, collection_id: Any) -> Optional[Dict[str, Any]]:
        try:
            collection_id = int(collection_id)
        except (TypeError, ValueError):
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            return self._get_collection_by_id_with_cursor(cursor, collection_id)
        except Exception:
            logger.exception("Failed to get insurance collection by id=%s", collection_id)
            return None
        finally:
            conn.close()

    def get_claim_collections(self, claim_id: Any) -> List[Dict[str, Any]]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return []

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    col.id,
                    col.claim_id,
                    ic.claim_number,
                    ic.status AS claim_status,
                    col.collection_reference,
                    col.collection_date,
                    col.amount,
                    col.payment_method,
                    col.user_id,
                    u.username,
                    col.shift_id,
                    col.notes,
                    col.created_at
                FROM insurance_collections col
                JOIN insurance_claims ic ON col.claim_id = ic.id
                JOIN users u ON col.user_id = u.id
                WHERE col.claim_id = ?
                ORDER BY col.collection_date DESC, col.id DESC
            """, (claim_id,))
            return self._rows_to_dicts(cursor.fetchall())
        except Exception:
            logger.exception("Failed to get collections for claim_id=%s", claim_id)
            return []
        finally:
            conn.close()

    def get_claim_collection_summary(self, claim_id: Any) -> Optional[Dict[str, Any]]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            claim_row = self._get_claim_row(cursor, claim_id)
            if not claim_row:
                return None

            remaining_amount = self._get_claim_remaining_collectible_amount(claim_row)

            return {
                "claim_id": claim_row["id"],
                "claim_number": claim_row["claim_number"],
                "claim_status": claim_row["status"],
                "provider_id": claim_row["provider_id"],
                "provider_name": claim_row["provider_name"],
                "customer_id": claim_row["customer_id"],
                "customer_name": claim_row["customer_name"],
                "policy_id": claim_row["policy_id"],
                "policy_number": claim_row["policy_number"],
                "approved_amount": round(float(claim_row.get("approved_amount") or 0.0), 2),
                "collected_amount": round(float(claim_row.get("collected_amount") or 0.0), 2),
                "remaining_amount": remaining_amount,
                "is_fully_collected": remaining_amount <= 0
            }
        except Exception:
            logger.exception("Failed to get claim collection summary for claim_id=%s", claim_id)
            return None
        finally:
            conn.close()

    def get_collectible_claims(
        self,
        provider_id: Optional[Any] = None,
        customer_id: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    ic.id,
                    ic.claim_number,
                    ic.status,
                    ic.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ic.customer_id,
                    c.name AS customer_name,
                    ic.policy_id,
                    cip.policy_number,
                    cip.member_number,
                    ic.approved_amount,
                    ic.collected_amount,
                    (ic.approved_amount - ic.collected_amount) AS remaining_amount,
                    ic.claim_date,
                    ic.created_at,
                    ic.updated_at
                FROM insurance_claims ic
                JOIN insurance_providers ip ON ic.provider_id = ip.id
                JOIN customers c ON ic.customer_id = c.id
                JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
                WHERE ic.status IN ('approved', 'partially_approved', 'collected')
                  AND COALESCE(ic.approved_amount, 0) > COALESCE(ic.collected_amount, 0)
            """
            params: List[Any] = []

            if provider_id is not None:
                try:
                    sql += " AND ic.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if customer_id is not None:
                try:
                    sql += " AND ic.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            sql += " ORDER BY ic.claim_date ASC, ic.id ASC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to load collectible claims.")
            return []
        finally:
            conn.close()

    def get_all_collections(
        self,
        claim_id: Optional[Any] = None,
        provider_id: Optional[Any] = None,
        customer_id: Optional[Any] = None,
        shift_id: Optional[Any] = None,
        payment_method: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    col.id,
                    col.claim_id,
                    ic.claim_number,
                    ic.status AS claim_status,
                    ic.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ic.customer_id,
                    c.name AS customer_name,
                    col.collection_reference,
                    col.collection_date,
                    col.amount,
                    col.payment_method,
                    col.user_id,
                    u.username,
                    col.shift_id,
                    col.notes,
                    col.created_at
                FROM insurance_collections col
                JOIN insurance_claims ic ON col.claim_id = ic.id
                JOIN insurance_providers ip ON ic.provider_id = ip.id
                JOIN customers c ON ic.customer_id = c.id
                JOIN users u ON col.user_id = u.id
                WHERE 1 = 1
            """
            params: List[Any] = []

            if claim_id is not None:
                try:
                    sql += " AND col.claim_id = ?"
                    params.append(int(claim_id))
                except (TypeError, ValueError):
                    return []

            if provider_id is not None:
                try:
                    sql += " AND ic.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if customer_id is not None:
                try:
                    sql += " AND ic.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            if shift_id is not None:
                try:
                    sql += " AND col.shift_id = ?"
                    params.append(int(shift_id))
                except (TypeError, ValueError):
                    return []

            if payment_method:
                safe_method = self._validate_payment_method(payment_method)
                sql += " AND col.payment_method = ?"
                params.append(safe_method)

            sql += " ORDER BY col.collection_date DESC, col.id DESC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to load insurance collections.")
            return []
        finally:
            conn.close()

    def search_collections(
        self,
        keyword: Any,
        provider_id: Optional[Any] = None,
        customer_id: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        safe_keyword = self._normalize_text(keyword)
        if not safe_keyword:
            return self.get_all_collections(
                provider_id=provider_id,
                customer_id=customer_id
            )

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    col.id,
                    col.claim_id,
                    ic.claim_number,
                    ic.status AS claim_status,
                    ic.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ic.customer_id,
                    c.name AS customer_name,
                    col.collection_reference,
                    col.collection_date,
                    col.amount,
                    col.payment_method,
                    col.user_id,
                    u.username,
                    col.shift_id,
                    col.notes,
                    col.created_at
                FROM insurance_collections col
                JOIN insurance_claims ic ON col.claim_id = ic.id
                JOIN insurance_providers ip ON ic.provider_id = ip.id
                JOIN customers c ON ic.customer_id = c.id
                JOIN users u ON col.user_id = u.id
                WHERE (
                    ic.claim_number LIKE ?
                    OR COALESCE(col.collection_reference, '') LIKE ?
                    OR c.name LIKE ?
                    OR ip.name LIKE ?
                    OR COALESCE(ip.code, '') LIKE ?
                    OR COALESCE(col.notes, '') LIKE ?
                    OR u.username LIKE ?
                )
            """
            params: List[Any] = [f"%{safe_keyword}%"] * 7

            if provider_id is not None:
                try:
                    sql += " AND ic.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if customer_id is not None:
                try:
                    sql += " AND ic.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            sql += " ORDER BY col.collection_date DESC, col.id DESC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to search insurance collections with keyword=%s", safe_keyword)
            return []
        finally:
            conn.close()

    # ==========================================
    # Write API
    # ==========================================
    def record_collection(
        self,
        claim_id: Any,
        amount: Any,
        user_id: Any,
        payment_method: Any = "bank_transfer",
        shift_id: Any = None,
        collection_reference: Any = None,
        collection_date: Any = None,
        notes: Any = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_claim_id = self._parse_int_id(claim_id, "معرف المطالبة")
            safe_user_id = self._parse_int_id(user_id, "معرف المستخدم")
            safe_amount = self._parse_positive_amount(amount, "مبلغ التحصيل")
            safe_payment_method = self._validate_payment_method(payment_method)
            safe_shift_id = self._parse_optional_shift_id(shift_id)
            safe_collection_reference = self._normalize_reference(collection_reference)
            safe_collection_date = self._parse_collection_date(collection_date)
            safe_notes = self._normalize_text(notes)

            if not self._user_exists(cursor, safe_user_id):
                conn.rollback()
                return False, "المستخدم المسؤول عن التحصيل غير موجود."

            claim_row = self._get_claim_row(cursor, safe_claim_id)
            if not claim_row:
                conn.rollback()
                return False, "المطالبة التأمينية غير موجودة."

            if not self._claim_allows_collection(claim_row):
                conn.rollback()
                return False, "هذه المطالبة غير قابلة للتحصيل حالياً."

            remaining_amount = self._get_claim_remaining_collectible_amount(claim_row)
            if safe_amount > remaining_amount:
                conn.rollback()
                return False, (
                    f"مبلغ التحصيل ({safe_amount:,.2f}) يتجاوز الرصيد المتبقي على المطالبة "
                    f"({remaining_amount:,.2f})."
                )

            if safe_payment_method == "cash":
                if safe_shift_id is None:
                    conn.rollback()
                    return False, "التحصيل النقدي يتطلب وردية مالية مفتوحة."
                if not self._shift_exists_and_open(cursor, safe_shift_id):
                    conn.rollback()
                    return False, "الوردية المحددة للتحصيل النقدي غير موجودة أو ليست مفتوحة."
            else:
                if safe_shift_id is not None and not self._shift_exists_and_open(cursor, safe_shift_id):
                    conn.rollback()
                    return False, "إذا تم تمرير وردية للتحصيل غير النقدي فيجب أن تكون وردية مفتوحة صالحة."

            if safe_collection_reference and self._collection_reference_exists(cursor, safe_collection_reference):
                conn.rollback()
                return False, "مرجع التحصيل مستخدم مسبقاً."

            cursor.execute("""
                INSERT INTO insurance_collections (
                    claim_id,
                    collection_reference,
                    collection_date,
                    amount,
                    payment_method,
                    user_id,
                    shift_id,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                safe_claim_id,
                safe_collection_reference,
                safe_collection_date,
                safe_amount,
                safe_payment_method,
                safe_user_id,
                safe_shift_id,
                safe_notes
            ))

            collection_id = cursor.lastrowid
            collection_state = self._get_collection_by_id_with_cursor(cursor, collection_id)

            tx_note_parts = [
                f"تحصيل تأميني للمطالبة {claim_row['claim_number']}"
            ]
            if safe_collection_reference:
                tx_note_parts.append(f"مرجع التحصيل: {safe_collection_reference}")
            if safe_notes:
                tx_note_parts.append(f"ملاحظات: {safe_notes}")

            tx_notes = " | ".join(tx_note_parts)

            cursor.execute("""
                INSERT INTO transactions (
                    transaction_type,
                    reference_type,
                    reference_id,
                    amount,
                    user_id,
                    shift_id,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                "in",
                "insurance_collection",
                collection_id,
                safe_amount,
                safe_user_id,
                safe_shift_id,
                tx_notes
            ))

            transaction_id = cursor.lastrowid
            transaction_state = self._get_transaction_by_id_with_cursor(cursor, transaction_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_user_id,
                action="INSERT",
                table_name="insurance_collections",
                record_id=collection_id,
                old_values=None,
                new_values=collection_state
            )

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_user_id,
                action="INSERT",
                table_name="transactions",
                record_id=transaction_id,
                old_values=None,
                new_values=transaction_state
            )

            old_claim_state, new_claim_state, status_changed = self._sync_claim_collection_status(
                cursor=cursor,
                claim_id=safe_claim_id,
                updated_by_user_id=safe_user_id
            )

            if status_changed and old_claim_state and new_claim_state:
                self._write_audit_log(
                    cursor=cursor,
                    user_id=safe_user_id,
                    action="UPDATE",
                    table_name="insurance_claims",
                    record_id=safe_claim_id,
                    old_values=old_claim_state,
                    new_values=new_claim_state
                )

            refreshed_claim = self._get_claim_row(cursor, safe_claim_id)
            refreshed_remaining = self._get_claim_remaining_collectible_amount(refreshed_claim)

            conn.commit()
            return True, {
                "collection_id": collection_id,
                "transaction_id": transaction_id,
                "claim_id": safe_claim_id,
                "claim_number": claim_row["claim_number"],
                "message": "تم تسجيل التحصيل التأميني وربطه بالحركة المالية بنجاح.",
                "claim_status": refreshed_claim["status"] if refreshed_claim else claim_row["status"],
                "collected_amount": round(float((refreshed_claim or {}).get("collected_amount", 0.0) or 0.0), 2),
                "remaining_amount": refreshed_remaining
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while recording insurance collection.")
            return False, f"فشل تسجيل التحصيل بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while recording insurance collection.")
            return False, "حدث خطأ داخلي غير متوقع أثناء تسجيل التحصيل التأميني."
        finally:
            conn.close()