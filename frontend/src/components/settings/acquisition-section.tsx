"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  SettingsCard,
  StatusLine,
} from "@/components/settings/shared-state";
import { useAcquisitionStore } from "@/stores/acquisition-store";
import type {
  AcquisitionGap,
  AcquisitionProposal,
  BrowserSession,
  CredentialConnection,
  RuntimePlanningIssue,
  WorkspaceConnector,
} from "@/lib/api/acquisition";

const oneDayFromNow = () =>
  new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

export function AcquisitionSection() {
  const {
    gaps,
    proposals,
    runtimePlanningIssues,
    credentialConnections,
    browserSessions,
    permissions,
    workspaceConnectors,
    journal,
    isLoading,
    isMutating,
    error,
    notice,
    loadOverview,
    loadJournal,
    clearMessages,
    dismissGap,
    snoozeGap,
    approveExploration,
    verifyProposal,
    approveActivation,
    activateProposal,
    rollbackProposal,
    dismissRuntimePlanningIssue,
    validateCredentialConnection,
    revokeCredentialConnection,
    terminateBrowserSession,
    revokeWorkspaceConnector,
    revokePermission,
    renewPermission,
  } = useAcquisitionStore();

  useEffect(() => {
    void loadOverview();
    void loadJournal();
  }, [loadOverview, loadJournal]);

  const refresh = () => {
    clearMessages();
    void loadOverview();
    void loadJournal();
  };

  return (
    <div data-testid="settings-acquisition-section" className="space-y-4">
      <StatusLine error={error} notice={notice} />

      <SettingsCard
        title="Capability Acquisition"
        description="Review V3 capability gaps, explorations, activation proposals, connectors, permissions, and recovery state."
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            {gaps.length} gaps · {proposals.length} proposals ·{" "}
            {permissions.length} permissions
          </p>
          <Button
            variant="ghost"
            disabled={isLoading}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={refresh}
          >
            Refresh
          </Button>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <SummaryTile label="Open gaps" value={gaps.length} />
          <SummaryTile label="Workspace connectors" value={workspaceConnectors.length} />
          <SummaryTile label="Browser sessions" value={browserSessions.length} />
        </div>
      </SettingsCard>

      <SettingsCard
        title="Gaps"
        description="Problem, cause, risk, next step, and recovery are kept visible before exploration."
      >
        {gaps.length === 0 ? (
          <EmptyState>No capability gaps recorded.</EmptyState>
        ) : (
          <div className="space-y-3">
            {gaps.map((gap) => (
              <GapRow
                key={gap.id}
                gap={gap}
                busy={isMutating}
                onApprove={() =>
                  void approveExploration(gap.id, {
                    source_run_id: `settings-${gap.id}`,
                    strategy: "manual_research",
                    risk_level: "safe",
                    bounds: { read_only: true, cleanup_supported: true },
                  })
                }
                onSnooze={() => void snoozeGap(gap.id, oneDayFromNow())}
                onDismiss={() => void dismissGap(gap.id, "Dismissed from Settings")}
              />
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard
        title="Activation proposals"
        description="Verification and activation approval stay separate; rollback remains visible after activation."
      >
        {proposals.length === 0 ? (
          <EmptyState>No acquisition proposals recorded.</EmptyState>
        ) : (
          <div className="space-y-3">
            {proposals.map((proposal) => (
              <ProposalRow
                key={proposal.id}
                proposal={proposal}
                busy={isMutating}
                onVerify={() =>
                  void verifyProposal(proposal.id, {
                    verification_kind: "settings_review",
                    input_fixture: { source: "settings_acquisition" },
                    expected_result: { reviewed: true },
                    actual_result: { reviewed: true },
                    artifact_refs: [],
                  })
                }
                onApprove={() =>
                  proposal.activation_snapshot_hash
                    ? void approveActivation(proposal.id, {
                        approved_snapshot_hash:
                          proposal.activation_snapshot_hash,
                        reason: "Approved from Settings.",
                      })
                    : undefined
                }
                onActivate={() =>
                  proposal.activation_snapshot_hash
                    ? void activateProposal(
                        proposal.id,
                        proposal.activation_snapshot_hash
                      )
                    : undefined
                }
                onRollback={() =>
                  void rollbackProposal(proposal.id, "Rollback from Settings")
                }
              />
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Runtime controls">
        {permissions.length === 0 &&
        workspaceConnectors.length === 0 &&
        credentialConnections.length === 0 &&
        browserSessions.length === 0 &&
        runtimePlanningIssues.length === 0 ? (
          <EmptyState>No active runtime acquisition controls.</EmptyState>
        ) : (
          <div className="space-y-3">
            {permissions.map((permission) => (
              <ControlRow
                key={permission.id}
                title={`${permission.target_type} permission`}
                detail={`${permission.status} · ${permission.risk_level}`}
                busy={isMutating}
                primaryLabel="Revoke permission"
                onPrimary={() =>
                  void revokePermission(permission.id, "Revoked from Settings")
                }
                secondaryLabel={permission.status === "revoked" ? "Renew" : undefined}
                onSecondary={
                  permission.status === "revoked"
                    ? () => void renewPermission(permission.id)
                    : undefined
                }
              />
            ))}
            {workspaceConnectors.map((connector) => (
              <WorkspaceConnectorRow
                key={connector.id}
                connector={connector}
                busy={isMutating}
                onRevoke={() =>
                  void revokeWorkspaceConnector(
                    connector.id,
                    "Revoked from Settings"
                  )
                }
              />
            ))}
            {credentialConnections.map((credential) => (
              <CredentialRow
                key={credential.id}
                credential={credential}
                busy={isMutating}
                onValidate={() =>
                  void validateCredentialConnection(credential.id)
                }
                onRevoke={() =>
                  void revokeCredentialConnection(
                    credential.id,
                    "Revoked from Settings"
                  )
                }
              />
            ))}
            {browserSessions.map((session) => (
              <BrowserSessionRow
                key={session.id}
                session={session}
                busy={isMutating}
                onTerminate={() =>
                  void terminateBrowserSession(
                    session.id,
                    "Terminated from Settings"
                  )
                }
              />
            ))}
            {runtimePlanningIssues.map((issue) => (
              <PlanningIssueRow
                key={issue.id}
                issue={issue}
                busy={isMutating}
                onDismiss={() =>
                  void dismissRuntimePlanningIssue(
                    issue.id,
                    "Dismissed from Settings"
                  )
                }
              />
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard
        title="ACQUISITION.md"
        description="Read-only private acquisition journal generated from UI/API/audit paths."
      >
        {journal?.rendered_markdown ? (
          <pre className="max-h-80 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs leading-5 text-zinc-400">
            {journal.rendered_markdown}
          </pre>
        ) : (
          <EmptyState>No acquisition journal content yet.</EmptyState>
        )}
      </SettingsCard>
    </div>
  );
}

function GapRow({
  gap,
  busy,
  onApprove,
  onSnooze,
  onDismiss,
}: {
  gap: AcquisitionGap;
  busy: boolean;
  onApprove: () => void;
  onSnooze: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <RowTitle title={gap.title} tag={gap.status} />
      <div className="mt-2 space-y-1 text-sm text-zinc-400">
        <FactLine label="Problem" value={gap.description} />
        <FactLine label="Cause" value={gap.gap_type} />
        <FactLine label="Risk" value={gap.severity} />
        <FactLine label="Next step" value="Approve exploration, snooze, or dismiss." />
        <FactLine label="Recovery" value="Snoozed or dismissed gaps can be revisited from the audit trail." />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton disabled={busy} onClick={onApprove}>
          Approve exploration
        </ActionButton>
        <GhostButton disabled={busy} onClick={onSnooze}>
          Snooze
        </GhostButton>
        <GhostButton disabled={busy} onClick={onDismiss}>
          Dismiss
        </GhostButton>
      </div>
    </div>
  );
}

function ProposalRow({
  proposal,
  busy,
  onVerify,
  onApprove,
  onActivate,
  onRollback,
}: {
  proposal: AcquisitionProposal;
  busy: boolean;
  onVerify: () => void;
  onApprove: () => void;
  onActivate: () => void;
  onRollback: () => void;
}) {
  const hasSnapshot = Boolean(proposal.activation_snapshot_hash);
  const canRollback = ["activated", "partial_activation", "activation_failed"].includes(
    proposal.status
  );

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <RowTitle title={proposal.title} tag={proposal.status} />
      <div className="mt-2 space-y-1 text-sm text-zinc-400">
        <FactLine label="Problem" value={proposal.user_visible_effect} />
        <FactLine label="Cause" value={proposal.reason} />
        <FactLine label="Risk" value={proposal.risk_level} />
        <FactLine label="Next step" value="Verify before approval; approve before activation." />
        <FactLine label="Recovery" value="Rollback is available after activation or partial activation." />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {["drafted", "verification_requested"].includes(proposal.status) && (
          <ActionButton disabled={busy} onClick={onVerify}>
            Verify
          </ActionButton>
        )}
        {["verified", "activation_requested"].includes(proposal.status) && (
          <ActionButton disabled={busy || !hasSnapshot} onClick={onApprove}>
            Approve activation
          </ActionButton>
        )}
        {proposal.status === "activation_approved" && (
          <ActionButton disabled={busy || !hasSnapshot} onClick={onActivate}>
            Activate
          </ActionButton>
        )}
        {canRollback && (
          <GhostButton disabled={busy} onClick={onRollback}>
            Rollback
          </GhostButton>
        )}
      </div>
    </div>
  );
}

function WorkspaceConnectorRow({
  connector,
  busy,
  onRevoke,
}: {
  connector: WorkspaceConnector;
  busy: boolean;
  onRevoke: () => void;
}) {
  return (
    <ControlRow
      title={connector.name}
      detail={`${connector.display_path} · ${connector.mount_health_status}`}
      busy={busy || !connector.enabled}
      primaryLabel="Revoke connector"
      onPrimary={onRevoke}
    />
  );
}

function CredentialRow({
  credential,
  busy,
  onValidate,
  onRevoke,
}: {
  credential: CredentialConnection;
  busy: boolean;
  onValidate: () => void;
  onRevoke: () => void;
}) {
  return (
    <ControlRow
      title={credential.name}
      detail={`${credential.provider} · ${credential.status}`}
      busy={busy}
      primaryLabel="Validate"
      onPrimary={onValidate}
      secondaryLabel="Revoke"
      onSecondary={onRevoke}
    />
  );
}

function BrowserSessionRow({
  session,
  busy,
  onTerminate,
}: {
  session: BrowserSession;
  busy: boolean;
  onTerminate: () => void;
}) {
  return (
    <ControlRow
      title={session.name}
      detail={`${session.status} · ${session.runtime_service_name}`}
      busy={busy || session.status === "terminated"}
      primaryLabel="Terminate"
      onPrimary={onTerminate}
    />
  );
}

function PlanningIssueRow({
  issue,
  busy,
  onDismiss,
}: {
  issue: RuntimePlanningIssue;
  busy: boolean;
  onDismiss: () => void;
}) {
  return (
    <ControlRow
      title={issue.issue_type}
      detail={`${issue.status} · ${issue.missed_signal}`}
      busy={busy}
      primaryLabel="Dismiss"
      onPrimary={onDismiss}
    />
  );
}

function ControlRow({
  title,
  detail,
  busy,
  primaryLabel,
  onPrimary,
  secondaryLabel,
  onSecondary,
}: {
  title: string;
  detail: string;
  busy: boolean;
  primaryLabel: string;
  onPrimary: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-zinc-100">{title}</p>
        <p className="mt-1 truncate text-xs text-zinc-500">{detail}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        {secondaryLabel && onSecondary && (
          <GhostButton disabled={busy} onClick={onSecondary}>
            {secondaryLabel}
          </GhostButton>
        )}
        <GhostButton disabled={busy} onClick={onPrimary}>
          {primaryLabel}
        </GhostButton>
      </div>
    </div>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function RowTitle({ title, tag }: { title: string; tag: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="truncate text-sm font-medium text-zinc-100">{title}</p>
      <span className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">
        {tag}
      </span>
    </div>
  );
}

function FactLine({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <span className="text-zinc-500">{label}: </span>
      <span className="text-zinc-300">{value}</span>
    </p>
  );
}

function ActionButton({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      size="sm"
      disabled={disabled}
      className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function GhostButton({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button
      size="sm"
      variant="ghost"
      disabled={disabled}
      className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
