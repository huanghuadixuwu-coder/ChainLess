"use client";

import { Button } from "@/components/ui/button";
import { usePlatformStore } from "@/stores/platform-store";
import { EmptyState, SettingsCard } from "@/components/settings/shared-state";

export function EvalSection() {
  const { evalSuites, evalStatuses, lastEvalRun, runEvalSuite, isMutating } =
    usePlatformStore();

  const statusBySuite = new Map(
    evalStatuses.map((status) => [status.suite, status])
  );

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Eval suites"
        description="List suites and run the backend dry-run validation contract."
      >
        {evalSuites.length === 0 ? (
          <EmptyState>No eval suites found.</EmptyState>
        ) : (
          <div className="space-y-3">
            {evalSuites.map((suite) => {
              const status = statusBySuite.get(suite.name);
              return (
                <div
                  key={suite.name}
                  className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-zinc-100">
                        {suite.name}
                      </div>
                      <div className="text-sm text-zinc-400">
                        {suite.task_count} task(s), status{" "}
                        {status?.status || "unknown"}
                      </div>
                    </div>
                    <Button
                      disabled={isMutating}
                      className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
                      onClick={() => void runEvalSuite(suite.name)}
                    >
                      Dry-run
                    </Button>
                  </div>
                  {status?.updated_at && (
                    <div className="mt-2 text-xs text-zinc-500">
                      Updated {status.updated_at}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Last dry-run result">
        {!lastEvalRun ? (
          <EmptyState>No dry-run result yet.</EmptyState>
        ) : (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-300">
            <div>Suite: {lastEvalRun.suite}</div>
            <div>Status: {lastEvalRun.status}</div>
            <div>Executed: {lastEvalRun.executed ? "yes" : "no"}</div>
            <div className="text-zinc-400">{lastEvalRun.message}</div>
          </div>
        )}
      </SettingsCard>
    </div>
  );
}
