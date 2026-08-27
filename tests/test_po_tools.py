from datetime import date

from backend.email_service import build_supplier_followup_email
from backend.po_tools import (
    build_schedule_query,
    is_overdue_open_schedule,
    is_partially_received_schedule,
    normalize_schedule_row,
    number_value,
    parse_oracle_date,
)

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


def test_number_value_handles_oracle_amounts():
    assert number_value("10,000.50") == 10000.50
    assert number_value(None) == 0.0
    assert number_value("bad") == 0.0


def test_partially_received_logic():
    assert is_partially_received_schedule({"Quantity": 10, "ReceivedQuantity": 4}) is True
    assert is_partially_received_schedule({"Quantity": 10, "ReceivedQuantity": 0}) is False
    assert is_partially_received_schedule({"Quantity": 10, "ReceivedQuantity": 10}) is False


def test_build_schedule_query_for_supplier_and_late_days():
    query = build_schedule_query(
        today=date(2026, 8, 27),
        supplier="Amazon",
        min_late_days=30,
    )

    assert "ScheduleStatus='Open'" in query
    assert "ProcurementBU='US1 Business Unit'" in query
    assert "Supplier='Amazon'" in query
    assert "RequestedDeliveryDate<'2026-07-28'" in query


def test_build_schedule_query_for_due_this_week():
    query = build_schedule_query(today=date(2026, 8, 27), overdue=False, due_window="this_week")

    assert "RequestedDeliveryDate>='2026-08-27'" in query
    assert "RequestedDeliveryDate<='2026-09-03'" in query