"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type ToolOption } from "@/lib/api";

interface ToolPickerProps {
  query: string;
  open: boolean;
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onActiveToolChange?: (tool: ToolOption | null) => void;
  onActiveOptionIdChange?: (id: string | null) => void;
  onSelect: (tool: ToolOption) => void;
}

export function ToolPicker({
  query,
  open,
  activeIndex,
  onActiveIndexChange,
  onActiveToolChange,
  onActiveOptionIdChange,
  onSelect,
}: ToolPickerProps) {
  const [tools, setTools] = useState<ToolOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || tools !== null || error) return;
    let cancelled = false;

    api
      .getAvailableTools()
      .then((items) => {
        if (cancelled) return;
        setTools(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Tools unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, [error, open, tools]);

  const filteredTools = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const enabledTools = (tools || []).filter((tool) => tool.enabled !== false);
    if (!normalized) return enabledTools.slice(0, 8);
    return enabledTools
      .filter(
        (tool) =>
          tool.name.toLowerCase().includes(normalized) ||
          (tool.description || "").toLowerCase().includes(normalized)
      )
      .slice(0, 8);
  }, [query, tools]);

  const normalizedActiveIndex = normalizeActiveIndex(
    open ? activeIndex : -1,
    filteredTools.length
  );
  const activeTool =
    open && normalizedActiveIndex >= 0 ? filteredTools[normalizedActiveIndex] : null;

  useEffect(() => {
    onActiveToolChange?.(activeTool);
    onActiveOptionIdChange?.(activeTool ? toolOptionId(activeTool.name) : null);
  }, [activeTool, onActiveOptionIdChange, onActiveToolChange]);

  if (!open) return null;
  const isLoading = tools === null && !error;

  return (
    <div
      id="tool-picker-listbox"
      className="absolute bottom-full left-0 mb-2 w-full overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900 shadow-xl"
      role="listbox"
      aria-label="Tool picker"
      tabIndex={-1}
      data-testid="tool-picker"
      onKeyDown={(event) => {
        if (filteredTools.length === 0) return;
        if (event.key === "ArrowDown") {
          event.preventDefault();
          onActiveIndexChange(normalizedActiveIndex + 1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          onActiveIndexChange(normalizedActiveIndex - 1);
        } else if (event.key === "Home") {
          event.preventDefault();
          onActiveIndexChange(0);
        } else if (event.key === "End") {
          event.preventDefault();
          onActiveIndexChange(filteredTools.length - 1);
        } else if ((event.key === "Enter" || event.key === "Tab") && activeTool) {
          event.preventDefault();
          onSelect(activeTool);
        }
      }}
    >
      <div className="max-h-64 overflow-auto p-1">
        {isLoading ? (
          <p className="px-3 py-2 text-xs text-zinc-500">Loading tools...</p>
        ) : error ? (
          <p className="px-3 py-2 text-xs text-red-300">
            Tools unavailable: {error}
          </p>
        ) : filteredTools.length ? (
          filteredTools.map((tool, index) => {
            const selected = index === normalizedActiveIndex;
            return (
            <button
              key={tool.name}
              id={toolOptionId(tool.name)}
              type="button"
              role="option"
              aria-selected={selected}
              data-testid="tool-option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onSelect(tool)}
              className={`block w-full rounded-md px-3 py-2 text-left hover:bg-zinc-800 ${
                selected ? "bg-zinc-800" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-zinc-100">
                  @{tool.name}
                </span>
                {tool.risk && (
                  <span className="shrink-0 text-[11px] text-zinc-500">
                    {tool.risk}
                  </span>
                )}
              </div>
              {tool.description && (
                <p className="mt-1 text-xs text-zinc-500">
                  {tool.description}
                </p>
              )}
            </button>
            );
          })
        ) : (
          <p className="px-3 py-2 text-xs text-zinc-500">No tools found.</p>
        )}
      </div>
    </div>
  );
}

function normalizeActiveIndex(index: number, length: number) {
  if (length <= 0) return -1;
  return ((index % length) + length) % length;
}

function toolOptionId(name: string) {
  return `tool-option-${name.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}
