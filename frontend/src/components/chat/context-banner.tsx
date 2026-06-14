"use client";

import type { StreamContext } from "@/lib/api";

export function ContextBanner({
  summary,
}: {
  summary: StreamContext | null | undefined;
}) {
  if (!summary) {
    return null;
  }

  const agentName = summary.agent?.name || "Default agent";
  const provider = summary.agent?.provider || "default";
  const memoryCount = summary.memory_count || 0;
  const memoryNames = (summary.memory_names || []).filter(Boolean);

  return (
    <div
      data-testid="context-banner"
      className="rounded-lg border border-zinc-800 bg-zinc-900/80 px-3 py-2 text-xs text-zinc-400"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-zinc-200">Context loaded</span>
        <span className="rounded border border-zinc-700 px-2 py-0.5">
          Agent: {agentName}
        </span>
        <span className="rounded border border-zinc-700 px-2 py-0.5">
          Provider: {provider}
        </span>
        <span className="rounded border border-zinc-700 px-2 py-0.5">
          Memories: {memoryCount}
        </span>
        {summary.has_layered_instructions && (
          <span className="rounded border border-zinc-700 px-2 py-0.5">
            Layered instructions
          </span>
        )}
      </div>
      {(memoryNames.length > 0 || summary.instruction_preview) && (
        <div className="mt-1 overflow-hidden text-ellipsis whitespace-nowrap text-zinc-500">
          {memoryNames.length > 0 && (
            <span>Memory: {memoryNames.slice(0, 3).join(", ")}</span>
          )}
          {memoryNames.length > 0 && summary.instruction_preview && (
            <span> | </span>
          )}
          {summary.instruction_preview && (
            <span>Instructions: {summary.instruction_preview}</span>
          )}
        </div>
      )}
    </div>
  );
}
