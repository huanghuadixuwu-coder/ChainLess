"use client";

import { ToolEvent } from "@/stores/chat-store";

interface ToolActivityRowProps {
  event: ToolEvent;
}

const STATUS_LABEL: Record<ToolEvent["status"], string> = {
  running: "Running",
  completed: "Completed",
  error: "Error",
  needs_confirmation: "Needs confirmation",
  denied: "Denied",
};

export function ToolActivityRow({ event }: ToolActivityRowProps) {
  const detail = event.result || event.error || "";

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/80 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-200">
            {event.name}
          </p>
          <p className="text-xs text-zinc-500">
            {event.risk
              ? `${STATUS_LABEL[event.status]} / ${event.risk}`
              : STATUS_LABEL[event.status]}
          </p>
        </div>
      </div>

      {Object.keys(event.args || {}).length > 0 && (
        <pre className="mt-3 overflow-x-auto rounded-md bg-zinc-950 px-3 py-2 text-xs text-zinc-400">
          {JSON.stringify(event.args, null, 2)}
        </pre>
      )}

      {event.artifacts && event.artifacts.length > 0 && (
        <p className="mt-3 text-xs text-zinc-500">
          {event.artifacts.length} file artifact
          {event.artifacts.length === 1 ? "" : "s"} available in Files/Diff.
        </p>
      )}

      {detail && (
        <pre
          className={`mt-3 overflow-x-auto rounded-md px-3 py-2 text-xs ${
            event.status === "error" || event.status === "denied"
              ? "bg-red-950/40 text-red-200"
              : "bg-zinc-950 text-zinc-300"
          }`}
        >
          {detail}
        </pre>
      )}
    </div>
  );
}
