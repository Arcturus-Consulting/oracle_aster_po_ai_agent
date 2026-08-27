import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import due_date_from_row, fetch_nested_schedule_detail, is_open_status, today_from_env


OUTPUT_DIR = ROOT / "outputs" / "feature_probes"

FIELDS = ",".join(
    [
        "OrderNumber",
        "POHeaderId",
        "POLineId",
        "LineLocationId",
        "LineNumber",
        "ScheduleNumber",
        "RequestedDeliveryDate",
        "ScheduleStatus",
        "Supplier",
        "SupplierSite",
        "ItemNumber",
        "ItemDescription",
        "Quantity",
        "ReceivedQuantity",
        "Amount",
        "ProcurementBU",
        "ShipToLocation",
    ]
)


def num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(str(value).replace(",", ""))


def summarize(row: dict[str, Any], today: date, include_destination: bool = False, client: OracleClient | None = None) -> dict[str, Any]:
    due = due_date_from_row(row)
    out = {
        "OrderNumber": row.get("OrderNumber"),
        "Supplier": row.get("Supplier"),
        "DueDate": due.isoformat() if due else None,
        "LateDays": (today - due).days if due and due < today else None,
        "Status": row.get("ScheduleStatus"),
        "Quantity": row.get("Quantity"),
        "ReceivedQuantity": row.get("ReceivedQuantity"),
        "PendingQuantity": num(row.get("Quantity")) - num(row.get("ReceivedQuantity")),
        "Amount": row.get("Amount"),
        "Description": row.get("ItemDescription"),
    }

    if include_destination and client:
        try:
            nested = fetch_nested_schedule_detail(client, row)
            out["DestinationType"] = nested.get("DestinationType")
        except Exception as exc:
            out["DestinationTypeError"] = str(exc)

    return out


def build_q(today: date, mode: str, supplier: str | None = None, min_late_days: int | None = None, near_days: int = 3) -> str:
    import os

    bu = os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")
    parts = ["ScheduleStatus='Open'", f"ProcurementBU='{bu}'"]

    if supplier:
        parts.append(f"Supplier='{supplier}'")

    if mode == "overdue":
        parts.append(f"RequestedDeliveryDate<'{today.isoformat()}'")
    elif mode == "overdue_more_than":
        cutoff = today - timedelta(days=min_late_days or 30)
        parts.append(f"RequestedDeliveryDate<'{cutoff.isoformat()}'")
    elif mode == "due_this_week":
        parts.append(f"RequestedDeliveryDate>='{today.isoformat()}'")
        parts.append(f"RequestedDeliveryDate<='{(today + timedelta(days=7)).isoformat()}'")
    elif mode == "near_due":
        parts.append(f"RequestedDeliveryDate>='{today.isoformat()}'")
        parts.append(f"RequestedDeliveryDate<='{(today + timedelta(days=near_days)).isoformat()}'")

    return ";".join(parts)


def fetch(client: OracleClient, q: str, limit: int = 100, max_pages: int = 3) -> list[dict[str, Any]]:
    return client.paginate(
        "purchaseOrderSchedules",
        params={
            "fields": FIELDS,
            "onlyData": "true",
            "q": q,
            "orderBy": "RequestedDeliveryDate:desc",
        },
        limit=limit,
        max_pages=max_pages,
    )


def main() -> int:
    client = OracleClient()
    today = today_from_env()

    scenarios = []

    tests = [
        {"name": "all_overdue", "mode": "overdue"},
        {"name": "amazon_overdue", "mode": "overdue", "supplier": "Amazon"},
        {"name": "overdue_more_than_30_days", "mode": "overdue_more_than", "min_late_days": 30},
        {"name": "due_this_week", "mode": "due_this_week"},
        {"name": "near_due_3_days", "mode": "near_due", "near_days": 3},
    ]

    for test in tests:
        q = build_q(
            today,
            test["mode"],
            supplier=test.get("supplier"),
            min_late_days=test.get("min_late_days"),
            near_days=test.get("near_days", 3),
        )
        rows = fetch(client, q)
        scenarios.append(
            {
                "name": test["name"],
                "q": q,
                "countFetched": len(rows),
                "first10": [summarize(row, today) for row in rows[:10]],
            }
        )

    overdue_rows = fetch(client, build_q(today, "overdue"), limit=100, max_pages=5)

    amount_rows = [row for row in overdue_rows if num(row.get("Amount")) > 10000]
    partial_rows = [
        row
        for row in overdue_rows
        if num(row.get("Quantity")) > 0 and 0 < num(row.get("ReceivedQuantity")) < num(row.get("Quantity"))
    ]

    supplier_counts = Counter(row.get("Supplier") or "Unknown" for row in overdue_rows)

    visible_page_with_destination = [
        summarize(row, today, include_destination=True, client=client)
        for row in overdue_rows[:20]
    ]

    output = {
        "today": today.isoformat(),
        "scenarios": scenarios,
        "amountAbove10000": {
            "countInFetchedOverdueRows": len(amount_rows),
            "first10": [summarize(row, today) for row in amount_rows[:10]],
        },
        "partiallyReceivedOverdue": {
            "countInFetchedOverdueRows": len(partial_rows),
            "first10": [summarize(row, today) for row in partial_rows[:10]],
        },
        "suppliersMostOverdue": [
            {"supplier": supplier, "overdueSchedules": count}
            for supplier, count in supplier_counts.most_common(10)
        ],
        "visiblePageDestinationEnrichment": visible_page_with_destination,
    }

    out_path = OUTPUT_DIR / "unified_po_search_probe.json"
    dump_json(out_path, output)

    print(f"Saved unified search probe to {out_path}")
    print(
        json.dumps(
            {
                "today": output["today"],
                "scenarios": [
                    {"name": item["name"], "countFetched": item["countFetched"]}
                    for item in scenarios
                ],
                "amountAbove10000Count": output["amountAbove10000"]["countInFetchedOverdueRows"],
                "partiallyReceivedOverdueCount": output["partiallyReceivedOverdue"]["countInFetchedOverdueRows"],
                "topSuppliers": output["suppliersMostOverdue"][:5],
                "firstPageDestinationSample": output["visiblePageDestinationEnrichment"][:3],
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())