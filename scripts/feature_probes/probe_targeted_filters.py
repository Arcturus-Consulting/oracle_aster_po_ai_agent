import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import due_date_from_row, today_from_env


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
        "RequestedShipDate",
        "ScheduleStatus",
        "Supplier",
        "SupplierSite",
        "ItemDescription",
        "Quantity",
        "ReceivedQuantity",
        "Amount",
        "ProcurementBU",
    ]
)


def summarize(row: dict[str, Any], today: date) -> dict[str, Any]:
    due = due_date_from_row(row)
    return {
        "OrderNumber": row.get("OrderNumber"),
        "POHeaderId": row.get("POHeaderId"),
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
        "Description": row.get("ItemDescription"),
    }


def run_query(client: OracleClient, name: str, q: str, today: date) -> dict[str, Any]:
    try:
        data = client.get(
            "purchaseOrderSchedules",
            {
                "fields": FIELDS,
                "onlyData": "true",
                "totalResults": "true",
                "limit": 20,
                "q": q,
            },
        )
        rows = data.get("items", [])
        return {
            "name": name,
            "q": q,
            "ok": True,
            "count": data.get("count"),
            "hasMore": data.get("hasMore"),
            "rows": [summarize(row, today) for row in rows],
        }
    except Exception as exc:
        return {"name": name, "q": q, "ok": False, "error": str(exc)}


def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--supplier", default="Amazon")
    parser.add_argument("--min-amount", type=float, default=10000)
    parser.add_argument("--near-days", type=int, default=3)
    args = parser.parse_args()

    client = OracleClient()
    today = today_from_env()
    bu = os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")

    queries = [
        (
            "supplier_open",
            f"ScheduleStatus='Open';ProcurementBU='{bu}';Supplier='{args.supplier}'",
        ),
        (
            "supplier_overdue_requested_date",
            f"ScheduleStatus='Open';ProcurementBU='{bu}';Supplier='{args.supplier}';RequestedDeliveryDate<'{today.isoformat()}'",
        ),
        (
            "overdue_more_than_30_requested_date",
            f"ScheduleStatus='Open';ProcurementBU='{bu}';RequestedDeliveryDate<'{(today - timedelta(days=30)).isoformat()}'",
        ),
        (
            "amount_above_min",
            f"ScheduleStatus='Open';ProcurementBU='{bu}';Amount>{args.min_amount}",
        ),
        (
            "due_today_or_near",
            (
                f"ScheduleStatus='Open';ProcurementBU='{bu}';"
                f"RequestedDeliveryDate>='{today.isoformat()}';"
                f"RequestedDeliveryDate<='{(today + timedelta(days=args.near_days)).isoformat()}'"
            ),
        ),
    ]

    results = [run_query(client, name, q, today) for name, q in queries]

    out_path = OUTPUT_DIR / "targeted_filter_probe.json"
    dump_json(out_path, results)

    print(f"Saved targeted filter probe to {out_path}")
    print(json.dumps([{k: v for k, v in item.items() if k != "rows"} for item in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())