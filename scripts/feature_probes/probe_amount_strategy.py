import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import due_date_from_row, fetch_purchase_order_header, is_overdue_open_schedule, today_from_env


OUTPUT_DIR = ROOT / "outputs" / "feature_probes"

FIELDS = ",".join(
    [
        "OrderNumber",
        "POHeaderId",
        "POLineId",
        "LineLocationId",
        "RequestedDeliveryDate",
        "ScheduleStatus",
        "Supplier",
        "ItemDescription",
        "Quantity",
        "ReceivedQuantity",
        "Amount",
        "ProcurementBU",
    ]
)


def number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(str(value).replace(",", ""))


def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--min-amount", type=float, default=10000)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()

    client = OracleClient()
    today = today_from_env()
    bu = os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")

    rows = client.paginate(
        "purchaseOrderSchedules",
        params={
            "fields": FIELDS,
            "onlyData": "true",
            "q": f"ScheduleStatus='Open';ProcurementBU='{bu}';RequestedDeliveryDate<'{today.isoformat()}'",
            "orderBy": "RequestedDeliveryDate:desc",
        },
        limit=args.limit,
        max_pages=args.max_pages,
    )

    overdue = [row for row in rows if is_overdue_open_schedule(row, today)]

    header_cache = {}
    results = []

    for row in overdue:
        po_header_id = row.get("POHeaderId")
        if po_header_id not in header_cache:
            header_cache[po_header_id] = fetch_purchase_order_header(client, po_header_id)

        header = header_cache[po_header_id]
        due = due_date_from_row(row)
        schedule_amount = number(row.get("Amount"))
        header_total = number(header.get("Total"))

        if schedule_amount > args.min_amount or header_total > args.min_amount:
            results.append(
                {
                    "OrderNumber": row.get("OrderNumber"),
                    "POHeaderId": po_header_id,
                    "Supplier": row.get("Supplier"),
                    "DueDate": due.isoformat() if due else None,
                    "LateDays": (today - due).days if due else None,
                    "ScheduleAmount": schedule_amount,
                    "HeaderTotal": header_total,
                    "MatchesScheduleAmount": schedule_amount > args.min_amount,
                    "MatchesHeaderTotal": header_total > args.min_amount,
                    "Description": row.get("ItemDescription"),
                }
            )

    output = {
        "today": today.isoformat(),
        "scannedRows": len(rows),
        "overdueRows": len(overdue),
        "uniqueHeadersFetched": len(header_cache),
        "minAmount": args.min_amount,
        "matches": results[:50],
        "matchCountInScannedRows": len(results),
    }

    out_path = OUTPUT_DIR / "amount_strategy_probe.json"
    dump_json(out_path, output)

    print(f"Saved amount strategy probe to {out_path}")
    print(json.dumps({k: v for k, v in output.items() if k != "matches"}, indent=2))
    print("First 10 matches:")
    print(json.dumps(results[:10], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())