"use client";

import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CapabilityHintCard } from "@/components/chat/capability-hint-card";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
  StatusLine,
} from "@/components/settings/shared-state";
import { useCapabilityStore } from "@/stores/capability-store";
import type { CapabilityCandidate } from "@/lib/api";

const ACTIVE_STATUSES = ["new", "seen", "snoozed"];

const oneDayFromNow = () =>
  new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

export function CapabilitiesSection() {
  const {
    candidatesByStatus,
    isLoadingCandidates,
    isMutating,
    error,
    notice,
    loadCandidates,
    clearMessages,
  } = useCapabilityStore();

  useEffect(() => {
    void loadCandidates();
  }, [loadCandidates]);

  const allCandidates = Object.values(candidatesByStatus).flat();
  const activeCandidates = ACTIVE_STATUSES.flatMap(
    (status) => candidatesByStatus[status] || []
  );
  const processedCandidates = allCandidates.filter(
    (candidate) => !ACTIVE_STATUSES.includes(candidate.status)
  );

  return (
    <div className="space-y-4">
      <StatusLine error={error} notice={notice} />

      <SettingsCard
        title="Capability Inbox"
        description="Review durable Memory, Skill, and Worker candidates suggested by completed work."
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            {activeCandidates.length} open candidate
            {activeCandidates.length === 1 ? "" : "s"}
          </p>
          <Button
            variant="ghost"
            disabled={isLoadingCandidates}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => {
              clearMessages();
              void loadCandidates();
            }}
          >
            Refresh
          </Button>
        </div>

        {activeCandidates.length === 0 ? (
          <EmptyState>No open candidates waiting for review.</EmptyState>
        ) : (
          <div className="space-y-3">
            {activeCandidates.map((candidate) => (
              <CandidateRow
                key={candidate.id}
                candidate={candidate}
                busy={isMutating}
              />
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Processed candidates">
        {processedCandidates.length === 0 ? (
          <EmptyState>No processed candidates to show.</EmptyState>
        ) : (
          <div className="space-y-3">
            {processedCandidates.map((candidate) => (
              <CapabilityHintCard
                key={candidate.id}
                candidate={candidate}
                compact
                busy={isMutating}
              />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function CandidateRow({
  candidate,
  busy,
}: {
  candidate: CapabilityCandidate;
  busy: boolean;
}) {
  const {
    acceptCandidate,
    dismissCandidate,
    archiveCandidate,
    snoozeCandidate,
    muteCandidatePattern,
    mergeCandidate,
  } = useCapabilityStore();
  const [targetCandidateId, setTargetCandidateId] = useState("");
  const [mergeReason, setMergeReason] = useState("");
  const [mutePattern, setMutePattern] = useState(
    candidate.dedupe_key || `${candidate.candidate_type}:${candidate.title}`
  );

  const submitMerge = (event: FormEvent) => {
    event.preventDefault();
    if (!targetCandidateId.trim()) return;
    void mergeCandidate(
      candidate.id,
      targetCandidateId.trim(),
      mergeReason.trim() || undefined
    );
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <CapabilityHintCard
        candidate={candidate}
        compact
        busy={busy}
        onAccept={(id) => void acceptCandidate(id)}
        onDismiss={(id) => void dismissCandidate(id)}
        onSnooze={(id) => void snoozeCandidate(id, oneDayFromNow())}
        onArchive={(id) => void archiveCandidate(id)}
      />

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="Mute pattern">
          <div className="flex gap-2">
            <Input
              className={inputClass}
              value={mutePattern}
              onChange={(event) => setMutePattern(event.target.value)}
            />
            <Button
              disabled={busy || !mutePattern.trim()}
              variant="ghost"
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={() =>
                void muteCandidatePattern(candidate.id, mutePattern.trim())
              }
            >
              Mute
            </Button>
          </div>
        </Field>

        <form onSubmit={submitMerge} className="space-y-2">
          <Field label="Merge into candidate ID">
            <Input
              className={inputClass}
              value={targetCandidateId}
              onChange={(event) => setTargetCandidateId(event.target.value)}
              placeholder="Target candidate UUID"
            />
          </Field>
          <Field label="Merge reason">
            <Input
              className={inputClass}
              value={mergeReason}
              onChange={(event) => setMergeReason(event.target.value)}
              placeholder="Optional"
            />
          </Field>
          <Button
            type="submit"
            disabled={busy || !targetCandidateId.trim()}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
          >
            Merge
          </Button>
        </form>
      </div>
    </div>
  );
}
