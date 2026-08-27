import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import SCHEDULE_FIELDS, fetch_schedule_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch purchaseOrderSchedules samples from Oracle Fusion.")
    parser.add_argument("--limit", type=int, default=int(os.getenv("ORACLE_PAGE_LIMIT", "50")))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("ORACLE_MAX_PAGES", "5")))
    parser.add_argument("--include-closed", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "outputs" / "po_schedules_raw.json"))
    args = parser.parse_args()

    client = OracleClient()
    rows = fetch_schedule_candidates(
        client,
        limit=args.limit,
        max_pages=args.max_pages,
        open_only=not args.include_closed,
    )

    output = {
        "resource": "purchaseOrderSchedules",
        "fieldsRequested": SCHEDULE_FIELDS.split(","),
        "count": len(rows),
        "sampleKeys": sorted(rows[0].keys()) if rows else [],
        "items": rows,
    }
    dump_json(Path(args.out), output)

    print(f"Saved {len(rows)} schedule row(s) to {args.out}")
    if rows:
        print("First row:")
        print(json.dumps(rows[0], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
