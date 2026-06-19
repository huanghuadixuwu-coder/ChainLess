"use client";

import { useEffect } from "react";
import { CapabilityHintCard } from "@/components/chat/capability-hint-card";
import { WorkerRunCard } from "@/components/chat/worker-run-card";
import { useCapabilityStore } from "@/stores/capability-store";

interface CapabilityInboxPanelProps {
  conversationId?: string | null;
}

const INBOX_STATUSES = ["new", "seen", "snoozed"];

const oneDayFromNow = () =>
  new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

export function CapabilityInboxPanel({
  conversationId = null,
}: CapabilityInboxPanelProps) {
  const {
    candidatesByStatus,
    candidateHintsByConversation,
    workerNoticesByConversation,
    isLoadingCandidates,
    isMutating,
    error,
    notice,
    loadCandidates,
    acceptCandidate,
    dismissCandidate,
    archiveCandidate,
    snoozeCandidate,
    muteCandidatePattern,
    sendWorkerFeedback,
  } = useCapabilityStore();

  useEffect(() => {
    void loadCandidates();
  }, [loadCandidates]);

  const candidates = INBOX_STATUSES.flatMap(
    (status) => candidatesByStatus[status] || []
  );
  const hints = conversationId
    ? candidateHintsByConversation[conversationId] || []
    : [];
  const workerNotices = conversationId
    ? workerNoticesByConversation[conversationId] || []
    : [];

  return (
    <div data-testid="capability-inbox-panel" className="space-y-4">
      <div>
        <p className="text-sm font-medium text-zinc-100">Capability Inbox</p>
        <p className="mt-1 text-xs text-zinc-500">
          Review memories, skills, and workers suggested from completed work.
        </p>
      </div>

      {(error || notice) && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-400">
          {error ? `Error: ${error}` : notice}
        </div>
      )}

      {workerNotices.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs font-medium text-zinc-400">Worker activity</p>
          {workerNotices.map((item, index) => (
            <WorkerRunCard
              key={`${item.worker_run_id || item.worker_id || index}-${index}`}
              notice={item}
              busy={isMutating}
              onFeedback={(workerId, feedback, sourceRunId) =>
                void sendWorkerFeedback(workerId, feedback, { sourceRunId })
              }
            />
          ))}
        </section>
      )}

      {hints.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs font-medium text-zinc-400">Latest hints</p>
          {hints.map((candidate) => (
            <CapabilityHintCard
              key={candidate.id}
              candidate={candidate}
              compact
              busy={isMutating}
              onAccept={(id) => void acceptCandidate(id)}
              onDismiss={(id) => void dismissCandidate(id)}
              onSnooze={(id) => void snoozeCandidate(id, oneDayFromNow())}
              onArchive={(id) => void archiveCandidate(id)}
              onMutePattern={(id, pattern) =>
                void muteCandidatePattern(id, pattern)
              }
            />
          ))}
        </section>
      )}

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-medium text-zinc-400">Open candidates</p>
          {isLoadingCandidates && (
            <span className="text-xs text-zinc-500">Loading...</span>
          )}
        </div>

        {candidates.length === 0 ? (
          <EmptyState text="No capability candidates waiting for review." />
        ) : (
          candidates.map((candidate) => (
            <CapabilityHintCard
              key={candidate.id}
              candidate={candidate}
              compact
              busy={isMutating}
              onAccept={(id) => void acceptCandidate(id)}
              onDismiss={(id) => void dismissCandidate(id)}
              onSnooze={(id) => void snoozeCandidate(id, oneDayFromNow())}
              onArchive={(id) => void archiveCandidate(id)}
              onMutePattern={(id, pattern) =>
                void muteCandidatePattern(id, pattern)
              }
            />
          ))
        )}
      </section>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-sm text-zinc-500">
      {text}
    </div>
  );
}
