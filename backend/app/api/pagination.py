"""Pagination helper for consistent list endpoint responses.

Usage::

    from app.api.pagination import paginated_response

    @router.get("/")
    async def list_items(
        request: Request,
        limit: int = 20,
        offset: int = 0,
        ...
    ):
        items = [...]
        total = ...
        return paginated_response(items, total, limit, offset, request)
"""

from fastapi import Request


def paginated_response(
    items: list,
    total: int,
    limit: int,
    offset: int,
    request: Request,
) -> dict:
    """Build a paginated response with the standard envelope.

    Returns::

        {
            "items": [...],
            "total": N,
            "limit": N,
            "offset": N,
            "next": "http://..." | None,
        }
    """
    next_url: str | None = None
    if offset + limit < total:
        next_url = str(
            request.url.include_query_params(
                limit=limit,
                offset=offset + limit,
            )
        )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next": next_url,
    }
