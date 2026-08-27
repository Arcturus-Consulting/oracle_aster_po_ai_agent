import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient


def main() -> int:
    client = OracleClient()
    checks = [
        ("purchaseOrderSchedules", {"limit": 1, "onlyData": "true"}),
        ("purchaseOrders", {"limit": 1, "onlyData": "true"}),
    ]

    print("Oracle Fusion connection probe")
    print(f"Base URL: {client.base_url}")
    print(f"Auth mode: {client.auth_mode}")

    for resource, params in checks:
        print(f"\nGET {resource}")
        data = client.get(resource, params)
        items = data.get("items", [])
        print(f"count={data.get('count')} hasMore={data.get('hasMore')} returned={len(items)}")
        if items:
            print("first_item_keys=" + json.dumps(sorted(items[0].keys()), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
