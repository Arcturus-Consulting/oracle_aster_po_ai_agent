import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient
from backend.po_tools import HEADER_FIELDS


def main() -> int:
    client = OracleClient()
    rows = client.paginate(
        "purchaseOrders",
        params={
            "fields": HEADER_FIELDS,
            "onlyData": "true",
            "q": "SupplierEmailAddress is not null",
        },
        limit=25,
        max_pages=10,
    )

    print(f"Found {len(rows)} purchase order header(s) with SupplierEmailAddress.")
    print(json.dumps(rows[:10], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())