import pytest
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


performance_probe = _load_script("performance_probe")
restore_drill = _load_script("restore_drill")
spec_complete_probe = _load_script("spec_complete_probe")


def test_restore_drill_quotes_safe_database_identifiers() -> None:
    assert restore_drill._quote_ident("chainless_restore_drill_abc123") == '"chainless_restore_drill_abc123"'


@pytest.mark.parametrize("identifier", ["bad-name", "bad;drop", "bad name", ""])
def test_restore_drill_rejects_unsafe_database_identifiers(identifier: str) -> None:
    with pytest.raises(ValueError):
        restore_drill._quote_ident(identifier)


def test_hackernews_parser_extracts_exact_top_ten() -> None:
    html = "".join(
        f'<tr class="athing submission" id="{idx}"><td><span class="titleline">'
        f'<a href="item?id={idx}">Story &amp; {idx}</a></span></td></tr>'
        for idx in range(12)
    )
    rows = performance_probe._extract_hackernews_top10(html)
    assert len(rows) == 10
    assert rows[0] == {"title": "Story & 0", "url": "item?id=0"}
    assert rows[-1]["title"] == "Story & 9"


def test_hackernews_script_contains_count_and_titles_contract() -> None:
    script = performance_probe._hackernews_script(
        [{"title": f"Story {idx}", "url": f"https://example.com/{idx}"} for idx in range(10)]
    )
    assert "assert len(items) == 10" in script
    assert '"count"' in script
    assert '"titles"' in script


def test_fibonacci_script_prints_expected_v1_gate_value() -> None:
    namespace: dict[str, object] = {}
    output: list[str] = []
    exec(
        performance_probe._fibonacci_script().replace("print(fibonacci(10))", "output.append(str(fibonacci(10)))"),
        {"output": output},
        namespace,
    )
    assert output == ["55"]


def test_spec_complete_sse_parser_and_contract_assertions() -> None:
    frames = (
        'event: text\n'
        'data: {"content":"hello"}\n\n'
        'event: done\n'
        'data: {"tokens_used":1}\n\n'
    )
    assert spec_complete_probe._parse_sse(frames) == [
        ("text", {"content": "hello"}),
        ("done", {"tokens_used": 1}),
    ]
    spec_complete_probe._assert_page(
        {"items": [], "total": 0, "limit": 10, "offset": 0, "next": None},
        "empty page",
    )
    spec_complete_probe._assert_error(
        {"error": {"code": "AUTH_EXPIRED", "message": "auth", "detail": None}},
        "AUTH_EXPIRED",
        "auth",
    )


def test_spec_complete_contract_assertions_reject_bad_shapes() -> None:
    with pytest.raises(AssertionError):
        spec_complete_probe._assert_page({"items": []}, "bad page")
    with pytest.raises(AssertionError):
        spec_complete_probe._assert_error({"error": {"code": "OTHER"}}, "AUTH_EXPIRED", "bad error")
