import os
from typing import Any
import re
from dotenv import load_dotenv

try:
    from .po_tools import search_po_schedules
except ImportError:
    from po_tools import search_po_schedules


load_dotenv()

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20

UNAVAILABLE_REPLY = (
    "I can help with overdue open purchase order schedules right now. "
    "That request is not available yet."
)

GREETING_REPLY = (
    "Hi! I can help you find overdue open purchase order schedules from Oracle Fusion. "
    "Ask me something like: list items that should have been delivered by today but are still open."
)

HELP_REPLY = (
    "I currently specialize in one Oracle Fusion workflow: finding overdue open purchase order schedules. "
    "I can show order number, destination type, due date, delay, status, supplier, and item description."
)

SYSTEM_PROMPT = """
You are a routing assistant for an Oracle Fusion Purchase Order chatbot.

Your job is not to answer directly. Your job is to decide whether the user request can be handled by the available PO schedule search tool.

Supported requests:
- overdue open purchase order schedules
- overdue POs for a supplier
- overdue POs above an amount
- overdue POs late by more than N days
- partially received overdue POs
- schedules due today
- schedules due this week
- schedules near due
- suppliers with the most overdue schedules

If the user asks normal greeting/help, answer normally.
If the user asks anything outside these supported features, do not call a tool.
Politely ask the user to rephrase with one of the supported procurement queries.

When calling the tool:
- Extract supplier names exactly.
- For "for Amazon", use supplier = "Amazon".
- For "supplier Midtown Computer Supplies", use supplier = "Midtown Computer Supplies".
- For "more than 30 days late", use min_late_days = 30.
- For "above 10000", use min_amount = 10000.
- For "top suppliers" or "which suppliers have most overdue", use group_by_supplier = true.
- For "partially received", use partially_received = true.
- For "due today", set overdue = false and due_window = "today".
- For "due this week", set overdue = false and due_window = "this_week".
- For "near due", set overdue = false and due_window = "near_due".

Never invent unsupported filters.
Never return all overdue schedules if the user clearly asked for a supplier-specific result.
"""

FUNCTION_DECLARATIONS = [
    {
        "name": "search_po_schedules",
        "description": (
            "Search Oracle Fusion purchase order schedules. Supports overdue open schedules, supplier filter, "
            "overdue more than N days, due today, near due, due this week, partially received schedules, "
            "amount above a threshold, and supplier overdue summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "supplier": {"type": "string"},
                "overdue": {"type": "boolean"},
                "min_late_days": {"type": "integer"},
                "min_amount": {"type": "number"},
                "due_window": {
                    "type": "string",
                    "enum": ["today", "near_due", "this_week"]
                },
                "partially_received": {"type": "boolean"},
                "group_by_supplier": {"type": "boolean"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                },
            },
        },
    }
]

def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""
def _is_greeting(text: str) -> bool:
    cleaned = text.strip().lower().replace("!", "").replace(".", "")
    return cleaned in {"hi", "hello", "hey", "hii", "hy", "good morning", "good afternoon", "good evening"}


def _is_help_request(text: str) -> bool:
    lowered = text.strip().lower()
    help_phrases = (
        "what can you do",
        "what do you do",
        "help",
        "how can you help",
        "your speciality",
        "your specialty",
        "specialities",
        "specialties",
        "capabilities",
        "features",
    )
    return any(phrase in lowered for phrase in help_phrases)

def _simple_intent_fallback(text: str) -> bool:
    lowered = text.lower()
    po_words = ("purchase order", "po", "order", "schedule", "supplier", "item")
    intent_words = (
        "overdue",
        "late",
        "delay",
        "delayed",
        "due today",
        "due this week",
        "near due",
        "partially received",
        "above",
        "more than",
        "most overdue",
        "supplier",
        "not delivered",
        "undelivered",
    )
    return any(w in lowered for w in po_words) and any(w in lowered for w in intent_words)

