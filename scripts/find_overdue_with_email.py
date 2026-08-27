import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient
from backend.po_tools import (
    fetch_purchase_order_header,
    fetch_schedule_candidates,
    is_overdue_open_schedule,
    normalize_schedule_row,
    today_from_env,
)


def main() -> int:
    client = OracleClient()
    today = today_from_env()

    schedules = fetch_schedule_candidates(
        client,
        limit=25,
        max_pages=2,
        open_only=True,
    )
    overdue = [row for row in schedules if is_overdue_open_schedule(row, today)]

    headers_by_id = {}
    matches = []

    print(f"Scanned schedules: {len(schedules)}")
    print(f"Overdue open schedules: {len(overdue)}")
    print("Checking first 15 unique PO headers only...")

    unique_header_ids = []
    for row in overdue:
        po_header_id = row.get("POHeaderId")
        if po_header_id and po_header_id not in unique_header_ids:
            unique_header_ids.append(po_header_id)
        if len(unique_header_ids) >= 15:
            break

    for index, po_header_id in enumerate(unique_header_ids, start=1):
        print(f"[{index}/{len(unique_header_ids)}] Header {po_header_id}")
        headers_by_id[po_header_id] = fetch_purchase_order_header(client, po_header_id)

    for row in overdue:
        header = headers_by_id.get(row.get("POHeaderId"))
        if header and header.get("SupplierEmailAddress"):
            matches.append(normalize_schedule_row(row, today=today, header=header))

    print(f"Checked unique headers: {len(unique_header_ids)}")
    print(f"Overdue open schedules with supplier email in checked headers: {len(matches)}")
    print(json.dumps(matches[:10], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())