import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import dump_json
from backend.po_tools import get_overdue_open_po_schedules


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the exact overdue-open logic planned for the chatbot tool.")
    parser.add_argument("--limit", type=int, default=int(os.getenv("ORACLE_PAGE_LIMIT", "50")))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("ORACLE_MAX_PAGES", "5")))
    parser.add_argument("--no-header-enrichment", action="store_true")
    parser.add_argument("--no-nested-enrichment", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "outputs" / "overdue_open_summary.json"))
    args = parser.parse_args()

    result = get_overdue_open_po_schedules(
        limit=args.limit,
        max_pages=args.max_pages,
        enrich_headers=not args.no_header_enrichment,
        enrich_nested_schedules=not args.no_nested_enrichment,
    )
    dump_json(Path(args.out), result)
    print(f"Saved overdue-open result to {args.out}")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    print("First 3 normalized rows:")
    print(json.dumps(result["rows"][:3], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
