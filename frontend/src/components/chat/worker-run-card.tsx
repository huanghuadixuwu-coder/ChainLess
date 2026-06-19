"use client";

import { Button } from "@/components/ui/button";
import type { WorkerNotice, WorkerRun } from "@/lib/api";

interface WorkerRunCardProps {
  notice?: WorkerNotice;
  run?: WorkerRun;
  busy?: boolean;
  onFeedback?: (
    workerId: string,
    feedback: string,
    sourceRunId?: string | null
  ) => void;
}

export function WorkerRunCard({
  notice,
  run,
  busy = false,
  onFeedback,
}: WorkerRunCardProps) {
  const workerId = notice?.worker_id || run?.worker_id || "";
  const sourceRunId = run?.source_run_id || notice?.worker_run_id || null;
  const status = notice?.status || run?.status || "unknown";
  const title = notice?.worker_name || "Worker";
  const detail =
    notice?.message ||
    run?.error_message ||
    (run ? "Worker run recorded." : "Worker event recorded.");
  const reason = notice?.reason || run?.error_code || "";

  return (
    <div
      data-testid="worker-run-card"
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium text-zinc-100">{title}</p>
          <p className="mt-1 text-xs text-zinc-500">{status}</p>
        </div>
        {notice?.score !== undefined && (
          <span className="text-xs text-zinc-500">
            {Math.round(notice.score * 100)}%
          </span>
        )}
      </div>

      <p className="mt-2 whitespace-pre-wrap text-zinc-400">{detail}</p>

      {reason && <p className="mt-2 text-xs text-zinc-500">{reason}</p>}

      {notice?.reasons && notice.reasons.length > 0 && (
        <p className="mt-2 text-xs text-zinc-500">
          {notice.reasons.slice(0, 3).join(", ")}
        </p>
      )}

      {onFeedback && workerId && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => onFeedback(workerId, "useful", sourceRunId)}
          >
            Useful
          </Button>
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => onFeedback(workerId, "not_useful", sourceRunId)}
          >
            Not useful
          </Button>
        </div>
      )}
    </div>
  );
}
