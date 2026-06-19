"use client";

import { Button } from "@/components/ui/button";
import type {
  CapabilityCandidate,
  CapabilityCandidateHint,
} from "@/lib/api";

type CandidateLike = CapabilityCandidate | CapabilityCandidateHint;

interface CapabilityHintCardProps {
  candidate: CandidateLike;
  compact?: boolean;
  busy?: boolean;
  onAccept?: (candidateId: string) => void;
  onDismiss?: (candidateId: string) => void;
  onSnooze?: (candidateId: string) => void;
  onArchive?: (candidateId: string) => void;
  onMutePattern?: (candidateId: string, pattern: string) => void;
}

export function CapabilityHintCard({
  candidate,
  compact = false,
  busy = false,
  onAccept,
  onDismiss,
  onSnooze,
  onArchive,
  onMutePattern,
}: CapabilityHintCardProps) {
  const status = candidate.status || "new";
  const canAct = ["new", "seen", "snoozed"].includes(status);
  const detail = "body" in candidate ? candidate.body : candidate.message;
  const mutePattern =
    "dedupe_key" in candidate && candidate.dedupe_key
      ? candidate.dedupe_key
      : `${candidate.candidate_type}:${candidate.title}`;

  return (
    <div
      data-testid="capability-hint-card"
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-zinc-100">
              {candidate.title}
            </p>
            <span className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">
              {candidate.candidate_type}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">{status}</p>
        </div>
      </div>

      {detail && (
        <p
          className={`mt-2 whitespace-pre-wrap text-zinc-400 ${
            compact ? "line-clamp-3" : ""
          }`}
        >
          {detail}
        </p>
      )}

      {canAct && (
        <div className="mt-3 flex flex-wrap gap-2">
          {onAccept && (
            <Button
              size="xs"
              disabled={busy}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
              onClick={() => onAccept(candidate.id)}
            >
              Accept
            </Button>
          )}
          {onDismiss && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={() => onDismiss(candidate.id)}
            >
              Dismiss
            </Button>
          )}
          {onSnooze && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={() => onSnooze(candidate.id)}
            >
              Snooze
            </Button>
          )}
          {onArchive && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={() => onArchive(candidate.id)}
            >
              Archive
            </Button>
          )}
          {onMutePattern && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={() => onMutePattern(candidate.id, mutePattern)}
            >
              Mute pattern
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
