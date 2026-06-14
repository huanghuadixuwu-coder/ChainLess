"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { usePlatformStore } from "@/stores/platform-store";
import { EmptyState, SettingsCard } from "@/components/settings/shared-state";

const metricLines = (metrics: string) =>
  metrics
    .split("\n")
    .filter((line) => line && !line.startsWith("#"))
    .slice(0, 12);

const subscribeMounted = () => () => {};
const getClientMounted = () => true;
const getServerMounted = () => false;

export function SystemSection() {
  const { systemHealth, systemMetrics, refreshSystem, isMutating } =
    usePlatformStore();
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(
    subscribeMounted,
    getClientMounted,
    getServerMounted,
  );

  const isDark = !mounted || resolvedTheme !== "light";

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Appearance"
        description="Dark mode remains the default; the toggle only changes the local browser preference."
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-zinc-100">
              Theme: {isDark ? "Dark" : "Light"}
            </div>
            <div className="text-xs text-zinc-500">
              Stored locally for this browser.
            </div>
          </div>
          <Button
            type="button"
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={() => setTheme(isDark ? "light" : "dark")}
          >
            Switch to {isDark ? "Light" : "Dark"}
          </Button>
        </div>
      </SettingsCard>

      <SettingsCard
        title="System health"
        description="Operational health summary from the backend system endpoints."
      >
        <div className="mb-3 flex justify-end">
          <Button
            disabled={isMutating}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={() => void refreshSystem()}
          >
            Refresh
          </Button>
        </div>
        {!systemHealth ? (
          <EmptyState>No system health loaded.</EmptyState>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <HealthItem label="Overall" value={systemHealth.status} />
            <HealthItem label="Database" value={systemHealth.db} />
            <HealthItem label="Redis" value={systemHealth.redis} />
            <HealthItem label="Worker" value={systemHealth.worker} />
            <HealthItem
              label="Sandbox pool"
              value={String(systemHealth.sandbox_pool)}
            />
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Metrics summary">
        {metricLines(systemMetrics).length === 0 ? (
          <EmptyState>No metrics loaded.</EmptyState>
        ) : (
          <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-xs text-zinc-300">
            {metricLines(systemMetrics).map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function HealthItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-sm font-medium text-zinc-100">{value}</div>
    </div>
  );
}
