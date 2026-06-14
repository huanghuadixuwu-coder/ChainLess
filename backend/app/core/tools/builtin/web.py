"""Builtin web and weather tools."""

import json
import re
import urllib.parse
from html import unescape

import httpx

_MAX_FETCH_LENGTH = 5000
_MAX_SEARCH_RESULTS = 5

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Chainless/1.0"},
        )
    return _client


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", unescape(clean)).strip()


def _decode_bing_url(url: str) -> str:
    url = unescape(url)
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
        query = urllib.parse.parse_qs(parsed.query)
        target = (query.get("u") or [""])[0]
        if target.startswith("a1"):
            import base64

            payload = target[2:]
            padding = "=" * (-len(payload) % 4)
            try:
                return base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            except Exception:
                return url
    return url


def _parse_bing_results(html: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.findall(
        r'<li\s+class="b_algo"[^>]*>(.*?)</li>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        link = re.search(
            r"<h2[^>]*>.*?<a\s+[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not link:
            continue

        snippet = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        url = _decode_bing_url(link.group(1))
        title = _strip_html(link.group(2))
        if not title or not url.startswith(("http://", "https://")):
            continue

        results.append(
            {
                "title": title,
                "url": url,
                "snippet": _strip_html(snippet.group(1)) if snippet else "",
                "source": "bing",
            }
        )
        if len(results) >= _MAX_SEARCH_RESULTS:
            break
    return results


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
            "description": "Search the web for public information",
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
    {
        "type": "function",
        "function": {
            "name": "weather_get",
            "description": (
                "Get current weather and today's forecast for a city. "
                "Use this for questions about weather, temperature, rain, or forecast."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name, for example Wuxi",
                    },
                },
                "required": ["location"],
            },
        },
    },
]


async def _web_fetch(url: str) -> str:
    resp = await _get_client().get(url, follow_redirects=True)
    resp.raise_for_status()
    body = resp.text
    if len(body) > _MAX_FETCH_LENGTH:
        body = body[:_MAX_FETCH_LENGTH] + "\n\n[truncated...]"
    return body


async def _web_search(query: str) -> str:
    try:
        resp = await _get_client().get(
            "https://www.bing.com/search",
            params={"q": query, "count": str(_MAX_SEARCH_RESULTS)},
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
        )
        resp.raise_for_status()
        results = _parse_bing_results(resp.text)
        if not results:
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "error": "No structured search results parsed. Try web_fetch with a specific URL.",
                },
                ensure_ascii=False,
            )
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "query": query,
                "results": [],
                "error": f"Search failed: {exc}. Try web_fetch with a specific URL.",
            },
            ensure_ascii=False,
        )


async def _weather_get(location: str) -> str:
    encoded = urllib.parse.quote(location)
    url = f"https://wttr.in/{encoded}?format=j1"
    resp = await _get_client().get(
        url,
        headers={"User-Agent": "curl/8.0"},
    )
    resp.raise_for_status()
    payload = json.loads(resp.text)

    current = (payload.get("current_condition") or [{}])[0]
    today = (payload.get("weather") or [{}])[0]
    hourly = today.get("hourly") or []

    desc = ((current.get("weatherDesc") or [{}])[0]).get("value", "Unknown")
    max_temp = today.get("maxtempC", "?")
    min_temp = today.get("mintempC", "?")
    humidity = current.get("humidity", "?")
    feels_like = current.get("FeelsLikeC", "?")
    rain_chance = max(
        [int(item.get("chanceofrain", 0) or 0) for item in hourly] or [0]
    )

    return (
        f"Weather in {location}: {desc}. "
        f"Current temperature {current.get('temp_C', '?')}C, feels like {feels_like}C, "
        f"humidity {humidity}%. "
        f"Today's high {max_temp}C, low {min_temp}C, "
        f"chance of rain about {rain_chance}%."
    )


async def execute(tool_name: str, args: dict) -> str:
    """Execute a builtin web or weather tool."""
    if tool_name == "web_fetch":
        return await _web_fetch(args["url"])
    if tool_name == "web_search":
        return await _web_search(args["query"])
    if tool_name == "weather_get":
        return await _weather_get(args["location"])
    raise ValueError(f"Unknown web tool: {tool_name}")
