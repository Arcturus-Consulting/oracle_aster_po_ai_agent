import os
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

try:
    from .email_service import build_supplier_followup_email
except ImportError:
    from email_service import build_supplier_followup_email

try:
    from .cache_service import cache_get_json, cache_key, cache_set_json, ttl_seconds
except ImportError:
    from cache_service import cache_get_json, cache_key, cache_set_json, ttl_seconds

if TYPE_CHECKING:
    from .oracle_client import OracleClient

OPEN_STATUSES = {"open"}

SCHEDULE_FIELDS = ",".join(
    [
        "OrderNumber",
        "POHeaderId",
        "POLineId",
        "LineLocationId",
        "LineNumber",
        "ScheduleNumber",
        "LineNumberScheduleNumber",
        "DueDate",
        "RequestedDeliveryDate",
        "ScheduleStatus",
        "ScheduleStatusCode",
        "Supplier",
        "SupplierSite",
        "ItemNumber",
        "ItemDescription",
        "ItemOrScheduleDescription",
        "Quantity",
        "ReceivedQuantity",
        "ShipToLocation",
        "RequisitioningBU",
        "ProcurementBU",
    ]
)

NESTED_SCHEDULE_FIELDS = ",".join(
    [
        "LineLocationId",
        "POLineId",
        "DestinationType",
        "DestinationTypeCode",
        "DeliverToLocation",
        "Description",
        "LineNumber",
        "ScheduleNumber",
        "DueDate",
        "ScheduleStatus",
    ]
)

HEADER_FIELDS = ",".join(
    [
        "POHeaderId",
        "OrderNumber",
        "Supplier",
        "SupplierSite",
        "SupplierContact",
        "SupplierCommunicationMethod",
        "SupplierCommunicationMethodCode",
        "SupplierEmailAddress",
        "SupplierCcEmailAddress",
        "SupplierBccEmailAddress",
        "Status",
        "StatusCode",
    ]
)


def today_from_env() -> date:
    override = os.getenv("TODAY_DATE", "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return date.today()


def parse_oracle_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]

    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def is_open_status(value: Any) -> bool:
    return str(value or "").strip().lower() in OPEN_STATUSES


def due_date_from_row(row: dict[str, Any]) -> date | None:
    return parse_oracle_date(row.get("RequestedDeliveryDate") or row.get("DueDate"))


def is_overdue_open_schedule(row: dict[str, Any], today: date | None = None) -> bool:
    today = today or today_from_env()
    due = due_date_from_row(row)
    return bool(due and due < today and is_open_status(row.get("ScheduleStatus")))


