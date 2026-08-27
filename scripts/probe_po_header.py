import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.oracle_client import OracleClient, dump_json
from backend.po_tools import HEADER_FIELDS, fetch_purchase_order_header


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one PO header and supplier communication fields.")
    parser.add_argument("--po-header-id", required=True, help="Example from URL: poHeaderId=300000339795840")
    parser.add_argument("--out", default=str(ROOT / "outputs" / "po_header_raw.json"))
    args = parser.parse_args()

    client = OracleClient()
    header = fetch_purchase_order_header(client, args.po_header_id)
    output = {"resource": f"purchaseOrders/{args.po_header_id}", "fieldsRequested": HEADER_FIELDS.split(","), "item": header}
    dump_json(Path(args.out), output)
    print(f"Saved purchase order header to {args.out}")
    print(json.dumps(header, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
