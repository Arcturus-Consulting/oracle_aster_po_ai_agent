# Oracle Fusion PO Chatbot

This is a runnable chatbot-only project for Oracle Fusion purchase order schedules.

It supports one current user intent:

```text
List purchase order schedules/items where due date is before today and status is Open.
```

For other queries, Gemini should route to a polite "not available yet" response.

## Folder Contents

```text
backend/   FastAPI app, Gemini router, Oracle REST client, PO schedule tool, email draft/send helper
frontend/  Chat dashboard UI, no attachments
scripts/   Oracle schema and logic probes
tests/     Local unit tests for date/status/mail logic
outputs/   Probe output files
```

## Setup

Open PowerShell:

```powershell
cd "C:\Users\uditn\OneDrive\Documents\ChatGPT\prep1\oracle-po-chatbot-full"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Fill `.env`:

```env
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.5-flash

ORACLE_BASE_URL=https://your-oracle-fusion-host
ORACLE_AUTH_MODE=basic
ORACLE_USERNAME=your_oracle_user
ORACLE_PASSWORD=your_oracle_password
TODAY_DATE=2026-08-24
```

`TODAY_DATE` is optional. Use it when you want repeatable testing against a specific day.

## Run Local Tests

```powershell
pytest -q
```

These tests do not call Oracle.

## Probe Oracle Before Running the Chatbot

```powershell
python scripts\probe_connection.py
python scripts\probe_po_schedules.py --limit 25 --max-pages 2
python scripts\probe_overdue_logic.py --limit 50 --max-pages 5
```

Outputs are saved in:

```text
outputs\po_schedules_raw.json
outputs\overdue_open_summary.json
```

If a schedule row has `poHeaderId`, `poLineId`, and `lineLocationId`, verify header and destination details:

```powershell
python scripts\probe_po_header.py --po-header-id 300000339795840
python scripts\probe_nested_schedule.py --po-header-id 300000339795840 --po-line-id YOUR_PO_LINE_ID --line-location-id YOUR_LINE_LOCATION_ID
```

## Run the Full App

```powershell
.\run_backend.ps1 -Port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Try:

```text
list me all the items which should have been delivered by today but are still open
```

## Mail Button

Each row shows a Mail button only when Oracle returns `SupplierEmailAddress` from the purchase order header.

By default, SMTP is disabled. The button will open a pre-drafted `mailto:` email. To send directly through backend SMTP, configure:

```env
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_TLS=true
```

## Important Notes

- Oracle schedule listing uses `GET /fscmRestApi/resources/11.13.18.05/purchaseOrderSchedules`.
- Supplier communication fields are fetched from `GET /fscmRestApi/resources/11.13.18.05/purchaseOrders/{POHeaderId}`.
- Destination type is fetched from nested schedule detail when IDs are available.
- No attachment upload exists in this version.
