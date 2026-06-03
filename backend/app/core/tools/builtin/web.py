"""Builtin web tools: web_fetch, web_search.

- ``web_fetch`` — HTTP GET a URL and return the response body (truncated).
- ``web_search`` — Placeholder that returns a descriptive message.
"""

import httpx

# Maximum number of characters to return from a web_fetch response.
_MAX_FETCH_LENGTH = 5000

WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch the content of a URL via HTTP GET",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


async def execute(tool_name: str, args: dict) -> str:
    """Execute a web tool.

    Args:
        tool_name: One of ``web_fetch``, ``web_search``.
        args: Dictionary with tool-specific arguments.

    Returns:
        Result string.

    Raises:
        ValueError: If *tool_name* is not recognised.
        httpx.HTTPError: On HTTP failures (web_fetch only).
    """
    if tool_name == "web_fetch":
        url = args["url"]
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            body = resp.text
            if len(body) > _MAX_FETCH_LENGTH:
                body = body[:_MAX_FETCH_LENGTH] + "\n\n[truncated...]"
            return body

    elif tool_name == "web_search":
        query = args["query"]
        return (
            f"Web search is not yet configured. "
            f"Query received: {query!r}. "
            f"To enable, integrate with Google Custom Search, Bing API, "
            f"or another search provider."
        )

    raise ValueError(f"Unknown web tool: {tool_name}")
