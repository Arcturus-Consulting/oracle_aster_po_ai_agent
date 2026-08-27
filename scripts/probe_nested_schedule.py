import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import NESTED_SCHEDULE_FIELDS


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one nested PO line schedule detail.")
    parser.add_argument("--po-header-id", required=True)
    parser.add_argument("--po-line-id", required=True)
    parser.add_argument("--line-location-id", required=True)
    parser.add_argument("--out", default=str(ROOT / "outputs" / "nested_schedule_raw.json"))
    args = parser.parse_args()

    client = OracleClient()
    path = (
        f"purchaseOrders/{args.po_header_id}/child/lines/{args.po_line_id}"
        f"/child/schedules/{args.line_location_id}"
    )
    try:
        row = client.get(path, {"fields": NESTED_SCHEDULE_FIELDS, "onlyData": "true"})
    except RuntimeError as exc:
        if "fields" not in str(exc).lower():
            raise
        print("Oracle rejected the fields parameter for nested schedules. Retrying without fields...")
        row = client.get(path, {"onlyData": "true"})
    dump_json(Path(args.out), {"resource": path, "item": row})
    print(f"Saved nested schedule to {args.out}")
    print(json.dumps(row, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
