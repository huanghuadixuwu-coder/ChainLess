"use client";

import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WorkerRunCard } from "@/components/chat/worker-run-card";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
  StatusLine,
} from "@/components/settings/shared-state";
import { useCapabilityStore } from "@/stores/capability-store";
import type { Worker } from "@/lib/api";

export function WorkersSection() {
  const {
    workers,
    isLoadingWorkers,
    isMutating,
    error,
    notice,
    loadWorkers,
    clearMessages,
  } = useCapabilityStore();

  useEffect(() => {
    void loadWorkers();
  }, [loadWorkers]);

  return (
    <div className="space-y-4">
      <StatusLine error={error} notice={notice} />

      <SettingsCard
        title="Workers"
        description="Manage reusable executable work templates owned by the current user."
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            {workers.length} worker{workers.length === 1 ? "" : "s"}
          </p>
          <Button
            variant="ghost"
            disabled={isLoadingWorkers}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => {
              clearMessages();
              void loadWorkers();
            }}
          >
            Refresh
          </Button>
        </div>

        {workers.length === 0 ? (
          <EmptyState>No Workers configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {workers.map((worker) => (
              <WorkerRow key={worker.id} worker={worker} busy={isMutating} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function WorkerRow({ worker, busy }: { worker: Worker; busy: boolean }) {
  const {
    workerRuns,
    workerVersions,
    enableWorker,
    disableWorker,
    deleteWorker,
    rollbackWorker,
    loadWorkerRuns,
    loadWorkerVersions,
    sendWorkerFeedback,
  } = useCapabilityStore();
  const [rollbackVersionId, setRollbackVersionId] = useState(
    worker.active_version_id || ""
  );
  const [activationToken, setActivationToken] = useState("");
  const [rollbackReason, setRollbackReason] = useState("");

  const runs = workerRuns[worker.id] || [];
  const versions = workerVersions[worker.id] || [];

  const submitRollback = (event: FormEvent) => {
    event.preventDefault();
    const versionId = rollbackVersionId.trim();
    if (!versionId) return;
    void rollbackWorker(worker.id, {
      version_id: versionId,
      activation_token: activationToken.trim() || null,
      reason: rollbackReason.trim() || null,
    });
  };

  return (
    <div
      data-testid="worker-management-card"
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-zinc-100">{worker.name}</p>
            <span className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">
              {worker.status}
            </span>
            <span className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">
              {worker.enabled ? "enabled" : "disabled"}
            </span>
          </div>
          {worker.description && (
            <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-400">
              {worker.description}
            </p>
          )}
          {worker.active_version_id && (
            <p className="mt-2 text-xs text-zinc-500">
              Active version: {worker.active_version_id}
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {worker.enabled ? (
          <Button
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => void disableWorker(worker.id)}
          >
            Disable
          </Button>
        ) : (
          <Button
            disabled={busy}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={() => void enableWorker(worker.id)}
          >
            Enable
          </Button>
        )}
        <Button
          variant="ghost"
          disabled={busy}
          className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          onClick={() => void loadWorkerRuns(worker.id)}
        >
          Load runs
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          onClick={() => void loadWorkerVersions(worker.id)}
        >
          Load versions
        </Button>
        <Button
          variant="destructive"
          disabled={busy}
          onClick={() => void deleteWorker(worker.id)}
        >
          Delete
        </Button>
      </div>

      <form onSubmit={submitRollback} className="mt-4 grid gap-3 md:grid-cols-3">
        <Field label="Rollback version ID">
          <Input
            className={inputClass}
            value={rollbackVersionId}
            onChange={(event) => setRollbackVersionId(event.target.value)}
            placeholder="Worker version UUID"
          />
        </Field>
        <Field label="Activation token">
          <Input
            className={inputClass}
            value={activationToken}
            onChange={(event) => setActivationToken(event.target.value)}
            placeholder="Optional"
          />
        </Field>
        <Field label="Reason">
          <Input
            className={inputClass}
            value={rollbackReason}
            onChange={(event) => setRollbackReason(event.target.value)}
            placeholder="Optional"
          />
        </Field>
        <div className="md:col-span-3">
          <Button
            type="submit"
            disabled={busy || !rollbackVersionId.trim()}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
          >
            Rollback
          </Button>
        </div>
      </form>

      {versions.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-medium text-zinc-400">Versions</p>
          {versions.map((version) => (
            <div
              key={version.id}
              className="rounded-lg border border-zinc-800 bg-zinc-900/80 px-3 py-2 text-xs text-zinc-400"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-zinc-200">
                  v{version.version}
                </span>
                <span>{version.status}</span>
                <span>{version.id}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {runs.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-medium text-zinc-400">Runs</p>
          {runs.map((run) => (
            <WorkerRunCard
              key={run.id}
              run={run}
              busy={busy}
              onFeedback={(workerId, feedback, sourceRunId) =>
                void sendWorkerFeedback(workerId, feedback, { sourceRunId })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