def _fallback_args_from_text(text: str) -> dict[str, Any]:
    lowered = text.lower()
    args: dict[str, Any] = {
        "page": DEFAULT_PAGE,
        "page_size": DEFAULT_PAGE_SIZE,
        "sort_order": "desc",
        "overdue": True,
    }

    quoted_supplier = re.search(
        r'(?:supplier|vendor|for|from)\s+["“]([^"”]+)["”]',
        text,
        flags=re.IGNORECASE,
    )

    supplier_match = quoted_supplier or re.search(
        r"(?:supplier|vendor|for|from)\s+([a-zA-Z0-9&.,' -]+)",
        text,
        flags=re.IGNORECASE,
    )

    if supplier_match:
        supplier = supplier_match.group(1).strip()
        supplier = re.split(
            r"\b(overdue|above|more than|greater than|due|partially|received|open|with|where|by)\b",
            supplier,
            flags=re.IGNORECASE,
        )[0].strip(" .,\"'")
        if supplier and supplier.lower() not in {"po", "pos", "purchase order", "purchase orders", "all"}:
            args["supplier"] = supplier

    late_match = re.search(r"(?:more than|over|late by)\s+(\d+)\s+days?", lowered)
    if late_match:
        args["min_late_days"] = int(late_match.group(1))

    amount_match = re.search(r"(?:above|more than|greater than|over)\s+([\d,]+(?:\.\d+)?)", lowered)
    if amount_match and "day" not in lowered[amount_match.start():amount_match.end() + 12]:
        args["min_amount"] = float(amount_match.group(1).replace(",", ""))

    if "partially received" in lowered or "partial received" in lowered:
        args["partially_received"] = True

    if "most overdue" in lowered or "top supplier" in lowered or "which suppliers" in lowered:
        args["group_by_supplier"] = True

    if "due today" in lowered:
        args["overdue"] = False
        args["due_window"] = "today"
    elif "due this week" in lowered:
        args["overdue"] = False
        args["due_window"] = "this_week"
    elif "near due" in lowered or "nearly due" in lowered:
        args["overdue"] = False
        args["due_window"] = "near_due"

    return args

