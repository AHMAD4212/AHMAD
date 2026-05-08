"""
وظيفة الملف: طبقة الوصول للبيانات الخاصة بالمطالبات التأمينية
(Insurance Claims DAO).
الطبقة: Data Access Layer

ملاحظات معمارية:
- هذا الملف يدير دورة حياة المطالبة التأمينية ورؤوسها وعناصرها.
- متوافق مع مخطط V27 الفعلي فقط.
- جميع عمليات الكتابة تتم ضمن BEGIN IMMEDIATE.
- لا يحتوي أي منطق واجهات.
- يعيد احتساب إجماليات المطالبة من عناصرها دائماً كحقيقة وحيدة (SSOT).
- يدعم التدقيق (audit_logs) للإنشاء، التعديل، الحذف، وتغييرات الحالة.
- يمنع الازدواجية المنطقية في Claim Items المرتبطة بـ sale_item_id داخل المطالبات غير الملغاة/غير المرفوضة.
- لا يدير التحصيلات التأمينية نفسها، لكنه يقرأ أثرها ويمنع بعض العمليات إذا كانت المطالبة قد حُصّل منها.
"""

import json
import uuid
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Any, Dict, List, Tuple

from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class InsuranceClaimsDAO:
    ALLOWED_CLAIM_STATUSES = {
        "draft",
        "submitted",
        "approved",
        "partially_approved",
        "rejected",
        "collected",
        "cancelled"
    }

    ALLOWED_ITEM_APPROVAL_STATUSES = {
        "pending",
        "approved",
        "partial",
        "rejected"
    }

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

    def _parse_int_id(self, value: Any, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} غير صالح.")
        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً موجباً.")
        return parsed

    def _parse_positive_int(self, value: Any, field_name: str) -> int:
        parsed = self._parse_int_id(value, field_name)
        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون أكبر من الصفر.")
        return parsed

    def _parse_nonnegative_amount(self, value: Any, field_name: str) -> Optional[float]:
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون رقماً صالحاً.")
        if parsed < 0:
            raise ValueError(f"{field_name} لا يجوز أن يكون سالباً.")
        return round(parsed, 2)

    def _parse_required_date(self, value: Any, field_name: str) -> str:
        if value is None or str(value).strip() == "":
            return date.today().strftime("%Y-%m-%d")

        value = str(value).strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{field_name} يجب أن يكون بصيغة YYYY-MM-DD.")
        return value

    def _validate_claim_status(self, status: Any) -> str:
        safe_status = self._normalize_text(status)
        if not safe_status:
            raise ValueError("حالة المطالبة حقل إلزامي.")
        safe_status = safe_status.lower()
        if safe_status not in self.ALLOWED_CLAIM_STATUSES:
            raise ValueError("حالة المطالبة غير صالحة.")
        return safe_status

    def _validate_item_approval_status(self, status: Any) -> str:
        safe_status = self._normalize_text(status) or "pending"
        safe_status = safe_status.lower()
        if safe_status not in self.ALLOWED_ITEM_APPROVAL_STATUSES:
            raise ValueError("حالة اعتماد عنصر المطالبة غير صالحة.")
        return safe_status

    def _normalize_claim_number(self, claim_number: Any) -> str:
        safe = self._normalize_text(claim_number)
        if not safe:
            raise ValueError("رقم المطالبة حقل إلزامي.")
        return safe.upper()

    def _generate_claim_number(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = uuid.uuid4().hex[:8].upper()
        return f"CLM-{stamp}-{suffix}"

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

    def _get_policy_row(self, cursor: sqlite3.Cursor, policy_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                p.*,
                c.name AS customer_name,
                COALESCE(c.is_active, 1) AS customer_is_active,
                ip.name AS provider_name,
                ip.code AS provider_code,
                ip.is_active AS provider_is_active
            FROM customer_insurance_policies p
            JOIN customers c ON p.customer_id = c.id
            JOIN insurance_providers ip ON p.provider_id = ip.id
            WHERE p.id = ?
            LIMIT 1
        """, (policy_id,))
        return self._row_to_dict(cursor.fetchone())

    def _policy_covers_service_date(self, policy_row: Dict[str, Any], service_date_str: str) -> bool:
        if not policy_row:
            return False

        if int(policy_row.get("customer_is_active", 0) or 0) != 1:
            return False

        if int(policy_row.get("provider_is_active", 0) or 0) != 1:
            return False

        status = str(policy_row.get("status", "")).lower()
        if status in {"suspended", "cancelled"}:
            return False

        service_date = datetime.strptime(service_date_str, "%Y-%m-%d").date()

        valid_from = policy_row.get("valid_from")
        valid_to = policy_row.get("valid_to")

        if valid_from:
            start_obj = datetime.strptime(valid_from, "%Y-%m-%d").date()
            if service_date < start_obj:
                return False

        if valid_to:
            end_obj = datetime.strptime(valid_to, "%Y-%m-%d").date()
            if service_date > end_obj:
                return False

        return True

    def _get_sale_row(self, cursor: sqlite3.Cursor, sale_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT *
            FROM sales
            WHERE id = ?
            LIMIT 1
        """, (sale_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_prescription_row(self, cursor: sqlite3.Cursor, prescription_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT *
            FROM prescriptions
            WHERE id = ?
            LIMIT 1
        """, (prescription_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_sale_item_row(self, cursor: sqlite3.Cursor, sale_item_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                si.*,
                s.customer_id AS sale_customer_id,
                s.id AS parent_sale_id
            FROM sale_items si
            JOIN sales s ON si.sale_id = s.id
            WHERE si.id = ?
            LIMIT 1
        """, (sale_item_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_prescription_item_row(
        self,
        cursor: sqlite3.Cursor,
        prescription_item_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                pi.*,
                p.customer_id AS prescription_customer_id,
                p.id AS parent_prescription_id
            FROM prescription_items pi
            JOIN prescriptions p ON pi.prescription_id = p.id
            WHERE pi.id = ?
            LIMIT 1
        """, (prescription_item_id,))
        return self._row_to_dict(cursor.fetchone())

    def _medicine_exists(self, cursor: sqlite3.Cursor, medicine_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM medicines
            WHERE id = ?
            LIMIT 1
        """, (medicine_id,))
        return cursor.fetchone() is not None

    def _batch_exists_for_medicine(
        self,
        cursor: sqlite3.Cursor,
        batch_id: int,
        medicine_id: int
    ) -> bool:
        cursor.execute("""
            SELECT 1
            FROM batches
            WHERE id = ?
              AND medicine_id = ?
            LIMIT 1
        """, (batch_id, medicine_id))
        return cursor.fetchone() is not None

    def _claim_number_exists(
        self,
        cursor: sqlite3.Cursor,
        claim_number: str,
        exclude_id: Optional[int] = None
    ) -> bool:
        sql = """
            SELECT 1
            FROM insurance_claims
            WHERE UPPER(TRIM(claim_number)) = UPPER(TRIM(?))
        """
        params: List[Any] = [claim_number]

        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _sale_item_already_claimed_elsewhere(
        self,
        cursor: sqlite3.Cursor,
        sale_item_id: int,
        exclude_claim_item_id: Optional[int] = None
    ) -> bool:
        sql = """
            SELECT 1
            FROM insurance_claim_items ici
            JOIN insurance_claims ic ON ici.claim_id = ic.id
            WHERE ici.sale_item_id = ?
              AND ic.status NOT IN ('cancelled', 'rejected')
        """
        params: List[Any] = [sale_item_id]

        if exclude_claim_item_id is not None:
            sql += " AND ici.id <> ?"
            params.append(exclude_claim_item_id)

        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return cursor.fetchone() is not None

    def _claim_has_collections(self, cursor: sqlite3.Cursor, claim_id: int) -> bool:
        cursor.execute("""
            SELECT 1
            FROM insurance_collections
            WHERE claim_id = ?
            LIMIT 1
        """, (claim_id,))
        return cursor.fetchone() is not None

    def _get_claim_by_id_with_cursor(self, cursor: sqlite3.Cursor, claim_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                ic.id,
                ic.claim_number,
                ic.provider_id,
                ip.name AS provider_name,
                ip.code AS provider_code,
                ic.policy_id,
                cip.policy_number,
                cip.member_number,
                cip.default_coverage_percent,
                cip.default_patient_share_percent,
                cip.coverage_limit_amount,
                cip.valid_from,
                cip.valid_to,
                ic.customer_id,
                c.name AS customer_name,
                ic.prescription_id,
                p.prescription_number,
                ic.sale_id,
                ic.status,
                ic.service_date,
                ic.claim_date,
                ic.gross_amount,
                ic.insurer_amount,
                ic.patient_amount,
                ic.approved_amount,
                ic.collected_amount,
                ic.external_claim_number,
                ic.submission_notes,
                ic.decision_notes,
                ic.rejection_reason,
                ic.created_by_user_id,
                cu.username AS created_by_username,
                ic.updated_by_user_id,
                uu.username AS updated_by_username,
                ic.created_at,
                ic.updated_at
            FROM insurance_claims ic
            JOIN insurance_providers ip ON ic.provider_id = ip.id
            JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
            JOIN customers c ON ic.customer_id = c.id
            LEFT JOIN prescriptions p ON ic.prescription_id = p.id
            LEFT JOIN users cu ON ic.created_by_user_id = cu.id
            LEFT JOIN users uu ON ic.updated_by_user_id = uu.id
            WHERE ic.id = ?
            LIMIT 1
        """, (claim_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_claim_item_by_id_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        claim_item_id: int
    ) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                ici.*,
                m.name AS medicine_name,
                b.batch_number,
                ic.status AS claim_status,
                ic.id AS claim_id
            FROM insurance_claim_items ici
            JOIN insurance_claims ic ON ici.claim_id = ic.id
            JOIN medicines m ON ici.medicine_id = m.id
            LEFT JOIN batches b ON ici.batch_id = b.id
            WHERE ici.id = ?
            LIMIT 1
        """, (claim_item_id,))
        return self._row_to_dict(cursor.fetchone())

    def _get_claim_items_with_cursor(self, cursor: sqlite3.Cursor, claim_id: int) -> List[Dict[str, Any]]:
        cursor.execute("""
            SELECT
                ici.id,
                ici.claim_id,
                ici.sale_item_id,
                ici.prescription_item_id,
                ici.medicine_id,
                m.name AS medicine_name,
                ici.batch_id,
                b.batch_number,
                ici.quantity,
                ici.unit_price,
                ici.gross_amount,
                ici.covered_amount,
                ici.patient_amount,
                ici.approval_status,
                ici.rejection_reason,
                ici.notes
            FROM insurance_claim_items ici
            JOIN medicines m ON ici.medicine_id = m.id
            LEFT JOIN batches b ON ici.batch_id = b.id
            WHERE ici.claim_id = ?
            ORDER BY ici.id ASC
        """, (claim_id,))
        return self._rows_to_dicts(cursor.fetchall())

    def _claim_is_editable(self, claim_row: Dict[str, Any]) -> bool:
        return claim_row and claim_row.get("status") == "draft"

    def _claim_allows_decision(self, claim_row: Dict[str, Any]) -> bool:
        if not claim_row:
            return False
        return claim_row.get("status") not in {"cancelled", "collected"}

    # ==========================================
    # Financial Helpers
    # ==========================================
    def _recalculate_claim_totals(
        self,
        cursor: sqlite3.Cursor,
        claim_id: int,
        updated_by_user_id: Optional[int] = None
    ) -> Dict[str, float]:
        cursor.execute("""
            SELECT
                COALESCE(SUM(gross_amount), 0.0) AS gross_amount,
                COALESCE(SUM(covered_amount), 0.0) AS insurer_amount,
                COALESCE(SUM(patient_amount), 0.0) AS patient_amount,
                COALESCE(SUM(
                    CASE
                        WHEN approval_status IN ('approved', 'partial')
                            THEN covered_amount
                        ELSE 0.0
                    END
                ), 0.0) AS approved_amount
            FROM insurance_claim_items
            WHERE claim_id = ?
        """, (claim_id,))
        totals = self._row_to_dict(cursor.fetchone()) or {}

        gross_amount = round(float(totals.get("gross_amount", 0.0) or 0.0), 2)
        insurer_amount = round(float(totals.get("insurer_amount", 0.0) or 0.0), 2)
        patient_amount = round(float(totals.get("patient_amount", 0.0) or 0.0), 2)
        approved_amount = round(float(totals.get("approved_amount", 0.0) or 0.0), 2)

        cursor.execute("""
            UPDATE insurance_claims
            SET
                gross_amount = ?,
                insurer_amount = ?,
                patient_amount = ?,
                approved_amount = ?,
                updated_by_user_id = COALESCE(?, updated_by_user_id)
            WHERE id = ?
        """, (
            gross_amount,
            insurer_amount,
            patient_amount,
            approved_amount,
            updated_by_user_id,
            claim_id
        ))

        return {
            "gross_amount": gross_amount,
            "insurer_amount": insurer_amount,
            "patient_amount": patient_amount,
            "approved_amount": approved_amount
        }

    # ==========================================
    # Item Normalization / Validation
    # ==========================================
    def _normalize_claim_item_payload(
        self,
        cursor: sqlite3.Cursor,
        claim_row: Dict[str, Any],
        item_data: Dict[str, Any],
        exclude_claim_item_id: Optional[int] = None
    ) -> Dict[str, Any]:
        if not isinstance(item_data, dict):
            raise ValueError("عنصر المطالبة يجب أن يكون كائناً من نوع dict.")

        sale_item_id = item_data.get("sale_item_id")
        prescription_item_id = item_data.get("prescription_item_id")
        medicine_id = item_data.get("medicine_id")
        batch_id = item_data.get("batch_id")
        quantity = item_data.get("quantity")
        unit_price = item_data.get("unit_price")
        gross_amount = item_data.get("gross_amount")
        covered_amount = item_data.get("covered_amount")
        patient_amount = item_data.get("patient_amount")
        approval_status = item_data.get("approval_status", "pending")
        rejection_reason = self._normalize_text(item_data.get("rejection_reason"))
        notes = self._normalize_text(item_data.get("notes"))

        sale_item_row = None
        prescription_item_row = None

        if sale_item_id is not None and str(sale_item_id).strip() != "":
            sale_item_id = self._parse_int_id(sale_item_id, "معرف سطر البيع")
            sale_item_row = self._get_sale_item_row(cursor, sale_item_id)
            if not sale_item_row:
                raise ValueError("سطر البيع المرتبط بعنصر المطالبة غير موجود.")

            if claim_row.get("sale_id") is not None and int(sale_item_row["parent_sale_id"]) != int(claim_row["sale_id"]):
                raise ValueError("سطر البيع لا ينتمي إلى فاتورة البيع المرتبطة بهذه المطالبة.")

            if int(sale_item_row["sale_customer_id"]) != int(claim_row["customer_id"]):
                raise ValueError("سطر البيع لا ينتمي إلى العميل المرتبط بهذه المطالبة.")

            if self._sale_item_already_claimed_elsewhere(
                cursor,
                sale_item_id=sale_item_id,
                exclude_claim_item_id=exclude_claim_item_id
            ):
                raise ValueError("سطر البيع هذا مُستخدم مسبقاً في مطالبة نشطة/غير مرفوضة أخرى.")

        if prescription_item_id is not None and str(prescription_item_id).strip() != "":
            prescription_item_id = self._parse_int_id(prescription_item_id, "معرف سطر الوصفة")
            prescription_item_row = self._get_prescription_item_row(cursor, prescription_item_id)
            if not prescription_item_row:
                raise ValueError("سطر الوصفة المرتبط بعنصر المطالبة غير موجود.")

            if claim_row.get("prescription_id") is not None and int(prescription_item_row["parent_prescription_id"]) != int(claim_row["prescription_id"]):
                raise ValueError("سطر الوصفة لا ينتمي إلى الوصفة المرتبطة بهذه المطالبة.")

            if int(prescription_item_row["prescription_customer_id"]) != int(claim_row["customer_id"]):
                raise ValueError("سطر الوصفة لا ينتمي إلى العميل المرتبط بهذه المطالبة.")

        if sale_item_row:
            derived_medicine_id = int(sale_item_row["medicine_id"])
            derived_batch_id = int(sale_item_row["batch_id"]) if sale_item_row.get("batch_id") is not None else None
        elif prescription_item_row:
            derived_medicine_id = int(prescription_item_row["medicine_id"])
            derived_batch_id = None
        else:
            if medicine_id is None or str(medicine_id).strip() == "":
                raise ValueError("يجب تمرير medicine_id إذا لم يتم تمرير sale_item_id أو prescription_item_id.")
            derived_medicine_id = self._parse_int_id(medicine_id, "معرف الدواء")
            derived_batch_id = None

        if medicine_id is not None and str(medicine_id).strip() != "":
            medicine_id = self._parse_int_id(medicine_id, "معرف الدواء")
            if medicine_id != derived_medicine_id:
                raise ValueError("معرف الدواء المرسل لا يطابق المرجع المرتبط (سطر البيع/الوصفة).")
        else:
            medicine_id = derived_medicine_id

        if not self._medicine_exists(cursor, medicine_id):
            raise ValueError("الدواء المرتبط بعنصر المطالبة غير موجود.")

        if batch_id is not None and str(batch_id).strip() != "":
            batch_id = self._parse_int_id(batch_id, "معرف التشغيلة")
        else:
            batch_id = derived_batch_id

        if batch_id is not None and not self._batch_exists_for_medicine(cursor, batch_id, medicine_id):
            raise ValueError("التشغيلة المحددة لا تنتمي إلى الدواء المحدد.")

        quantity = self._parse_positive_int(quantity, "كمية عنصر المطالبة")

        if sale_item_row:
            max_qty = int(sale_item_row["quantity"])
            if quantity > max_qty:
                raise ValueError(f"كمية عنصر المطالبة تتجاوز كمية سطر البيع الأصلية ({max_qty}).")

        if prescription_item_row:
            max_qty = int(prescription_item_row["dispensed_qty"] or prescription_item_row["prescribed_qty"] or 0)
            if max_qty > 0 and quantity > max_qty:
                raise ValueError(f"كمية عنصر المطالبة تتجاوز الكمية المنطقية المسموحة للوصفة ({max_qty}).")

        parsed_unit_price = self._parse_nonnegative_amount(unit_price, "سعر الوحدة")
        parsed_gross = self._parse_nonnegative_amount(gross_amount, "الإجمالي الخام")
        parsed_covered = self._parse_nonnegative_amount(covered_amount, "المبلغ المغطى من شركة التأمين")
        parsed_patient = self._parse_nonnegative_amount(patient_amount, "حصة المريض")

        if parsed_unit_price is None and parsed_gross is None:
            if sale_item_row:
                fallback_price = sale_item_row.get("final_unit_price")
                if fallback_price is None:
                    fallback_price = sale_item_row.get("price_at_sale")
                parsed_unit_price = round(float(fallback_price or 0.0), 2)
            else:
                raise ValueError("يجب تمرير unit_price أو gross_amount لعنصر المطالبة غير المرتبط بسطر بيع.")

        if parsed_unit_price is None and parsed_gross is not None:
            parsed_unit_price = round(parsed_gross / quantity, 2)

        if parsed_gross is None and parsed_unit_price is not None:
            parsed_gross = round(parsed_unit_price * quantity, 2)

        if parsed_gross is None or parsed_unit_price is None:
            raise ValueError("تعذر اشتقاق قيم السعر لعنصر المطالبة.")

        policy_coverage = float(claim_row.get("default_coverage_percent") or 80.0)
        policy_patient_share = float(claim_row.get("default_patient_share_percent") or 20.0)

        if parsed_covered is None and parsed_patient is None:
            parsed_covered = round(parsed_gross * (policy_coverage / 100.0), 2)
            parsed_patient = round(parsed_gross - parsed_covered, 2)
        elif parsed_covered is not None and parsed_patient is None:
            parsed_patient = round(parsed_gross - parsed_covered, 2)
        elif parsed_covered is None and parsed_patient is not None:
            parsed_covered = round(parsed_gross - parsed_patient, 2)

        if parsed_covered is None or parsed_patient is None:
            raise ValueError("تعذر احتساب توزيع المبلغ بين شركة التأمين والمريض.")

        if parsed_covered < 0 or parsed_patient < 0:
            raise ValueError("قيم التغطية/حصة المريض لا يجوز أن تكون سالبة.")

        if round(parsed_covered + parsed_patient, 2) != round(parsed_gross, 2):
            raise ValueError("يجب أن يساوي مجموع المبلغ المغطى وحصة المريض الإجمالي الخام لعنصر المطالبة.")

        approval_status = self._validate_item_approval_status(approval_status)

        if approval_status == "rejected":
            parsed_covered = 0.0
            parsed_patient = round(parsed_gross, 2)
            if not rejection_reason:
                rejection_reason = "مرفوض تأمينياً"
        elif approval_status == "approved":
            if parsed_covered <= 0:
                raise ValueError("عنصر المطالبة الموافق عليه يجب أن يحتوي مبلغ تغطية أكبر من صفر.")
            rejection_reason = None
        elif approval_status == "partial":
            if parsed_covered <= 0 or parsed_covered >= parsed_gross:
                raise ValueError("العنصر المعتمد جزئياً يجب أن تكون قيمة التغطية فيه أكبر من صفر وأقل من الإجمالي الخام.")
            rejection_reason = None
        else:
            rejection_reason = None

        return {
            "sale_item_id": sale_item_id,
            "prescription_item_id": prescription_item_id,
            "medicine_id": medicine_id,
            "batch_id": batch_id,
            "quantity": quantity,
            "unit_price": round(parsed_unit_price, 2),
            "gross_amount": round(parsed_gross, 2),
            "covered_amount": round(parsed_covered, 2),
            "patient_amount": round(parsed_patient, 2),
            "approval_status": approval_status,
            "rejection_reason": rejection_reason,
            "notes": notes
        }

    # ==========================================
    # Read API
    # ==========================================
    def get_claim_by_id(self, claim_id: Any) -> Optional[Dict[str, Any]]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            claim = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not claim:
                return None
            claim["items"] = self._get_claim_items_with_cursor(cursor, claim_id)
            return claim
        except Exception:
            logger.exception("Failed to get insurance claim by id=%s", claim_id)
            return None
        finally:
            conn.close()

    def get_claim_items(self, claim_id: Any) -> List[Dict[str, Any]]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return []

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            return self._get_claim_items_with_cursor(cursor, claim_id)
        except Exception:
            logger.exception("Failed to load claim items for claim_id=%s", claim_id)
            return []
        finally:
            conn.close()

    def get_all_claims(
        self,
        customer_id: Optional[Any] = None,
        provider_id: Optional[Any] = None,
        policy_id: Optional[Any] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    ic.id,
                    ic.claim_number,
                    ic.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ic.policy_id,
                    cip.policy_number,
                    cip.member_number,
                    ic.customer_id,
                    c.name AS customer_name,
                    ic.prescription_id,
                    p.prescription_number,
                    ic.sale_id,
                    ic.status,
                    ic.service_date,
                    ic.claim_date,
                    ic.gross_amount,
                    ic.insurer_amount,
                    ic.patient_amount,
                    ic.approved_amount,
                    ic.collected_amount,
                    ic.external_claim_number,
                    ic.submission_notes,
                    ic.decision_notes,
                    ic.rejection_reason,
                    ic.created_by_user_id,
                    cu.username AS created_by_username,
                    ic.updated_by_user_id,
                    uu.username AS updated_by_username,
                    ic.created_at,
                    ic.updated_at,
                    (
                        SELECT COUNT(*)
                        FROM insurance_claim_items ici
                        WHERE ici.claim_id = ic.id
                    ) AS items_count
                FROM insurance_claims ic
                JOIN insurance_providers ip ON ic.provider_id = ip.id
                JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
                JOIN customers c ON ic.customer_id = c.id
                LEFT JOIN prescriptions p ON ic.prescription_id = p.id
                LEFT JOIN users cu ON ic.created_by_user_id = cu.id
                LEFT JOIN users uu ON ic.updated_by_user_id = uu.id
                WHERE 1 = 1
            """
            params: List[Any] = []

            if customer_id is not None:
                try:
                    sql += " AND ic.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            if provider_id is not None:
                try:
                    sql += " AND ic.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if policy_id is not None:
                try:
                    sql += " AND ic.policy_id = ?"
                    params.append(int(policy_id))
                except (TypeError, ValueError):
                    return []

            if status:
                safe_status = self._validate_claim_status(status)
                sql += " AND ic.status = ?"
                params.append(safe_status)

            sql += """
                ORDER BY ic.created_at DESC, ic.id DESC
            """

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to load insurance claims.")
            return []
        finally:
            conn.close()

    def search_claims(
        self,
        keyword: Any,
        customer_id: Optional[Any] = None,
        provider_id: Optional[Any] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        safe_keyword = self._normalize_text(keyword)
        if not safe_keyword:
            return self.get_all_claims(
                customer_id=customer_id,
                provider_id=provider_id,
                status=status
            )

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            sql = """
                SELECT
                    ic.id,
                    ic.claim_number,
                    ic.provider_id,
                    ip.name AS provider_name,
                    ip.code AS provider_code,
                    ic.policy_id,
                    cip.policy_number,
                    cip.member_number,
                    ic.customer_id,
                    c.name AS customer_name,
                    ic.prescription_id,
                    p.prescription_number,
                    ic.sale_id,
                    ic.status,
                    ic.service_date,
                    ic.claim_date,
                    ic.gross_amount,
                    ic.insurer_amount,
                    ic.patient_amount,
                    ic.approved_amount,
                    ic.collected_amount,
                    ic.external_claim_number,
                    ic.submission_notes,
                    ic.decision_notes,
                    ic.rejection_reason,
                    ic.created_at,
                    ic.updated_at
                FROM insurance_claims ic
                JOIN insurance_providers ip ON ic.provider_id = ip.id
                JOIN customer_insurance_policies cip ON ic.policy_id = cip.id
                JOIN customers c ON ic.customer_id = c.id
                LEFT JOIN prescriptions p ON ic.prescription_id = p.id
                WHERE (
                    ic.claim_number LIKE ?
                    OR COALESCE(ic.external_claim_number, '') LIKE ?
                    OR c.name LIKE ?
                    OR ip.name LIKE ?
                    OR COALESCE(ip.code, '') LIKE ?
                    OR COALESCE(cip.policy_number, '') LIKE ?
                    OR COALESCE(cip.member_number, '') LIKE ?
                )
            """
            params: List[Any] = [f"%{safe_keyword}%"] * 7

            if customer_id is not None:
                try:
                    sql += " AND ic.customer_id = ?"
                    params.append(int(customer_id))
                except (TypeError, ValueError):
                    return []

            if provider_id is not None:
                try:
                    sql += " AND ic.provider_id = ?"
                    params.append(int(provider_id))
                except (TypeError, ValueError):
                    return []

            if status:
                safe_status = self._validate_claim_status(status)
                sql += " AND ic.status = ?"
                params.append(safe_status)

            sql += " ORDER BY ic.created_at DESC, ic.id DESC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("Failed to search insurance claims with keyword=%s", safe_keyword)
            return []
        finally:
            conn.close()

    # ==========================================
    # Claim Creation / Update
    # ==========================================
    def create_claim(
        self,
        provider_id: Any,
        policy_id: Any,
        customer_id: Any,
        prescription_id: Any = None,
        sale_id: Any = None,
        service_date: Any = None,
        claim_number: Any = None,
        external_claim_number: Any = None,
        submission_notes: Any = None,
        created_by_user_id: Any = None,
        items: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Any]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_provider_id = self._parse_int_id(provider_id, "معرف مزود التأمين")
            safe_policy_id = self._parse_int_id(policy_id, "معرف الوثيقة التأمينية")
            safe_customer_id = self._parse_int_id(customer_id, "معرف العميل")
            safe_created_by_user_id = self._parse_int_id(created_by_user_id, "معرف المستخدم المنشئ")
            safe_service_date = self._parse_required_date(service_date, "تاريخ الخدمة")

            safe_claim_number = self._normalize_text(claim_number)
            safe_claim_number = self._normalize_claim_number(safe_claim_number) if safe_claim_number else self._generate_claim_number()

            safe_external_claim_number = self._normalize_text(external_claim_number)
            safe_submission_notes = self._normalize_text(submission_notes)

            safe_sale_id = None
            if sale_id is not None and str(sale_id).strip() != "":
                safe_sale_id = self._parse_int_id(sale_id, "معرف فاتورة البيع")

            safe_prescription_id = None
            if prescription_id is not None and str(prescription_id).strip() != "":
                safe_prescription_id = self._parse_int_id(prescription_id, "معرف الوصفة")

            if not self._user_exists(cursor, safe_created_by_user_id):
                conn.rollback()
                return False, "المستخدم المنشئ غير موجود في النظام."

            if not self._customer_exists(cursor, safe_customer_id):
                conn.rollback()
                return False, "العميل/المريض غير موجود أو غير فعال."

            if not self._provider_exists_and_active(cursor, safe_provider_id):
                conn.rollback()
                return False, "مزود التأمين غير موجود أو غير فعال."

            policy_row = self._get_policy_row(cursor, safe_policy_id)
            if not policy_row:
                conn.rollback()
                return False, "الوثيقة التأمينية غير موجودة."

            if int(policy_row["customer_id"]) != safe_customer_id:
                conn.rollback()
                return False, "الوثيقة التأمينية لا تنتمي إلى العميل المحدد."

            if int(policy_row["provider_id"]) != safe_provider_id:
                conn.rollback()
                return False, "الوثيقة التأمينية لا تنتمي إلى مزود التأمين المحدد."

            if not self._policy_covers_service_date(policy_row, safe_service_date):
                conn.rollback()
                return False, "الوثيقة التأمينية لا تغطي تاريخ الخدمة المحدد أو أنها غير صالحة تشغيلياً."

            if self._claim_number_exists(cursor, safe_claim_number):
                conn.rollback()
                return False, "رقم المطالبة مستخدم مسبقاً."

            if safe_sale_id is not None:
                sale_row = self._get_sale_row(cursor, safe_sale_id)
                if not sale_row:
                    conn.rollback()
                    return False, "فاتورة البيع المرجعية غير موجودة."
                if sale_row.get("customer_id") != safe_customer_id:
                    conn.rollback()
                    return False, "فاتورة البيع المرجعية لا تنتمي إلى العميل المحدد."

            if safe_prescription_id is not None:
                prescription_row = self._get_prescription_row(cursor, safe_prescription_id)
                if not prescription_row:
                    conn.rollback()
                    return False, "الوصفة المرجعية غير موجودة."
                if prescription_row.get("customer_id") != safe_customer_id:
                    conn.rollback()
                    return False, "الوصفة المرجعية لا تنتمي إلى العميل المحدد."

            cursor.execute("""
                INSERT INTO insurance_claims (
                    claim_number,
                    provider_id,
                    policy_id,
                    customer_id,
                    prescription_id,
                    sale_id,
                    status,
                    service_date,
                    external_claim_number,
                    submission_notes,
                    created_by_user_id,
                    updated_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, NULL)
            """, (
                safe_claim_number,
                safe_provider_id,
                safe_policy_id,
                safe_customer_id,
                safe_prescription_id,
                safe_sale_id,
                safe_service_date,
                safe_external_claim_number,
                safe_submission_notes,
                safe_created_by_user_id
            ))

            claim_id = cursor.lastrowid
            claim_row = self._get_claim_by_id_with_cursor(cursor, claim_id)
            claim_row["default_coverage_percent"] = policy_row["default_coverage_percent"]
            claim_row["default_patient_share_percent"] = policy_row["default_patient_share_percent"]

            if items:
                for item in items:
                    normalized_item = self._normalize_claim_item_payload(cursor, claim_row, item)
                    cursor.execute("""
                        INSERT INTO insurance_claim_items (
                            claim_id,
                            sale_item_id,
                            prescription_item_id,
                            medicine_id,
                            batch_id,
                            quantity,
                            unit_price,
                            gross_amount,
                            covered_amount,
                            patient_amount,
                            approval_status,
                            rejection_reason,
                            notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        claim_id,
                        normalized_item["sale_item_id"],
                        normalized_item["prescription_item_id"],
                        normalized_item["medicine_id"],
                        normalized_item["batch_id"],
                        normalized_item["quantity"],
                        normalized_item["unit_price"],
                        normalized_item["gross_amount"],
                        normalized_item["covered_amount"],
                        normalized_item["patient_amount"],
                        normalized_item["approval_status"],
                        normalized_item["rejection_reason"],
                        normalized_item["notes"]
                    ))

            self._recalculate_claim_totals(cursor, claim_id, updated_by_user_id=safe_created_by_user_id)

            new_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            new_state["items"] = self._get_claim_items_with_cursor(cursor, claim_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_created_by_user_id,
                action="INSERT",
                table_name="insurance_claims",
                record_id=claim_id,
                old_values=None,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "claim_id": claim_id,
                "claim_number": safe_claim_number,
                "message": f"تم إنشاء المطالبة التأمينية ({safe_claim_number}) بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while creating insurance claim.")
            return False, f"فشل إنشاء المطالبة بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while creating insurance claim.")
            return False, "حدث خطأ داخلي غير متوقع أثناء إنشاء المطالبة التأمينية."
        finally:
            conn.close()

    def update_claim_header(
        self,
        claim_id: Any,
        service_date: Any = None,
        external_claim_number: Any = None,
        submission_notes: Any = None,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return False, "معرف المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not old_state:
                conn.rollback()
                return False, "المطالبة المطلوبة غير موجودة."

            if not self._claim_is_editable(old_state):
                conn.rollback()
                return False, "لا يمكن تعديل رأس المطالبة بعد مغادرة حالة المسودة."

            safe_service_date = self._parse_required_date(service_date or old_state["service_date"], "تاريخ الخدمة")
            safe_external_claim_number = self._normalize_text(external_claim_number)
            safe_submission_notes = self._normalize_text(submission_notes)

            policy_row = self._get_policy_row(cursor, int(old_state["policy_id"]))
            if not policy_row or not self._policy_covers_service_date(policy_row, safe_service_date):
                conn.rollback()
                return False, "الوثيقة التأمينية لا تغطي تاريخ الخدمة الجديد."

            cursor.execute("""
                UPDATE insurance_claims
                SET
                    service_date = ?,
                    external_claim_number = ?,
                    submission_notes = ?,
                    updated_by_user_id = ?
                WHERE id = ?
            """, (
                safe_service_date,
                safe_external_claim_number,
                safe_submission_notes,
                safe_updated_by_user_id,
                claim_id
            ))

            new_state = self._get_claim_by_id_with_cursor(cursor, claim_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="insurance_claims",
                record_id=claim_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "claim_id": claim_id,
                "message": "تم تحديث بيانات رأس المطالبة بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while updating insurance claim header id=%s", claim_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تحديث رأس المطالبة."
        finally:
            conn.close()

    # ==========================================
    # Claim Items API
    # ==========================================
    def add_claim_item(
        self,
        claim_id: Any,
        item_data: Dict[str, Any],
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return False, "معرف المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            claim_row = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not claim_row:
                conn.rollback()
                return False, "المطالبة المطلوبة غير موجودة."

            if not self._claim_is_editable(claim_row):
                conn.rollback()
                return False, "لا يمكن إضافة عناصر إلى مطالبة ليست في حالة مسودة."

            normalized_item = self._normalize_claim_item_payload(cursor, claim_row, item_data)

            cursor.execute("""
                INSERT INTO insurance_claim_items (
                    claim_id,
                    sale_item_id,
                    prescription_item_id,
                    medicine_id,
                    batch_id,
                    quantity,
                    unit_price,
                    gross_amount,
                    covered_amount,
                    patient_amount,
                    approval_status,
                    rejection_reason,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                claim_id,
                normalized_item["sale_item_id"],
                normalized_item["prescription_item_id"],
                normalized_item["medicine_id"],
                normalized_item["batch_id"],
                normalized_item["quantity"],
                normalized_item["unit_price"],
                normalized_item["gross_amount"],
                normalized_item["covered_amount"],
                normalized_item["patient_amount"],
                normalized_item["approval_status"],
                normalized_item["rejection_reason"],
                normalized_item["notes"]
            ))

            claim_item_id = cursor.lastrowid
            item_state = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)

            self._recalculate_claim_totals(cursor, claim_id, updated_by_user_id=safe_updated_by_user_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="INSERT",
                table_name="insurance_claim_items",
                record_id=claim_item_id,
                old_values=None,
                new_values=item_state
            )

            conn.commit()
            return True, {
                "claim_item_id": claim_item_id,
                "message": "تمت إضافة عنصر المطالبة بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while adding insurance claim item.")
            return False, f"فشل إضافة عنصر المطالبة بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while adding insurance claim item to claim_id=%s", claim_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء إضافة عنصر المطالبة."
        finally:
            conn.close()

    def update_claim_item(
        self,
        claim_item_id: Any,
        item_data: Dict[str, Any],
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_item_id = int(claim_item_id)
        except (TypeError, ValueError):
            return False, "معرف عنصر المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_item_state = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)
            if not old_item_state:
                conn.rollback()
                return False, "عنصر المطالبة المطلوب غير موجود."

            claim_row = self._get_claim_by_id_with_cursor(cursor, int(old_item_state["claim_id"]))
            if not claim_row:
                conn.rollback()
                return False, "المطالبة الأم غير موجودة."

            if not self._claim_is_editable(claim_row):
                conn.rollback()
                return False, "لا يمكن تعديل عناصر مطالبة ليست في حالة مسودة."

            normalized_item = self._normalize_claim_item_payload(
                cursor,
                claim_row,
                item_data,
                exclude_claim_item_id=claim_item_id
            )

            cursor.execute("""
                UPDATE insurance_claim_items
                SET
                    sale_item_id = ?,
                    prescription_item_id = ?,
                    medicine_id = ?,
                    batch_id = ?,
                    quantity = ?,
                    unit_price = ?,
                    gross_amount = ?,
                    covered_amount = ?,
                    patient_amount = ?,
                    approval_status = ?,
                    rejection_reason = ?,
                    notes = ?
                WHERE id = ?
            """, (
                normalized_item["sale_item_id"],
                normalized_item["prescription_item_id"],
                normalized_item["medicine_id"],
                normalized_item["batch_id"],
                normalized_item["quantity"],
                normalized_item["unit_price"],
                normalized_item["gross_amount"],
                normalized_item["covered_amount"],
                normalized_item["patient_amount"],
                normalized_item["approval_status"],
                normalized_item["rejection_reason"],
                normalized_item["notes"],
                claim_item_id
            ))

            new_item_state = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)

            self._recalculate_claim_totals(
                cursor,
                int(old_item_state["claim_id"]),
                updated_by_user_id=safe_updated_by_user_id
            )

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="insurance_claim_items",
                record_id=claim_item_id,
                old_values=old_item_state,
                new_values=new_item_state
            )

            conn.commit()
            return True, {
                "claim_item_id": claim_item_id,
                "message": "تم تحديث عنصر المطالبة بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except sqlite3.IntegrityError as ie:
            conn.rollback()
            logger.exception("Integrity error while updating insurance claim item.")
            return False, f"فشل تحديث عنصر المطالبة بسبب قيد تكاملي: {str(ie)}"
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while updating insurance claim item id=%s", claim_item_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء تحديث عنصر المطالبة."
        finally:
            conn.close()

    def delete_claim_item(
        self,
        claim_item_id: Any,
        updated_by_user_id: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_item_id = int(claim_item_id)
        except (TypeError, ValueError):
            return False, "معرف عنصر المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_item_state = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)
            if not old_item_state:
                conn.rollback()
                return False, "عنصر المطالبة المطلوب غير موجود."

            claim_row = self._get_claim_by_id_with_cursor(cursor, int(old_item_state["claim_id"]))
            if not claim_row:
                conn.rollback()
                return False, "المطالبة الأم غير موجودة."

            if not self._claim_is_editable(claim_row):
                conn.rollback()
                return False, "لا يمكن حذف عناصر من مطالبة ليست في حالة مسودة."

            cursor.execute("DELETE FROM insurance_claim_items WHERE id = ?", (claim_item_id,))

            self._recalculate_claim_totals(
                cursor,
                int(old_item_state["claim_id"]),
                updated_by_user_id=safe_updated_by_user_id
            )

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="DELETE",
                table_name="insurance_claim_items",
                record_id=claim_item_id,
                old_values=old_item_state,
                new_values=None
            )

            conn.commit()
            return True, {
                "claim_item_id": claim_item_id,
                "message": "تم حذف عنصر المطالبة بنجاح."
            }

        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while deleting insurance claim item id=%s", claim_item_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء حذف عنصر المطالبة."
        finally:
            conn.close()

    # ==========================================
    # Claim Workflow
    # ==========================================
    def submit_claim(
        self,
        claim_id: Any,
        updated_by_user_id: Any = None,
        external_claim_number: Any = None,
        submission_notes: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return False, "معرف المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not old_state:
                conn.rollback()
                return False, "المطالبة المطلوبة غير موجودة."

            if old_state["status"] != "draft":
                conn.rollback()
                return False, "لا يمكن إرسال المطالبة إلا من حالة المسودة."

            items = self._get_claim_items_with_cursor(cursor, claim_id)
            if not items:
                conn.rollback()
                return False, "لا يمكن إرسال مطالبة فارغة بدون عناصر."

            totals = self._recalculate_claim_totals(cursor, claim_id, updated_by_user_id=safe_updated_by_user_id)
            if totals["gross_amount"] <= 0:
                conn.rollback()
                return False, "إجمالي المطالبة صفر، لا يمكن إرسالها."

            safe_external_claim_number = self._normalize_text(external_claim_number)
            safe_submission_notes = self._normalize_text(submission_notes)

            cursor.execute("""
                UPDATE insurance_claims
                SET
                    status = 'submitted',
                    external_claim_number = COALESCE(?, external_claim_number),
                    submission_notes = COALESCE(?, submission_notes),
                    rejection_reason = NULL,
                    updated_by_user_id = ?
                WHERE id = ?
            """, (
                safe_external_claim_number,
                safe_submission_notes,
                safe_updated_by_user_id,
                claim_id
            ))

            new_state = self._get_claim_by_id_with_cursor(cursor, claim_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="insurance_claims",
                record_id=claim_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "claim_id": claim_id,
                "message": "تم إرسال المطالبة التأمينية بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while submitting insurance claim id=%s", claim_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء إرسال المطالبة."
        finally:
            conn.close()

    def apply_claim_decision(
        self,
        claim_id: Any,
        item_decisions: List[Dict[str, Any]],
        new_status: Any,
        updated_by_user_id: Any = None,
        decision_notes: Any = None,
        rejection_reason: Any = None,
        external_claim_number: Any = None
    ) -> Tuple[bool, Any]:
        """
        يعتمد قرار شركة التأمين على مستوى عناصر المطالبة ثم يثبت حالة الرأس.
        new_status المسموح هنا: approved / partially_approved / rejected
        """
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return False, "معرف المطالبة غير صالح."

        allowed_final_statuses = {"approved", "partially_approved", "rejected"}
        try:
            safe_new_status = self._validate_claim_status(new_status)
        except ValueError as ve:
            return False, str(ve)

        if safe_new_status not in allowed_final_statuses:
            return False, "حالة القرار النهائية يجب أن تكون approved أو partially_approved أو rejected."

        if not isinstance(item_decisions, list) or not item_decisions:
            return False, "يجب تمرير قائمة قرارات عناصر المطالبة بشكل صحيح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not old_state:
                conn.rollback()
                return False, "المطالبة المطلوبة غير موجودة."

            if not self._claim_allows_decision(old_state):
                conn.rollback()
                return False, "لا يمكن اعتماد قرار على مطالبة ملغاة أو محصلة."

            if old_state.get("status") == "draft":
                conn.rollback()
                return False, "يجب إرسال المطالبة أولاً قبل اعتماد قرارها."

            seen_ids = set()

            for decision in item_decisions:
                if not isinstance(decision, dict):
                    conn.rollback()
                    return False, "أحد قرارات العناصر ليس بصيغة صحيحة."

                if "claim_item_id" not in decision:
                    conn.rollback()
                    return False, "كل قرار عنصر يجب أن يحتوي claim_item_id."

                claim_item_id = self._parse_int_id(decision["claim_item_id"], "معرف عنصر المطالبة")
                if claim_item_id in seen_ids:
                    conn.rollback()
                    return False, "يوجد claim_item_id مكرر داخل قرارات العناصر."
                seen_ids.add(claim_item_id)

                current_item = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)
                if not current_item or int(current_item["claim_id"]) != claim_id:
                    conn.rollback()
                    return False, "أحد عناصر القرار لا ينتمي إلى هذه المطالبة."

                item_status = self._validate_item_approval_status(decision.get("approval_status"))
                gross_amount = round(float(current_item["gross_amount"]), 2)

                item_notes = self._normalize_text(decision.get("notes"))
                item_rejection_reason = self._normalize_text(decision.get("rejection_reason"))
                covered_amount = self._parse_nonnegative_amount(
                    decision.get("covered_amount"),
                    "المبلغ المعتمد لعنصر المطالبة"
                )
                patient_amount = self._parse_nonnegative_amount(
                    decision.get("patient_amount"),
                    "حصة المريض لعنصر المطالبة"
                )

                if item_status == "rejected":
                    covered_amount = 0.0
                    patient_amount = gross_amount
                    if not item_rejection_reason:
                        item_rejection_reason = "مرفوض تأمينياً"

                elif item_status == "approved":
                    if covered_amount is None:
                        covered_amount = gross_amount
                    if patient_amount is None:
                        patient_amount = round(gross_amount - covered_amount, 2)
                    if covered_amount <= 0:
                        conn.rollback()
                        return False, "العنصر الموافق عليه يجب أن يحتوي مبلغاً معتمداً أكبر من صفر."
                    if round(covered_amount + patient_amount, 2) != gross_amount:
                        conn.rollback()
                        return False, "قيمة التغطية + حصة المريض يجب أن تساوي الإجمالي الخام للعنصر الموافق عليه."
                    item_rejection_reason = None

                elif item_status == "partial":
                    if covered_amount is None:
                        conn.rollback()
                        return False, "العنصر المعتمد جزئياً يتطلب covered_amount صريحاً."
                    if patient_amount is None:
                        patient_amount = round(gross_amount - covered_amount, 2)
                    if covered_amount <= 0 or covered_amount >= gross_amount:
                        conn.rollback()
                        return False, "العنصر المعتمد جزئياً يجب أن تكون قيمة التغطية فيه أكبر من صفر وأقل من الإجمالي الخام."
                    if round(covered_amount + patient_amount, 2) != gross_amount:
                        conn.rollback()
                        return False, "قيمة التغطية + حصة المريض يجب أن تساوي الإجمالي الخام للعنصر المعتمد جزئياً."
                    item_rejection_reason = None

                else:
                    conn.rollback()
                    return False, "لا يجوز إبقاء العناصر بحالة pending أثناء اعتماد القرار النهائي."

                old_item_state = dict(current_item)

                cursor.execute("""
                    UPDATE insurance_claim_items
                    SET
                        covered_amount = ?,
                        patient_amount = ?,
                        approval_status = ?,
                        rejection_reason = ?,
                        notes = COALESCE(?, notes)
                    WHERE id = ?
                """, (
                    round(covered_amount, 2),
                    round(patient_amount, 2),
                    item_status,
                    item_rejection_reason,
                    item_notes,
                    claim_item_id
                ))

                new_item_state = self._get_claim_item_by_id_with_cursor(cursor, claim_item_id)

                self._write_audit_log(
                    cursor=cursor,
                    user_id=safe_updated_by_user_id,
                    action="UPDATE",
                    table_name="insurance_claim_items",
                    record_id=claim_item_id,
                    old_values=old_item_state,
                    new_values=new_item_state
                )

            totals = self._recalculate_claim_totals(cursor, claim_id, updated_by_user_id=safe_updated_by_user_id)
            items_after = self._get_claim_items_with_cursor(cursor, claim_id)

            approved_count = sum(1 for item in items_after if item["approval_status"] == "approved")
            partial_count = sum(1 for item in items_after if item["approval_status"] == "partial")
            rejected_count = sum(1 for item in items_after if item["approval_status"] == "rejected")

            if safe_new_status == "approved":
                if rejected_count > 0 or partial_count > 0:
                    conn.rollback()
                    return False, "لا يمكن وسم المطالبة approved بينما بعض العناصر مرفوضة أو معتمدة جزئياً."
                if approved_count == 0:
                    conn.rollback()
                    return False, "لا يمكن اعتماد المطالبة بالكامل بدون عناصر approved."

            elif safe_new_status == "partially_approved":
                if approved_count == 0 and partial_count == 0:
                    conn.rollback()
                    return False, "المطالبة الجزئية تتطلب على الأقل عنصراً واحداً approved أو partial."

            elif safe_new_status == "rejected":
                if rejected_count != len(items_after):
                    conn.rollback()
                    return False, "لا يمكن وسم المطالبة rejected إلا إذا كانت جميع العناصر مرفوضة."
                if totals["approved_amount"] != 0:
                    conn.rollback()
                    return False, "المطالبة المرفوضة يجب أن يكون approved_amount فيها صفراً."

            safe_decision_notes = self._normalize_text(decision_notes)
            safe_rejection_reason = self._normalize_text(rejection_reason)
            safe_external_claim_number = self._normalize_text(external_claim_number)

            if safe_new_status == "rejected" and not safe_rejection_reason:
                safe_rejection_reason = "تم رفض المطالبة بالكامل."

            cursor.execute("""
                UPDATE insurance_claims
                SET
                    status = ?,
                    decision_notes = ?,
                    rejection_reason = ?,
                    external_claim_number = COALESCE(?, external_claim_number),
                    updated_by_user_id = ?
                WHERE id = ?
            """, (
                safe_new_status,
                safe_decision_notes,
                safe_rejection_reason if safe_new_status == "rejected" else None,
                safe_external_claim_number,
                safe_updated_by_user_id,
                claim_id
            ))

            new_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            new_state["items"] = items_after

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="insurance_claims",
                record_id=claim_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "claim_id": claim_id,
                "status": safe_new_status,
                "message": "تم اعتماد قرار المطالبة التأمينية بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while applying insurance claim decision id=%s", claim_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء اعتماد قرار المطالبة."
        finally:
            conn.close()

    def cancel_claim(
        self,
        claim_id: Any,
        updated_by_user_id: Any = None,
        decision_notes: Any = None
    ) -> Tuple[bool, Any]:
        try:
            claim_id = int(claim_id)
        except (TypeError, ValueError):
            return False, "معرف المطالبة غير صالح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            safe_updated_by_user_id = self._parse_int_id(updated_by_user_id, "معرف المستخدم المعدّل")
            if not self._user_exists(cursor, safe_updated_by_user_id):
                conn.rollback()
                return False, "المستخدم المعدّل غير موجود."

            old_state = self._get_claim_by_id_with_cursor(cursor, claim_id)
            if not old_state:
                conn.rollback()
                return False, "المطالبة المطلوبة غير موجودة."

            if old_state["status"] == "cancelled":
                conn.rollback()
                return False, "المطالبة ملغاة مسبقاً."

            if old_state["status"] == "collected":
                conn.rollback()
                return False, "لا يمكن إلغاء مطالبة محصلة."

            if self._claim_has_collections(cursor, claim_id) or float(old_state.get("collected_amount") or 0.0) > 0:
                conn.rollback()
                return False, "لا يمكن إلغاء مطالبة تحتوي تحصيلات تأمينية مسجلة."

            safe_decision_notes = self._normalize_text(decision_notes)

            cursor.execute("""
                UPDATE insurance_claims
                SET
                    status = 'cancelled',
                    decision_notes = COALESCE(?, decision_notes),
                    updated_by_user_id = ?
                WHERE id = ?
            """, (
                safe_decision_notes,
                safe_updated_by_user_id,
                claim_id
            ))

            new_state = self._get_claim_by_id_with_cursor(cursor, claim_id)

            self._write_audit_log(
                cursor=cursor,
                user_id=safe_updated_by_user_id,
                action="UPDATE",
                table_name="insurance_claims",
                record_id=claim_id,
                old_values=old_state,
                new_values=new_state
            )

            conn.commit()
            return True, {
                "claim_id": claim_id,
                "message": "تم إلغاء المطالبة التأمينية بنجاح."
            }

        except ValueError as ve:
            conn.rollback()
            return False, str(ve)
        except Exception:
            conn.rollback()
            logger.exception("Unexpected error while cancelling insurance claim id=%s", claim_id)
            return False, "حدث خطأ داخلي غير متوقع أثناء إلغاء المطالبة."
        finally:
            conn.close()

    # ==========================================
    # Operational Helper for Future UI / Workflow
    # ==========================================
    def build_claim_preview_from_sale_items(
        self,
        customer_id: Any,
        policy_id: Any,
        sale_item_ids: List[Any]
    ) -> Tuple[bool, Any]:
        """
        دالة مساعدة لبناء Preview داخلي من sale_items قبل إنشاء المطالبة فعلياً.
        لا تحفظ شيئاً في القاعدة.
        """
        try:
            safe_customer_id = self._parse_int_id(customer_id, "معرف العميل")
            safe_policy_id = self._parse_int_id(policy_id, "معرف الوثيقة")
        except ValueError as ve:
            return False, str(ve)

        if not isinstance(sale_item_ids, list) or not sale_item_ids:
            return False, "يجب تمرير قائمة sale_item_ids بشكل صحيح."

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            policy_row = self._get_policy_row(cursor, safe_policy_id)
            if not policy_row:
                return False, "الوثيقة التأمينية غير موجودة."

            if int(policy_row["customer_id"]) != safe_customer_id:
                return False, "الوثيقة لا تنتمي إلى العميل المحدد."

            preview_items: List[Dict[str, Any]] = []
            total_gross = 0.0
            total_insurer = 0.0
            total_patient = 0.0

            fake_claim_row = {
                "customer_id": safe_customer_id,
                "sale_id": None,
                "prescription_id": None,
                "default_coverage_percent": policy_row["default_coverage_percent"],
                "default_patient_share_percent": policy_row["default_patient_share_percent"]
            }

            for raw_sale_item_id in sale_item_ids:
                sale_item_id = self._parse_int_id(raw_sale_item_id, "معرف سطر البيع")
                normalized_item = self._normalize_claim_item_payload(
                    cursor=cursor,
                    claim_row=fake_claim_row,
                    item_data={"sale_item_id": sale_item_id, "quantity": 1}
                    if False else {"sale_item_id": sale_item_id, "quantity": self._get_sale_item_row(cursor, sale_item_id)["quantity"]}
                )

                preview_items.append(normalized_item)
                total_gross += normalized_item["gross_amount"]
                total_insurer += normalized_item["covered_amount"]
                total_patient += normalized_item["patient_amount"]

            return True, {
                "items": preview_items,
                "gross_amount": round(total_gross, 2),
                "insurer_amount": round(total_insurer, 2),
                "patient_amount": round(total_patient, 2)
            }

        except ValueError as ve:
            return False, str(ve)
        except Exception:
            logger.exception("Unexpected error while building claim preview from sale items.")
            return False, "حدث خطأ داخلي غير متوقع أثناء بناء معاينة المطالبة."
        finally:
            conn.close()