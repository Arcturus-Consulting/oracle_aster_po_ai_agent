import json
import sys
from collections import Counter
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
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=3)
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

    enriched = []
    counts = Counter()

    for index, row in enumerate(overdue, start=1):
        print(f"[{index}/{len(overdue)}] {row.get('OrderNumber')}")
        try:
            nested = fetch_nested_schedule_detail(client, row)
            destination_type = nested.get("DestinationType") or "-"
            destination_type_code = nested.get("DestinationTypeCode") or "-"
        except Exception as exc:
            destination_type = "ERROR"
            destination_type_code = str(exc)

        counts[destination_type] += 1
        due = due_date_from_row(row)

        enriched.append(
            {
                "OrderNumber": row.get("OrderNumber"),
                "POHeaderId": row.get("POHeaderId"),
                "POLineId": row.get("POLineId"),
                "LineLocationId": row.get("LineLocationId"),
                "Supplier": row.get("Supplier"),
                "DueDate": due.isoformat() if due else None,
                "LateDays": (today - due).days if due else None,
                "DestinationType": destination_type,
                "DestinationTypeCode": destination_type_code,
                "Amount": row.get("Amount"),
                "Description": row.get("ItemDescription"),
            }
        )

    output = {
        "today": today.isoformat(),
        "scannedRows": len(rows),
        "overdueRows": len(overdue),
        "seconds": round(time.time() - started, 2),
        "destinationCounts": dict(counts),
        "inventoryFirst20": [row for row in enriched if row["DestinationType"].lower() == "inventory"][:20],
        "expenseFirst20": [row for row in enriched if row["DestinationType"].lower() == "expense"][:20],
        "allFirst50": enriched[:50],
    }

    out_path = OUTPUT_DIR / "destination_strategy_probe.json"
    dump_json(out_path, output)

    print(f"Saved destination strategy probe to {out_path}")
    print(json.dumps({k: v for k, v in output.items() if k not in {"allFirst50", "inventoryFirst20", "expenseFirst20"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())