from datetime import date

from backend.email_service import build_supplier_followup_email
from backend.po_tools import is_overdue_open_schedule, normalize_schedule_row, parse_oracle_date


def test_parse_oracle_date_common_formats():
    assert parse_oracle_date("2026-08-20") == date(2026, 8, 20)
    assert parse_oracle_date("8/20/26") == date(2026, 8, 20)
    assert parse_oracle_date("2026-08-20T10:15:00+00:00") == date(2026, 8, 20)


def test_overdue_open_logic_uses_due_date_before_today():
    row = {"DueDate": "2026-08-20", "ScheduleStatus": "Open"}
    assert is_overdue_open_schedule(row, date(2026, 8, 24)) is True

    due_today = {"DueDate": "2026-08-24", "ScheduleStatus": "Open"}
    assert is_overdue_open_schedule(due_today, date(2026, 8, 24)) is False

    closed = {"DueDate": "2026-08-20", "ScheduleStatus": "Closed"}
    assert is_overdue_open_schedule(closed, date(2026, 8, 24)) is False


def test_normalized_row_contains_dashboard_columns_and_email_draft():
    row = {
        "OrderNumber": "US165362",
        "POHeaderId": 300000339795840,
        "POLineId": 10,
        "LineLocationId": 20,
        "LineNumber": 1,
        "ScheduleNumber": 1,
        "DueDate": "2026-08-20",
        "ScheduleStatus": "Open",
        "ItemDescription": "Recycled Plastic Scissors",
        "Supplier": "EcoSupply",
    }
    header = {"SupplierEmailAddress": "supplier@example.com", "SupplierCommunicationMethod": "Email"}
    nested = {"DestinationType": "Expense", "DeliverToLocation": "Seattle"}

    normalized = normalize_schedule_row(row, today=date(2026, 8, 24), header=header, nested_schedule=nested)

    assert normalized["orderNumber"] == "US165362"
    assert normalized["destinationType"] == "Expense"
    assert normalized["dueDate"] == "2026-08-20"
    assert normalized["lateDays"] == 4
    assert normalized["mailAvailable"] is True
    assert "mailto:" in normalized["emailDraft"]["mailto"]


def test_email_draft_handles_missing_email():
    draft = build_supplier_followup_email({"orderNumber": "US165362", "dueDate": "2026-08-20"})
    assert draft["to"] == ""
    assert draft["mailto"] == ""
    assert "US165362" in draft["subject"]
