"""Validation helpers for OpenAI-compatible tool definitions."""

from __future__ import annotations

from typing import Any


def validate_openai_tool_schema(tool: dict[str, Any]) -> None:
    """Raise ``ValueError`` if a tool is not a valid function tool shape."""
    if tool.get("type") != "function":
        raise ValueError("tool.type must be 'function'")
    function = tool.get("function")
    if not isinstance(function, dict):
        raise ValueError("tool.function must be an object")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("tool.function.name must be a non-empty string")
    description = function.get("description")
    if not isinstance(description, str) or not description:
        raise ValueError(f"tool '{name}' description must be a non-empty string")
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError(f"tool '{name}' parameters must be an object schema")
    if parameters.get("type") != "object":
        raise ValueError(f"tool '{name}' parameters.type must be 'object'")
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"tool '{name}' parameters.properties must be an object")
    required = parameters.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(f"tool '{name}' parameters.required must be a string list")
    missing = [item for item in required if item not in properties]
    if missing:
        raise ValueError(f"tool '{name}' requires undefined properties: {missing}")


def validate_openai_tool_schemas(tools: list[dict[str, Any]]) -> None:
    """Validate a list of tool definitions and detect duplicate names."""
    names: set[str] = set()
    for tool in tools:
        validate_openai_tool_schema(tool)
        name = tool["function"]["name"]
        if name in names:
            raise ValueError(f"duplicate tool name: {name}")
        names.add(name)
