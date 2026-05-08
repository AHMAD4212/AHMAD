"""
مهمة الملف:
طبقة الوصول للبيانات الخاصة بإدارة المواد الخطرة.

الطبقة:
Data Access Layer

ملاحظات معمارية:
- هذا الملف لا يغيّر مخطط قاعدة البيانات، بل يعمل فوق البنية الحالية فقط.
- يعتمد على الجداول الموجودة فعلاً:
  medicines, batches, suppliers, hazardous_disposal_log, disposals, users
- الهدف منه جعل المتطلب 28 متطلباً مستقلاً وقابلاً للإدارة من خلال:
  1) عرض الأصناف الخطرة
  2) عرض دفعاتها
  3) عرض الدفعات المنتهية أو القريبة من الانتهاء
  4) عرض سجل الإتلاف الخطر
  5) إعطاء ملخص تشغيلي سريع
- لا يحتوي أي منطق واجهات، ولا أي أوامر ALTER/CREATE.
"""

import sqlite3
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class HazardousMaterialsDAO:
    def __init__(self):
        self.db = DatabaseManager()

    # ==========================================
    # أدوات الاتصال والتحويل
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
    # أدوات التطبيع والتحقق
    # ==========================================
    def _normalize_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _parse_positive_int(self, value: Any, field_name: str, allow_none: bool = False) -> Optional[int]:
        if value is None or str(value).strip() == "":
            if allow_none:
                return None
            raise ValueError(f"{field_name} حقل إلزامي.")

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

        if parsed <= 0:
            raise ValueError(f"{field_name} يجب أن يكون عدداً موجباً.")
        return parsed

    def _parse_non_negative_int(self, value: Any, field_name: str, default: int = 0) -> int:
        if value is None or str(value).strip() == "":
            return default

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

        if parsed < 0:
            raise ValueError(f"{field_name} لا يجوز أن يكون سالباً.")
        return parsed

    def _parse_date(self, value: Any, field_name: str, allow_none: bool = False) -> Optional[str]:
        if value is None or str(value).strip() == "":
            if allow_none:
                return None
            raise ValueError(f"{field_name} حقل إلزامي.")

        text = str(value).strip()
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"{field_name} يجب أن يكون بصيغة YYYY-MM-DD.")
        return text

    def _build_like(self, value: str) -> str:
        return f"%{value}%"

    def _today_str(self) -> str:
        return date.today().strftime("%Y-%m-%d")

    def _future_date_str(self, days_ahead: int) -> str:
        return (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # ==========================================
    # 1) الأصناف الخطرة
    # ==========================================
    def get_all_hazardous_medicines(
        self,
        search_term: Optional[str] = None,
        low_stock_only: bool = False,
        out_of_stock_only: bool = False,
        supplier_id: Optional[Any] = None,
        sort_by: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        يعيد جميع الأدوية المصنفة كمواد خطرة مع ملخص تشغيلي لكل صنف.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            safe_supplier_id = self._parse_positive_int(supplier_id, "معرف المورد", allow_none=True)
            safe_search = self._normalize_text(search_term)

            sort_map = {
                "name": "m.name COLLATE NOCASE ASC",
                "quantity": "m.quantity DESC, m.name COLLATE NOCASE ASC",
                "nearest_expiry": "nearest_expiry_date IS NULL, nearest_expiry_date ASC, m.name COLLATE NOCASE ASC",
                "hazard_class": "COALESCE(m.hazard_class, '') COLLATE NOCASE ASC, m.name COLLATE NOCASE ASC",
                "supplier": "COALESCE(s.name, '') COLLATE NOCASE ASC, m.name COLLATE NOCASE ASC"
            }
            safe_order = sort_map.get(sort_by, sort_map["name"])

            sql = f"""
                SELECT
                    m.id,
                    m.barcode,
                    m.name,
                    m.active_ingredient,
                    m.dosage_form,
                    m.strength,
                    m.description,
                    m.buy_price,
                    m.sell_price,
                    m.quantity AS system_quantity,
                    m.expiry_date AS medicine_expiry_date,
                    m.min_stock_alert,
                    m.hazard_class,
                    m.hazard_notes,
                    m.supplier_id,
                    s.name AS supplier_name,

                    COALESCE((
                        SELECT COUNT(*)
                        FROM batches b1
                        WHERE b1.medicine_id = m.id
                    ), 0) AS total_batches_count,

                    COALESCE((
                        SELECT COUNT(*)
                        FROM batches b2
                        WHERE b2.medicine_id = m.id
                          AND b2.quantity > 0
                          AND b2.status = 'active'
                    ), 0) AS active_batches_count,

                    (
                        SELECT MIN(b3.expiry_date)
                        FROM batches b3
                        WHERE b3.medicine_id = m.id
                          AND b3.quantity > 0
                    ) AS nearest_expiry_date,

                    COALESCE((
                        SELECT COUNT(*)
                        FROM batches b4
                        WHERE b4.medicine_id = m.id
                          AND DATE(b4.expiry_date) < DATE('now')
                          AND b4.quantity > 0
                    ), 0) AS expired_batches_count,

                    COALESCE((
                        SELECT SUM(b5.quantity)
                        FROM batches b5
                        WHERE b5.medicine_id = m.id
                          AND b5.quantity > 0
                    ), 0) AS batch_quantity_total,

                    COALESCE((
                        SELECT COUNT(*)
                        FROM hazardous_disposal_log h
                        WHERE h.medicine_id = m.id
                    ), 0) AS hazardous_disposal_events_count,

                    CASE
                        WHEN COALESCE(m.quantity, 0) <= 0 THEN 'out_of_stock'
                        WHEN COALESCE(m.quantity, 0) <= COALESCE(m.min_stock_alert, 0) THEN 'low_stock'
                        ELSE 'normal'
                    END AS stock_state

                FROM medicines m
                LEFT JOIN suppliers s ON s.id = m.supplier_id
                WHERE m.is_hazardous = 1
            """
            params: List[Any] = []

            if safe_supplier_id is not None:
                sql += " AND m.supplier_id = ?"
                params.append(safe_supplier_id)

            if low_stock_only:
                sql += " AND COALESCE(m.quantity, 0) <= COALESCE(m.min_stock_alert, 0)"

            if out_of_stock_only:
                sql += " AND COALESCE(m.quantity, 0) <= 0"

            if safe_search:
                sql += """
                    AND (
                        m.name LIKE ?
                        OR COALESCE(m.barcode, '') LIKE ?
                        OR COALESCE(m.active_ingredient, '') LIKE ?
                        OR COALESCE(m.hazard_class, '') LIKE ?
                        OR COALESCE(m.hazard_notes, '') LIKE ?
                        OR COALESCE(s.name, '') LIKE ?
                    )
                """
                like_value = self._build_like(safe_search)
                params.extend([like_value] * 6)

            sql += f" ORDER BY {safe_order}"

            cursor.execute(sql, params)
            rows = self._rows_to_dicts(cursor.fetchall())

            for row in rows:
                row["display_strength"] = " ".join(
                    x for x in [
                        row.get("dosage_form"),
                        row.get("strength")
                    ] if x
                ) or None

            return rows

        except Exception:
            logger.exception("فشل تحميل قائمة المواد الخطرة.")
            return []
        finally:
            conn.close()

    def get_hazardous_medicine_by_id(self, medicine_id: Any) -> Optional[Dict[str, Any]]:
        """
        يعيد بطاقة تفصيلية لصنف خطر واحد.
        """
        try:
            safe_medicine_id = self._parse_positive_int(medicine_id, "معرف الدواء")
        except ValueError:
            return None

        results = self.get_all_hazardous_medicines()
        for row in results:
            if int(row["id"]) == safe_medicine_id:
                return row
        return None

    # ==========================================
    # 2) دفعات المواد الخطرة
    # ==========================================
    def get_hazardous_batches(
        self,
        search_term: Optional[str] = None,
        medicine_id: Optional[Any] = None,
        batch_status: Optional[str] = None,
        expired_only: bool = False,
        expiring_within_days: Optional[Any] = None,
        include_zero_qty: bool = False,
        sort_by: str = "expiry_date"
    ) -> List[Dict[str, Any]]:
        """
        يعيد دفعات المواد الخطرة مع حالة الصلاحية والحالة المخزنية.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            safe_search = self._normalize_text(search_term)
            safe_medicine_id = self._parse_positive_int(medicine_id, "معرف الدواء", allow_none=True)
            safe_days = None
            if expiring_within_days is not None and str(expiring_within_days).strip() != "":
                safe_days = self._parse_non_negative_int(expiring_within_days, "عدد الأيام", default=30)

            allowed_batch_statuses = {'active', 'expired', 'depleted', 'recalled'}
            safe_batch_status = None
            if batch_status is not None and str(batch_status).strip() != "":
                safe_batch_status = str(batch_status).strip().lower()
                if safe_batch_status not in allowed_batch_statuses:
                    raise ValueError("حالة الدفعة غير صالحة.")

            sort_map = {
                "expiry_date": "b.expiry_date ASC, m.name COLLATE NOCASE ASC",
                "medicine_name": "m.name COLLATE NOCASE ASC, b.expiry_date ASC",
                "quantity": "b.quantity DESC, m.name COLLATE NOCASE ASC",
                "status": "b.status ASC, b.expiry_date ASC"
            }
            safe_order = sort_map.get(sort_by, sort_map["expiry_date"])

            soon_limit = self._future_date_str(safe_days if safe_days is not None else 30)

            sql = f"""
                SELECT
                    b.id AS batch_id,
                    b.medicine_id,
                    m.name AS medicine_name,
                    m.barcode,
                    m.active_ingredient,
                    m.dosage_form,
                    m.strength,
                    m.hazard_class,
                    m.hazard_notes,
                    b.batch_number,
                    b.expiry_date,
                    b.buy_price,
                    b.sell_price,
                    b.quantity,
                    b.status,
                    b.received_at,
                    s.name AS supplier_name,
                    CAST(julianday(b.expiry_date) - julianday(DATE('now')) AS INTEGER) AS days_to_expiry,
                    CASE
                        WHEN DATE(b.expiry_date) < DATE('now') THEN 'expired'
                        WHEN DATE(b.expiry_date) <= DATE(?) THEN 'expiring_soon'
                        ELSE 'valid'
                    END AS expiry_state
                FROM batches b
                JOIN medicines m ON m.id = b.medicine_id
                LEFT JOIN suppliers s ON s.id = m.supplier_id
                WHERE m.is_hazardous = 1
            """
            params: List[Any] = [soon_limit]

            if safe_medicine_id is not None:
                sql += " AND b.medicine_id = ?"
                params.append(safe_medicine_id)

            if safe_batch_status is not None:
                sql += " AND b.status = ?"
                params.append(safe_batch_status)

            if not include_zero_qty:
                sql += " AND COALESCE(b.quantity, 0) > 0"

            if expired_only:
                sql += " AND DATE(b.expiry_date) < DATE('now')"

            if safe_days is not None:
                future_limit = self._future_date_str(safe_days)
                sql += " AND DATE(b.expiry_date) BETWEEN DATE('now') AND DATE(?)"
                params.append(future_limit)

            if safe_search:
                sql += """
                    AND (
                        m.name LIKE ?
                        OR COALESCE(m.barcode, '') LIKE ?
                        OR COALESCE(m.active_ingredient, '') LIKE ?
                        OR COALESCE(b.batch_number, '') LIKE ?
                        OR COALESCE(m.hazard_class, '') LIKE ?
                        OR COALESCE(s.name, '') LIKE ?
                    )
                """
                like_value = self._build_like(safe_search)
                params.extend([like_value] * 6)

            sql += f" ORDER BY {safe_order}"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("فشل تحميل دفعات المواد الخطرة.")
            return []
        finally:
            conn.close()

    def get_expired_hazardous_batches(self) -> List[Dict[str, Any]]:
        return self.get_hazardous_batches(expired_only=True, include_zero_qty=False, sort_by="expiry_date")

    def get_expiring_hazardous_batches(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        return self.get_hazardous_batches(
            expired_only=False,
            expiring_within_days=days_ahead,
            include_zero_qty=False,
            sort_by="expiry_date"
        )

    # ==========================================
    # 3) سجل الإتلاف الخطر
    # ==========================================
    def get_hazardous_disposal_log(
        self,
        search_term: Optional[str] = None,
        medicine_id: Optional[Any] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        manifest_number: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        يعيد السجل البيئي/الرقابي الخاص بإتلاف المواد الخطرة.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            safe_search = self._normalize_text(search_term)
            safe_manifest = self._normalize_text(manifest_number)
            safe_medicine_id = self._parse_positive_int(medicine_id, "معرف الدواء", allow_none=True)
            safe_start = self._parse_date(start_date, "من تاريخ", allow_none=True)
            safe_end = self._parse_date(end_date, "إلى تاريخ", allow_none=True)

            if safe_start and safe_end:
                start_obj = datetime.strptime(safe_start, "%Y-%m-%d").date()
                end_obj = datetime.strptime(safe_end, "%Y-%m-%d").date()
                if start_obj > end_obj:
                    raise ValueError("تاريخ البداية لا يجوز أن يكون بعد تاريخ النهاية.")

            sql = """
                SELECT
                    h.id,
                    h.disposal_id,
                    d.disposal_date,
                    h.disposal_item_id,
                    h.medicine_id,
                    m.name AS medicine_name,
                    m.barcode,
                    m.active_ingredient,
                    m.dosage_form,
                    m.strength,
                    h.batch_id,
                    b.batch_number,
                    h.user_id,
                    u.username,
                    h.quantity,
                    h.hazard_class,
                    h.disposal_reason,
                    h.disposal_method,
                    h.receiver_entity,
                    h.manifest_number,
                    h.notes,
                    h.logged_at
                FROM hazardous_disposal_log h
                JOIN medicines m ON m.id = h.medicine_id
                LEFT JOIN batches b ON b.id = h.batch_id
                LEFT JOIN users u ON u.id = h.user_id
                LEFT JOIN disposals d ON d.id = h.disposal_id
                WHERE 1 = 1
            """
            params: List[Any] = []

            if safe_medicine_id is not None:
                sql += " AND h.medicine_id = ?"
                params.append(safe_medicine_id)

            if safe_start:
                sql += " AND DATE(COALESCE(d.disposal_date, h.logged_at)) >= DATE(?)"
                params.append(safe_start)

            if safe_end:
                sql += " AND DATE(COALESCE(d.disposal_date, h.logged_at)) <= DATE(?)"
                params.append(safe_end)

            if safe_manifest:
                sql += " AND COALESCE(h.manifest_number, '') LIKE ?"
                params.append(self._build_like(safe_manifest))

            if safe_search:
                sql += """
                    AND (
                        m.name LIKE ?
                        OR COALESCE(m.barcode, '') LIKE ?
                        OR COALESCE(m.active_ingredient, '') LIKE ?
                        OR COALESCE(b.batch_number, '') LIKE ?
                        OR COALESCE(h.hazard_class, '') LIKE ?
                        OR COALESCE(h.disposal_method, '') LIKE ?
                        OR COALESCE(h.receiver_entity, '') LIKE ?
                        OR COALESCE(u.username, '') LIKE ?
                        OR COALESCE(h.manifest_number, '') LIKE ?
                    )
                """
                like_value = self._build_like(safe_search)
                params.extend([like_value] * 9)

            sql += " ORDER BY COALESCE(d.disposal_date, h.logged_at) DESC, h.id DESC"

            cursor.execute(sql, params)
            return self._rows_to_dicts(cursor.fetchall())

        except Exception:
            logger.exception("فشل تحميل سجل الإتلاف الخطر.")
            return []
        finally:
            conn.close()

    def get_hazardous_disposal_log_by_id(self, log_id: Any) -> Optional[Dict[str, Any]]:
        try:
            safe_log_id = self._parse_positive_int(log_id, "معرف السجل")
        except ValueError:
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    h.id,
                    h.disposal_id,
                    d.disposal_date,
                    h.disposal_item_id,
                    h.medicine_id,
                    m.name AS medicine_name,
                    m.barcode,
                    m.active_ingredient,
                    m.dosage_form,
                    m.strength,
                    h.batch_id,
                    b.batch_number,
                    h.user_id,
                    u.username,
                    h.quantity,
                    h.hazard_class,
                    h.disposal_reason,
                    h.disposal_method,
                    h.receiver_entity,
                    h.manifest_number,
                    h.notes,
                    h.logged_at
                FROM hazardous_disposal_log h
                JOIN medicines m ON m.id = h.medicine_id
                LEFT JOIN batches b ON b.id = h.batch_id
                LEFT JOIN users u ON u.id = h.user_id
                LEFT JOIN disposals d ON d.id = h.disposal_id
                WHERE h.id = ?
                LIMIT 1
            """, (safe_log_id,))
            return self._row_to_dict(cursor.fetchone())

        except Exception:
            logger.exception("فشل تحميل سجل إتلاف خطر مفرد.")
            return None
        finally:
            conn.close()

    # ==========================================
    # 4) ملخصات تشغيلية
    # ==========================================
    def get_hazardous_dashboard_summary(self, expiring_within_days: int = 30) -> Dict[str, Any]:
        """
        ملخص سريع يمكن استخدامه في الصفحة الإدارية للمواد الخطرة.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            safe_days = self._parse_non_negative_int(expiring_within_days, "عدد الأيام", default=30)
            future_limit = self._future_date_str(safe_days)

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM medicines
                WHERE is_hazardous = 1
            """)
            total_hazardous_medicines = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM medicines
                WHERE is_hazardous = 1
                  AND COALESCE(quantity, 0) <= 0
            """)
            out_of_stock_count = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM medicines
                WHERE is_hazardous = 1
                  AND COALESCE(quantity, 0) > 0
                  AND COALESCE(quantity, 0) <= COALESCE(min_stock_alert, 0)
            """)
            low_stock_count = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM batches b
                JOIN medicines m ON m.id = b.medicine_id
                WHERE m.is_hazardous = 1
                  AND COALESCE(b.quantity, 0) > 0
            """)
            total_live_batches = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM batches b
                JOIN medicines m ON m.id = b.medicine_id
                WHERE m.is_hazardous = 1
                  AND COALESCE(b.quantity, 0) > 0
                  AND DATE(b.expiry_date) < DATE('now')
            """)
            expired_batches_count = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM batches b
                JOIN medicines m ON m.id = b.medicine_id
                WHERE m.is_hazardous = 1
                  AND COALESCE(b.quantity, 0) > 0
                  AND DATE(b.expiry_date) BETWEEN DATE('now') AND DATE(?)
            """, (future_limit,))
            expiring_soon_batches_count = cursor.fetchone()["cnt"]

            cursor.execute("""
                SELECT COALESCE(SUM(quantity), 0) AS total_qty
                FROM hazardous_disposal_log
            """)
            total_disposed_qty = cursor.fetchone()["total_qty"]

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM hazardous_disposal_log
            """)
            disposal_events_count = cursor.fetchone()["cnt"]

            return {
                "total_hazardous_medicines": total_hazardous_medicines,
                "out_of_stock_count": out_of_stock_count,
                "low_stock_count": low_stock_count,
                "total_live_batches": total_live_batches,
                "expired_batches_count": expired_batches_count,
                "expiring_soon_batches_count": expiring_soon_batches_count,
                "total_disposed_qty": total_disposed_qty,
                "disposal_events_count": disposal_events_count,
                "expiring_within_days": safe_days
            }

        except Exception:
            logger.exception("فشل تحميل الملخص التشغيلي للمواد الخطرة.")
            return {
                "total_hazardous_medicines": 0,
                "out_of_stock_count": 0,
                "low_stock_count": 0,
                "total_live_batches": 0,
                "expired_batches_count": 0,
                "expiring_soon_batches_count": 0,
                "total_disposed_qty": 0,
                "disposal_events_count": 0,
                "expiring_within_days": expiring_within_days
            }
        finally:
            conn.close()

    # ==========================================
    # 5) دوال عملية للواجهة المستقلة
    # ==========================================
    def get_hazardous_management_snapshot(self, expiring_within_days: int = 30) -> Dict[str, Any]:
        """
        دالة تجميعية مفيدة للواجهة الإدارية:
        - ملخص
        - الأصناف الخطرة
        - الدفعات المنتهية
        - الدفعات القريبة من الانتهاء
        - آخر سجل إتلاف
        """
        summary = self.get_hazardous_dashboard_summary(expiring_within_days=expiring_within_days)

        return {
            "summary": summary,
            "hazardous_medicines": self.get_all_hazardous_medicines(),
            "expired_batches": self.get_expired_hazardous_batches(),
            "expiring_batches": self.get_expiring_hazardous_batches(days_ahead=expiring_within_days),
            "recent_disposal_log": self.get_hazardous_disposal_log()
        }