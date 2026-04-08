from langchain_core.tools import tool
from datetime import datetime, timezone


@tool
def get_current_time() -> str:
    """Get the current date and time in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression. Only supports basic arithmetic.

    Args:
        expression: A mathematical expression like '2 + 3 * 4'
    """
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: expression contains invalid characters"
    try:
        result = eval(expression)  # noqa: S307 - input sanitized above
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def get_general_tools():
    return [get_current_time, calculator]
