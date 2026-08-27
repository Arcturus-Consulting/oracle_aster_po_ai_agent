import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import (
    due_date_from_row,
    fetch_nested_schedule_detail,
    fetch_purchase_order_header,
    is_open_status,
    parse_oracle_date,
    today_from_env,
)


OUTPUT_DIR = ROOT / "outputs" / "feature_probes"

SCHEDULE_FIELDS = ",".join(
    [
        "OrderNumber",
        "POHeaderId",
        "POLineId",
        "LineLocationId",
        "LineNumber",
        "ScheduleNumber",
        "RequestedDeliveryDate",
        "RequestedShipDate",
        "ScheduleStatus",
        "Supplier",
        "SupplierSite",
        "ItemNumber",
        "ItemDescription",
        "Quantity",
        "ReceivedQuantity",
        "Amount",
        "ProcurementBU",
        "RequisitioningBU",
        "ShipToLocation",
    ]
)

HEADER_FIELDS = ",".join(
    [
        "POHeaderId",
        "OrderNumber",
        "Supplier",
        "SupplierEmailAddress",
        "SupplierCommunicationMethod",
        "Total",
        "Status",
        "StatusCode",
    ]
)


def money_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def qty_value(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def is_overdue_open(row: dict[str, Any], today: date) -> bool:
    due = due_date_from_row(row)
    return bool(due and due < today and is_open_status(row.get("ScheduleStatus")))


def is_due_this_week(row: dict[str, Any], today: date) -> bool:
    due = due_date_from_row(row)
    if not due:
        return False
    week_end = today + timedelta(days=7)
    return today <= due <= week_end


def is_due_today_or_near(row: dict[str, Any], today: date, days: int = 3) -> bool:
    due = due_date_from_row(row)
    if not due:
        return False
    return today <= due <= today + timedelta(days=days)


def is_partially_received(row: dict[str, Any]) -> bool:
    quantity = qty_value(row.get("Quantity"))
    received = qty_value(row.get("ReceivedQuantity"))
    return quantity > 0 and 0 < received < quantity


def summarize_row(row: dict[str, Any], today: date) -> dict[str, Any]:
    due = due_date_from_row(row)
    return {
        "OrderNumber": row.get("OrderNumber"),
        "POHeaderId": row.get("POHeaderId"),
        "POLineId": row.get("POLineId"),
        "LineLocationId": row.get("LineLocationId"),
        "Supplier": row.get("Supplier"),
        "DueDateUsed": due.isoformat() if due else None,
        "RawDueDate": row.get("DueDate") or row.get("RequestedDeliveryDate"),
        "RequestedDeliveryDate": row.get("RequestedDeliveryDate"),
        "LateDays": (today - due).days if due and due < today else None,
        "ScheduleStatus": row.get("ScheduleStatus"),
        "Quantity": row.get("Quantity"),
        "ReceivedQuantity": row.get("ReceivedQuantity"),
        "Amount": row.get("Amount"),
        "Ordered": row.get("Ordered"),
        "Description": row.get("ItemOrScheduleDescription") or row.get("ItemDescription"),
    }


def fetch_schedules(client: OracleClient, limit: int, max_pages: int) -> list[dict[str, Any]]:
    bu = __import__("os").getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")
    params = {
        "fields": SCHEDULE_FIELDS,
        "onlyData": "true",
        "totalResults": "true",
        "q": f"ScheduleStatus='Open';ProcurementBU='{bu}'",
    }

    for order_by in ("RequestedDeliveryDate:desc", "DueDate:desc", ""):
        attempt = dict(params)
        if order_by:
            attempt["orderBy"] = order_by
        try:
            return client.paginate(
                "purchaseOrderSchedules",
                params=attempt,
                limit=limit,
                max_pages=max_pages,
            )
        except RuntimeError as exc:
            if order_by and "not valid" in str(exc).lower():
                continue
            raise

    return []


def probe_oracle_q(client: OracleClient, today: date) -> list[dict[str, Any]]:
    bu = __import__("os").getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")
    tests = [
        {
            "name": "open_by_supplier_exact",
            "q": f"ScheduleStatus='Open';ProcurementBU='{bu}';Supplier='Amazon'",
        },
        {
            "name": "requested_delivery_before_today",
            "q": f"ScheduleStatus='Open';ProcurementBU='{bu}';RequestedDeliveryDate<'{today.isoformat()}'",
        },
        {
            "name": "due_this_week_requested_delivery",
            "q": (
                f"ScheduleStatus='Open';ProcurementBU='{bu}';"
                f"RequestedDeliveryDate>='{today.isoformat()}';"
                f"RequestedDeliveryDate<='{(today + timedelta(days=7)).isoformat()}'"
            ),
        },
        {
            "name": "amount_above_10000",
            "q": f"ScheduleStatus='Open';ProcurementBU='{bu}';Amount>10000",
        },
    ]

    results = []
    for item in tests:
        try:
            data = client.get(
                "purchaseOrderSchedules",
                {
                    "fields": SCHEDULE_FIELDS,
                    "onlyData": "true",
                    "limit": 5,
                    "q": item["q"],
                },
            )
            rows = data.get("items", [])
            results.append(
                {
                    "name": item["name"],
                    "q": item["q"],
                    "ok": True,
                    "count": data.get("count"),
                    "hasMore": data.get("hasMore"),
                    "firstRows": [summarize_row(row, today) for row in rows[:3]],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "name": item["name"],
                    "q": item["q"],
                    "ok": False,
                    "error": str(exc),
                }
            )
    return results


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--nested-sample", type=int, default=10)
    parser.add_argument("--header-sample", type=int, default=10)
    args = parser.parse_args()

    client = OracleClient()
    today = today_from_env()

    schedules = fetch_schedules(client, args.limit, args.max_pages)
    overdue = [row for row in schedules if is_overdue_open(row, today)]

    overdue_sorted_recent_first = sorted(
        overdue,
        key=lambda row: due_date_from_row(row) or date.min,
        reverse=True,
    )

    supplier_counts = Counter(row.get("Supplier") or "Unknown" for row in overdue)
    supplier_late_days = defaultdict(int)
    for row in overdue:
        due = due_date_from_row(row)
        if due:
            supplier_late_days[row.get("Supplier") or "Unknown"] += (today - due).days

    partially_received = [row for row in overdue if is_partially_received(row)]
    due_this_week = [row for row in schedules if is_due_this_week(row, today)]
    due_near = [row for row in schedules if is_due_today_or_near(row, today, days=3)]
    overdue_30 = [
        row for row in overdue
        if due_date_from_row(row) and (today - due_date_from_row(row)).days > 30
    ]
    amount_above_10000 = [
        row for row in overdue
        if (money_value(row.get("Amount")) or money_value(row.get("Ordered")) or 0) > 10000
    ]

    nested_samples = []
    for row in overdue_sorted_recent_first[: args.nested_sample]:
        try:
            nested = fetch_nested_schedule_detail(client, row)
            nested_samples.append(
                {
                    **summarize_row(row, today),
                    "DestinationType": nested.get("DestinationType"),
                    "DestinationTypeCode": nested.get("DestinationTypeCode"),
                    "NestedKeys": sorted(nested.keys()),
                }
            )
        except Exception as exc:
            nested_samples.append({**summarize_row(row, today), "nestedError": str(exc)})

    header_samples = []
    seen_headers = []
    for row in overdue_sorted_recent_first:
        po_header_id = row.get("POHeaderId")
        if po_header_id and po_header_id not in seen_headers:
            seen_headers.append(po_header_id)
        if len(seen_headers) >= args.header_sample:
            break

    for po_header_id in seen_headers:
        try:
            header = client.get(
                f"purchaseOrders/{po_header_id}",
                {"fields": HEADER_FIELDS, "onlyData": "true"},
            )
            header_samples.append(header)
        except Exception as exc:
            header_samples.append({"POHeaderId": po_header_id, "headerError": str(exc)})

    output = {
        "today": today.isoformat(),
        "scannedSchedules": len(schedules),
        "overdueOpenCount": len(overdue),
        "overdueMoreThan30Count": len(overdue_30),
        "dueThisWeekCount": len(due_this_week),
        "dueTodayOrNext3DaysCount": len(due_near),
        "partiallyReceivedOverdueCount": len(partially_received),
        "scheduleAmountAbove10000Count": len(amount_above_10000),
        "topSuppliersByOverdueCount": [
            {
                "supplier": supplier,
                "overdueSchedules": count,
                "totalLateDays": supplier_late_days[supplier],
            }
            for supplier, count in supplier_counts.most_common(10)
        ],
        "recentOverdueFirst10": [
            summarize_row(row, today) for row in overdue_sorted_recent_first[:10]
        ],
        "overdueMoreThan30First10": [
            summarize_row(row, today) for row in overdue_30[:10]
        ],
        "partiallyReceivedFirst10": [
            summarize_row(row, today) for row in partially_received[:10]
        ],
        "dueThisWeekFirst10": [
            summarize_row(row, today) for row in due_this_week[:10]
        ],
        "dueTodayOrNext3DaysFirst10": [
            summarize_row(row, today) for row in due_near[:10]
        ],
        "amountAbove10000First10": [
            summarize_row(row, today) for row in amount_above_10000[:10]
        ],
        "nestedDestinationSamples": nested_samples,
        "headerAmountEmailSamples": header_samples,
        "oracleQuerySupportTests": probe_oracle_q(client, today),
    }

    out_path = OUTPUT_DIR / "po_feature_matrix.json"
    dump_json(out_path, output)

    print(f"Saved feature probe to {out_path}")
    print(
        json.dumps(
            {
                "today": output["today"],
                "scannedSchedules": output["scannedSchedules"],
                "overdueOpenCount": output["overdueOpenCount"],
                "overdueMoreThan30Count": output["overdueMoreThan30Count"],
                "dueThisWeekCount": output["dueThisWeekCount"],
                "dueTodayOrNext3DaysCount": output["dueTodayOrNext3DaysCount"],
                "partiallyReceivedOverdueCount": output["partiallyReceivedOverdueCount"],
                "scheduleAmountAbove10000Count": output["scheduleAmountAbove10000Count"],
                "topSuppliersByOverdueCount": output["topSuppliersByOverdueCount"][:5],
                "queryTests": [
                    {"name": item["name"], "ok": item["ok"], "count": item.get("count"), "error": item.get("error")}
                    for item in output["oracleQuerySupportTests"]
                ],
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())