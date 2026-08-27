import os
from typing import Any

from dotenv import load_dotenv

try:
    from .po_tools import get_overdue_open_po_schedules
except ImportError:
    from po_tools import get_overdue_open_po_schedules


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
You are an Oracle Fusion procurement chatbot router.

If the user greets you or asks what you can do, answer naturally and briefly.
Your specialty is finding overdue open purchase order schedules from Oracle Fusion.

Your only available Oracle tool is get_overdue_open_po_schedules.
Call it only when the user asks for purchase order items or schedules that are overdue, due before today, still open, pending delivery, or not delivered.
For unrelated business requests, do not call a tool. Reply politely that the request is not available yet.
Do not invent Oracle data. Oracle facts must come from the tool result.
After the tool returns, summarize the count and tell the user the table is shown on the right.
"""

FUNCTION_DECLARATIONS = [
    {
        "name": "get_overdue_open_po_schedules",
        "description": (
            "Fetch a paginated page of overdue open purchase order schedules from Oracle Fusion. "
            "Use only for PO schedules/items due before today and still open/not delivered."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number to return. Default is 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Rows per page. Default is 20.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Oracle page size for backend scanning. Default comes from env.",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum Oracle pages to scan. Default comes from env.",
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
    overdue_words = (
        "overdue",
        "late",
        "delay",
        "delayed",
        "due before",
        "due today",
        "delivered by today",
        "not delivered",
        "undelivered",
    )
    po_words = ("purchase order", "po", "order", "schedule", "supplier", "item")
    open_words = ("open", "pending", "not delivered", "undelivered")
    return any(w in lowered for w in overdue_words) and any(w in lowered for w in po_words + open_words)


def _tool_result_response(result: dict[str, Any], router: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    total = result.get("overdueOpenCount", len(result.get("rows", [])))
    page = result.get("page", DEFAULT_PAGE)
    total_pages = result.get("totalPages", 1)

    return {
        "reply": (
            f"There are {total} overdue open purchase order schedule(s). "
            f"Showing page {page} of {total_pages} on the right."
        ),
        "table": result.get("rows", []),
        "page": page,
        "pageSize": result.get("pageSize", DEFAULT_PAGE_SIZE),
        "totalPages": total_pages,
        "overdueOpenCount": total,
        "toolCalls": tool_calls,
        "router": router,
    }

def _run_overdue_tool(
    args: dict[str, Any] | None = None,
    oracle_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = args or {}
    return get_overdue_open_po_schedules(
        page=args.get("page") or DEFAULT_PAGE,
        page_size=args.get("page_size") or args.get("pageSize") or DEFAULT_PAGE_SIZE,
        sort_order=args.get("sort_order") or args.get("sortOrder") or "desc",
        destination_type=args.get("destination_type") or args.get("destinationType") or "",
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

        result = _run_overdue_tool(oracle_config=oracle_config)
        tool_calls = [{"name": "get_overdue_open_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
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

        result = _run_overdue_tool(oracle_config=oracle_config)
        tool_calls = [{"name": "get_overdue_open_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
        response_data = _tool_result_response(result, "fallback-after-gemini-error", tool_calls)
        response_data["reply"] = "Gemini routing failed, so I used the local fallback router. " + response_data["reply"]
        return response_data

    function_calls = list(getattr(response, "function_calls", None) or [])

    if not function_calls:
        if _simple_intent_fallback(latest_text):
            result = _run_overdue_tool(oracle_config=oracle_config)
            tool_calls = [{"name": "get_overdue_open_po_schedules", "args": {}, "resultSummary": _summarize_result(result)}]
            return _tool_result_response(result, "fallback-after-no-tool-call", tool_calls)

        return {
            "reply": response.text or UNAVAILABLE_REPLY,
            "table": [],
            "toolCalls": [],
            "router": "gemini",
        }

    tool_calls = []

    for call in function_calls:
        name = getattr(call, "name", None)
        args = dict(getattr(call, "args", None) or {})

        if name != "get_overdue_open_po_schedules":
            continue

        result = _run_overdue_tool(args, oracle_config=oracle_config)
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