def _tool_result_response(result: dict[str, Any], router: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    mode = result.get("mode", "schedule_table")
    rows = result.get("rows", [])

    if mode == "supplier_summary":
        total = result.get("resultCount", len(rows))
        return {
            "reply": f"Here are the top suppliers by overdue schedule count. I found {total} supplier(s).",
            "table": rows,
            "mode": mode,
            "page": 1,
            "pageSize": result.get("pageSize", total),
            "totalPages": 1,
            "overdueOpenCount": total,
            "toolCalls": tool_calls,
            "router": router,
        }

    total = result.get("resultCount", result.get("overdueOpenCount", len(rows)))
    page = result.get("page", DEFAULT_PAGE)
    total_pages = result.get("totalPages", 1)

    return {
        "reply": (
            f"I found {total} matching purchase order schedule(s). "
            f"Showing page {page} of {total_pages} on the right."
        ),
        "table": rows,
        "mode": mode,
        "page": page,
        "pageSize": result.get("pageSize", DEFAULT_PAGE_SIZE),
        "totalPages": total_pages,
        "overdueOpenCount": total,
        "toolCalls": tool_calls,
        "router": router,
    }

def _run_po_search_tool(
    args: dict[str, Any] | None = None,
    oracle_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = args or {}
    return search_po_schedules(
        supplier=args.get("supplier") or None,
        overdue=args.get("overdue", True),
        min_late_days=args.get("min_late_days") or args.get("minLateDays"),
        due_window=args.get("due_window") or args.get("dueWindow"),
        min_amount=args.get("min_amount") or args.get("minAmount"),
        partially_received=bool(args.get("partially_received") or args.get("partiallyReceived")),
        group_by_supplier=bool(args.get("group_by_supplier") or args.get("groupBySupplier")),
        page=args.get("page") or DEFAULT_PAGE,
        page_size=args.get("page_size") or args.get("pageSize") or DEFAULT_PAGE_SIZE,
        sort_order=args.get("sort_order") or args.get("sortOrder") or "desc",
        limit=args.get("limit"),
        max_pages=args.get("max_pages") or args.get("maxPages"),
        oracle_config=oracle_config,
    )
    
async def run_chat(messages: list[dict[str, str]], oracle_config: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    latest_text = _latest_user_text(messages)
    if _is_greeting(latest_text):
        return {
            "reply": GREETING_REPLY,
            "table": [],
            "toolCalls": [],
            "router": "small-talk",
        }

    if _is_help_request(latest_text):
        return {
            "reply": HELP_REPLY,
            "table": [],
            "toolCalls": [],
            "router": "help",
        }
    if not api_key:
        if not _simple_intent_fallback(latest_text):
            return {"reply": UNAVAILABLE_REPLY, "table": [], "toolCalls": [], "router": "fallback"}

        fallback_args = _fallback_args_from_text(latest_text)
        result = _run_po_search_tool(fallback_args, oracle_config=oracle_config)
        tool_calls = [{"name": "search_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
        response = _tool_result_response(result, "fallback", tool_calls)
        response["reply"] = "Gemini is not configured, so I used the local fallback router. " + response["reply"]
        return response

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed. Run pip install -r requirements.txt.") from exc

    client = genai.Client(api_key=api_key)
    declarations = [
        types.FunctionDeclaration(
            name=item["name"],
            description=item["description"],
            parameters_json_schema=item["parameters"],
        )
        for item in FUNCTION_DECLARATIONS
    ]

    tool = types.Tool(function_declarations=declarations)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    transcript = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[-8:])
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=transcript)])]
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
    except Exception:
        if not _simple_intent_fallback(latest_text):
            return {"reply": UNAVAILABLE_REPLY, "table": [], "toolCalls": [], "router": "fallback-after-gemini-error"}

        fallback_args = _fallback_args_from_text(latest_text)
        result = _run_po_search_tool(fallback_args, oracle_config=oracle_config)
        tool_calls = [{"name": "search_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
        response_data = _tool_result_response(result, "fallback-after-gemini-error", tool_calls)
        response_data["reply"] = "Gemini routing failed, so I used the local fallback router. " + response_data["reply"]
        return response_data

    function_calls = list(getattr(response, "function_calls", None) or [])

    if not function_calls:
        if _simple_intent_fallback(latest_text):
            fallback_args = _fallback_args_from_text(latest_text)
            result = _run_po_search_tool(fallback_args, oracle_config=oracle_config)
            tool_calls = [{"name": "search_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
            return _tool_result_response(result, "fallback-after-no-tool-call", tool_calls)

        return {
            "reply": (
                "I could not map that request to the current procurement tools. "
                "Please ask using details like supplier name, overdue days, amount, "
                "due date window, or partially received schedules."
            ),
            "table": [],
            "toolCalls": [],
            "router": "gemini-unsupported",
        }

    tool_calls = []

    for call in function_calls:
        name = getattr(call, "name", None)
        args = dict(getattr(call, "args", None) or {})

        if name != "search_po_schedules":
            continue

        fallback_args = _fallback_args_from_text(latest_text)
        result = _run_po_search_tool(fallback_args, oracle_config=oracle_config)
        tool_calls.append({"name": name, "args": args, "resultSummary": _summarize_result(result)})
        return _tool_result_response(result, "gemini", tool_calls)

    return {"reply": UNAVAILABLE_REPLY, "table": [], "toolCalls": tool_calls, "router": "gemini"}


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "today": result.get("today"),
        "candidateCount": result.get("candidateCount"),
        "overdueOpenCount": result.get("overdueOpenCount"),
        "page": result.get("page"),
        "pageSize": result.get("pageSize"),
        "totalPages": result.get("totalPages"),
    }