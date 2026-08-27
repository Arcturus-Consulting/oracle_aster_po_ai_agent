import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import (
    due_date_from_row,
    fetch_nested_schedule_detail,
    is_overdue_open_schedule,
    today_from_env,
)


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


def main() -> int:
    import argparse
    import os
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", default="Inventory")
    parser.add_argument("--need", type=int, default=20)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()

    client = OracleClient()
    today = today_from_env()
    bu = os.getenv("ORACLE_PROCUREMENT_BU", "US1 Business Unit")

    started = time.time()

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
    matches = []
    checked = 0

    for row in overdue:
        checked += 1
        print(f"[checked {checked}] {row.get('OrderNumber')}")

        nested = fetch_nested_schedule_detail(client, row)
        destination_type = nested.get("DestinationType") or ""

        if destination_type.lower() == args.destination.lower():
            due = due_date_from_row(row)
            matches.append(
                {
                    "OrderNumber": row.get("OrderNumber"),
                    "POHeaderId": row.get("POHeaderId"),
                    "Supplier": row.get("Supplier"),
                    "DueDate": due.isoformat() if due else None,
                    "LateDays": (today - due).days if due else None,
                    "DestinationType": destination_type,
                    "Amount": row.get("Amount"),
                    "Description": row.get("ItemDescription"),
                }
            )

        if len(matches) >= args.need:
            break

    output = {
        "today": today.isoformat(),
        "destination": args.destination,
        "scannedRows": len(rows),
        "overdueRows": len(overdue),
        "nestedRowsChecked": checked,
        "matchesFound": len(matches),
        "seconds": round(time.time() - started, 2),
        "matches": matches,
    }

    out_path = OUTPUT_DIR / "destination_first_matches_probe.json"
    dump_json(out_path, output)

    print(f"Saved destination first matches probe to {out_path}")
    print(json.dumps({k: v for k, v in output.items() if k != "matches"}, indent=2))
    print(json.dumps(matches[:5], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())