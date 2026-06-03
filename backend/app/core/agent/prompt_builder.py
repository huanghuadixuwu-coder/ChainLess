"""Token-aware context builder.

Provides a utility to count tokens (approximate) and build a context list
that stays within a configured token budget while preserving the most
recent messages.
"""

try:
    import tiktoken
except ImportError:
    tiktoken = None  # fallback in count_tokens


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Approximate token count for *text* using tiktoken.

    Falls back to a ``len(text) // 4`` heuristic when tiktoken fails
    (e.g. unsupported model or missing tokenizer file).
    """
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def build_context(
    system_instructions: str,
    messages: list[dict],
    max_context_tokens: int = 60000,
    min_recent_messages: int = 4,
) -> list[dict]:
    """Build a token-aware context list.

    Always includes the system instruction message.  Always includes the
    last *min_recent_messages* messages (provided they fit in the token
    budget).  Older messages are included working backwards until the
    budget is exhausted.

    Args:
        system_instructions: The system-level prompt.
        messages: Full message history (role/content dicts).
        max_context_tokens: Hard cap on total tokens for the returned list.
        min_recent_messages: Minimum number of trailing messages to retain.

    Returns:
        A list of message dicts suitable for passing to the LLM gateway.
    """
    budget = max_context_tokens - count_tokens(system_instructions)
    result = [{"role": "system", "content": system_instructions}]

    # Split into "recent" (guaranteed) and "remaining" (best-effort).
    recent = messages[-min_recent_messages:] if len(messages) >= min_recent_messages else messages
    remaining = messages[:-min_recent_messages] if len(messages) >= min_recent_messages else []

    selected: list[dict] = []

    # Always try to include the most recent messages.
    for msg in reversed(recent):
        tokens = count_tokens(msg.get("content", "") or "")
        if tokens <= budget:
            selected.insert(0, msg)
            budget -= tokens

    # Fill the remaining budget with older messages, oldest-first.
    for msg in reversed(remaining):
        tokens = count_tokens(msg.get("content", "") or "")
        if tokens <= budget:
            selected.insert(0, msg)
            budget -= tokens
        else:
            break

    result.extend(selected)
    return result
