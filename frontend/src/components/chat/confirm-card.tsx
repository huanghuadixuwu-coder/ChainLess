"use client";

import { Button } from "@/components/ui/button";
import { PendingConfirmation } from "@/stores/chat-store";

interface ConfirmCardProps {
  confirmation: PendingConfirmation;
  busy?: boolean;
  onApprove: () => void;
  onDeny: () => void;
}

export function ConfirmCard({
  confirmation,
  busy = false,
  onApprove,
  onDeny,
}: ConfirmCardProps) {
  return (
    <div className="rounded-lg border border-amber-800 bg-amber-950/40 px-4 py-3 text-amber-50">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Confirmation required</p>
          <p className="mt-1 text-xs text-amber-200/80">
            `{confirmation.tool_name}` is marked as {confirmation.risk}. Review
            the request and approve or deny.
          </p>
        </div>
        <span className="rounded border border-amber-800 px-2 py-1 text-[11px] uppercase tracking-wide text-amber-200">
          {confirmation.timeout_s}s
        </span>
      </div>

      <pre className="mt-3 overflow-x-auto rounded-md bg-zinc-950/80 px-3 py-2 text-xs text-zinc-300">
        {JSON.stringify(confirmation.args, null, 2)}
      </pre>

      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          onClick={onApprove}
          disabled={busy}
          className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
        >
          Approve
        </Button>
        <Button
          type="button"
          onClick={onDeny}
          disabled={busy}
          variant="outline"
          className="border-zinc-700 bg-transparent text-zinc-200 hover:bg-zinc-800"
        >
          Deny
        </Button>
      </div>
    </div>
  );
}