def normalize_schedule_row(
    row: dict[str, Any],
    *,
    today: date | None = None,
    header: dict[str, Any] | None = None,
    nested_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or today_from_env()
    header = header or {}
    nested_schedule = nested_schedule or {}
    due = due_date_from_row(row) or due_date_from_row(nested_schedule)
    late_days = (today - due).days if due else None
    description = (
        row.get("ItemOrScheduleDescription")
        or row.get("ItemDescription")
        or nested_schedule.get("Description")
        or ""
    )

    normalized = {
        "orderNumber": row.get("OrderNumber") or header.get("OrderNumber"),
        "poHeaderId": row.get("POHeaderId") or header.get("POHeaderId"),
        "poLineId": row.get("POLineId") or nested_schedule.get("POLineId"),
        "lineLocationId": row.get("LineLocationId") or nested_schedule.get("LineLocationId"),
        "lineSchedule": row.get("LineNumberScheduleNumber")
        or _line_schedule(row.get("LineNumber"), row.get("ScheduleNumber")),
        "destinationType": nested_schedule.get("DestinationType") or row.get("DestinationType"),
        "destinationTypeCode": nested_schedule.get("DestinationTypeCode") or row.get("DestinationTypeCode"),
        "dueDate": due.isoformat() if due else None,
        "lateDays": late_days,
        "status": row.get("ScheduleStatus") or nested_schedule.get("ScheduleStatus"),
        "supplier": row.get("Supplier") or header.get("Supplier"),
        "supplierSite": row.get("SupplierSite") or header.get("SupplierSite"),
        "supplierEmail": header.get("SupplierEmailAddress"),
        "supplierCommunicationMethod": header.get("SupplierCommunicationMethod"),
        "itemNumber": row.get("ItemNumber"),
        "description": description,
        "quantity": row.get("Quantity"),
        "receivedQuantity": row.get("ReceivedQuantity"),
        "shipToLocation": row.get("ShipToLocation") or nested_schedule.get("DeliverToLocation"),
        "mailAvailable": bool(header.get("SupplierEmailAddress")),
    }
    normalized["emailDraft"] = build_supplier_followup_email(normalized)
    return normalized


def _line_schedule(line: Any, schedule: Any) -> str:
    if line is None and schedule is None:
        return ""
    if schedule is None:
        return str(line)
    return f"{line}-{schedule}"


def fetch_purchase_order_header(client: "OracleClient", po_header_id: Any) -> dict[str, Any]:
    key = cache_key(
        "po-header",
        {
            "poHeaderId": str(po_header_id),
            "fields": HEADER_FIELDS,
            "baseUrl": os.getenv("ORACLE_BASE_URL", ""),
        },
    )

    cached = cache_get_json(key)
    if cached is not None:
        return cached

    header = client.get(f"purchaseOrders/{po_header_id}", {"fields": HEADER_FIELDS, "onlyData": "true"})
    cache_set_json(key, header, ttl_seconds("DETAIL_CACHE_TTL_SECONDS", 1800))
    return header

def fetch_nested_schedule_detail(client: "OracleClient", row: dict[str, Any]) -> dict[str, Any]:
    po_header_id = row.get("POHeaderId")
    po_line_id = row.get("POLineId")
    line_location_id = row.get("LineLocationId")

    if not po_header_id or not po_line_id or not line_location_id:
        return {}

    key = cache_key(
        "nested-schedule",
        {
            "poHeaderId": str(po_header_id),
            "poLineId": str(po_line_id),
            "lineLocationId": str(line_location_id),
            "baseUrl": os.getenv("ORACLE_BASE_URL", ""),
        },
    )

    cached = cache_get_json(key)
    if cached is not None:
        return cached

    path = f"purchaseOrders/{po_header_id}/child/lines/{po_line_id}/child/schedules/{line_location_id}"

    try:
        detail = client.get(path, {"fields": NESTED_SCHEDULE_FIELDS, "onlyData": "true"})
    except RuntimeError as exc:
        if "fields" not in str(exc).lower():
            raise
        detail = client.get(path, {"onlyData": "true"})

    cache_set_json(key, detail, ttl_seconds("DETAIL_CACHE_TTL_SECONDS", 1800))
    return detail

def fetch_schedule_candidates(
    client: "OracleClient",
    *,
    limit: int,
    max_pages: int,
    open_only: bool = True,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "fields": SCHEDULE_FIELDS,
        "onlyData": "true",
        "totalResults": "true",
    }

    if open_only:
        bu = os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")
        params["q"] = f"ScheduleStatus='Open';ProcurementBU='{bu}'"

    for order_by in ("RequestedDeliveryDate:desc", "DueDate:desc", ""):
        page_params = dict(params)
        if order_by:
            page_params["orderBy"] = order_by

        key = cache_key(
            "schedule-candidates",
            {
                "params": page_params,
                "limit": limit,
                "maxPages": max_pages,
                "baseUrl": os.getenv("ORACLE_BASE_URL", ""),
            },
        )

        cached = cache_get_json(key)
        if cached is not None:
            return cached

        try:
            rows = client.paginate(
                "purchaseOrderSchedules",
                params=page_params,
                limit=limit,
                max_pages=max_pages,
            )
            cache_set_json(key, rows, ttl_seconds("SCHEDULE_CACHE_TTL_SECONDS", 300))
            return rows
        except RuntimeError as exc:
            text = str(exc).lower()
            if order_by and ("orderby" in text or "order by" in text or "not valid" in text):
                continue
            raise

    return []



def get_overdue_open_po_schedules(
    limit: int | None = None,
    max_pages: int | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_order: str = "desc",
    destination_type: str = "",
    enrich_headers: bool = True,
    enrich_nested_schedules: bool = True,
    oracle_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from .oracle_client import OracleClient
    except ImportError:
        from oracle_client import OracleClient

    client = OracleClient(**oracle_config) if oracle_config else OracleClient()
    today = today_from_env()

    limit = int(limit or os.getenv("ORACLE_PAGE_LIMIT", "100"))
    max_pages = int(max_pages or os.getenv("ORACLE_MAX_PAGES", "10"))
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    sort_order = (sort_order or "desc").lower()
    destination_type = (destination_type or "").strip().lower()

    page_key = cache_key(
        "overdue-page",
        {
            "today": today.isoformat(),
            "limit": limit,
            "maxPages": max_pages,
            "page": page,
            "pageSize": page_size,
            "sortOrder": sort_order,
            "destinationType": destination_type,
            "enrichHeaders": enrich_headers,
            "enrichNestedSchedules": enrich_nested_schedules,
            "baseUrl": os.getenv("ORACLE_BASE_URL", ""),
            "procurementBU": os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit"),
        },
    )

    cached_page = cache_get_json(page_key)
    if cached_page is not None:
        cached_page["cache"] = {"hit": True, "key": page_key}
        return cached_page

    candidates = fetch_schedule_candidates(client, limit=limit, max_pages=max_pages)
    overdue = [row for row in candidates if is_overdue_open_schedule(row, today)]

    overdue.sort(
        key=lambda row: due_date_from_row(row) or date.min,
        reverse=(sort_order == "desc"),
    )

    total_overdue = len(overdue)
    total_pages = max(1, (total_overdue + page_size - 1) // page_size)
    page = min(page, total_pages)

    start = (page - 1) * page_size
    end = start + page_size
    visible_rows = overdue[start:end]

    headers_by_id: dict[Any, dict[str, Any]] = {}
    normalized_rows = []

    for row in visible_rows:
        header = {}
        nested_schedule = {}
        po_header_id = row.get("POHeaderId")

        if enrich_headers and po_header_id:
            if po_header_id not in headers_by_id:
                headers_by_id[po_header_id] = fetch_purchase_order_header(client, po_header_id)
            header = headers_by_id[po_header_id]

        if enrich_nested_schedules:
            try:
                nested_schedule = fetch_nested_schedule_detail(client, row)
            except Exception as exc:
                nested_schedule = {"_error": str(exc)}

        normalized_rows.append(
            normalize_schedule_row(row, today=today, header=header, nested_schedule=nested_schedule)
        )

    if destination_type:
        normalized_rows = [
            row
            for row in normalized_rows
            if str(row.get("destinationType") or "").strip().lower() == destination_type
        ]

    result = {
        "today": today.isoformat(),
        "candidateCount": len(candidates),
        "overdueOpenCount": total_overdue,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "sortOrder": sort_order,
        "destinationType": destination_type,
        "rows": normalized_rows,
        "cache": {"hit": False, "key": page_key},
    }

    cache_set_json(page_key, result, ttl_seconds("PAGE_CACHE_TTL_SECONDS", 300))
    return result