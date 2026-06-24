"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { AcquisitionHintCard } from "@/components/chat/acquisition-hint-card";
import { useAcquisitionStore } from "@/stores/acquisition-store";
import { useChatStore } from "@/stores/chat-store";
import type {
  AcquisitionGap,
  AcquisitionProposal,
  BrowserSession,
  CredentialConnection,
  RuntimePlanningIssue,
  StandingPermission,
  WorkspaceConnector,
} from "@/lib/api/acquisition";

interface AcquisitionPanelProps {
  conversationId?: string | null;
}

const ACTIVE_GAP_STATUSES = new Set([
  "detected",
  "exploration_recommended",
  "exploration_approved",
  "explored_failed",
  "snoozed",
]);

const oneDayFromNow = () =>
  new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

export function AcquisitionPanel({
  conversationId = null,
}: AcquisitionPanelProps) {
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
    dismissGap,
    snoozeGap,
    approveExploration,
    verifyProposal,
    approveActivation,
    rejectActivation,
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

  const acquisitionNotices = useChatStore((state) =>
    conversationId ? state.acquisitionNotices[conversationId] || [] : []
  );

  useEffect(() => {
    void loadOverview();
    void loadJournal();
  }, [loadOverview, loadJournal]);

  const openGaps = gaps.filter((gap) => ACTIVE_GAP_STATUSES.has(gap.status));
  const actionableProposals = proposals.filter((proposal) =>
    [
      "drafted",
      "verification_requested",
      "verified",
      "activation_requested",
      "activation_approved",
      "activated",
      "partial_activation",
      "activation_failed",
    ].includes(proposal.status)
  );

  return (
    <div data-testid="acquisition-panel" className="space-y-4">
      <div>
        <p className="text-sm font-medium text-zinc-100">
          Capability Acquisition
        </p>
        <p className="mt-1 text-xs text-zinc-500">
          Review gaps, explorations, proposals, permissions, connectors, and
          recovery actions created while the Agent learns new capabilities.
        </p>
      </div>

      {(error || notice) && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-400">
          {error ? `Error: ${error}` : notice}
        </div>
      )}

      {acquisitionNotices.length > 0 && (
        <section className="space-y-2">
          <SectionHeader title="Latest acquisition hints" />
          {acquisitionNotices.slice(0, 3).map((item, index) => (
            <AcquisitionHintCard
              key={`${item.type}-${item.trace_id || item.gap_id || index}`}
              notice={item}
              compact
            />
          ))}
        </section>
      )}

      <section className="space-y-2">
        <SectionHeader
          title="Open gaps"
          trailing={isLoading ? "Loading..." : `${openGaps.length}`}
        />
        {openGaps.length === 0 ? (
          <EmptyState text="No acquisition gaps waiting for review." />
        ) : (
          openGaps.map((gap) => (
            <GapCard
              key={gap.id}
              gap={gap}
              busy={isMutating}
              onApprove={() =>
                void approveExploration(gap.id, {
                  source_run_id: `ui-${gap.id}`,
                  strategy: "manual_research",
                  risk_level: "safe",
                  bounds: {
                    read_only: true,
                    cleanup_supported: true,
                  },
                })
              }
              onDismiss={() => void dismissGap(gap.id, "Dismissed from UI")}
              onSnooze={() => void snoozeGap(gap.id, oneDayFromNow())}
            />
          ))
        )}
      </section>

      <section className="space-y-2">
        <SectionHeader title="Activation proposals" trailing={`${actionableProposals.length}`} />
        {actionableProposals.length === 0 ? (
          <EmptyState text="No acquisition proposals need action." />
        ) : (
          actionableProposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              busy={isMutating}
              onVerify={() =>
                void verifyProposal(proposal.id, {
                  verification_kind: "ui_review",
                  input_fixture: { source: "acquisition_panel" },
                  expected_result: { reviewed: true },
                  actual_result: { reviewed: true },
                  artifact_refs: [],
                })
              }
              onApprove={() =>
                proposal.activation_snapshot_hash
                  ? void approveActivation(proposal.id, {
                      approved_snapshot_hash: proposal.activation_snapshot_hash,
                      reason: "Approved from acquisition panel.",
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
              onReject={() =>
                void rejectActivation(proposal.id, "Rejected from UI")
              }
              onRollback={() =>
                void rollbackProposal(proposal.id, "Rollback from UI")
              }
            />
          ))
        )}
      </section>

      {(permissions.length > 0 ||
        workspaceConnectors.length > 0 ||
        credentialConnections.length > 0 ||
        browserSessions.length > 0 ||
        runtimePlanningIssues.length > 0) && (
        <section className="space-y-2">
          <SectionHeader title="Runtime controls" />
          {permissions.slice(0, 4).map((permission) => (
            <PermissionRow
              key={permission.id}
              permission={permission}
              busy={isMutating}
              onRevoke={() =>
                void revokePermission(permission.id, "Revoked from UI")
              }
              onRenew={() => void renewPermission(permission.id)}
            />
          ))}
          {workspaceConnectors.slice(0, 4).map((connector) => (
            <WorkspaceConnectorRow
              key={connector.id}
              connector={connector}
              busy={isMutating}
              onRevoke={() =>
                void revokeWorkspaceConnector(connector.id, "Revoked from UI")
              }
            />
          ))}
          {credentialConnections.slice(0, 4).map((credential) => (
            <CredentialRow
              key={credential.id}
              credential={credential}
              busy={isMutating}
              onValidate={() => void validateCredentialConnection(credential.id)}
              onRevoke={() =>
                void revokeCredentialConnection(credential.id, "Revoked from UI")
              }
            />
          ))}
          {browserSessions.slice(0, 4).map((session) => (
            <BrowserSessionRow
              key={session.id}
              session={session}
              busy={isMutating}
              onTerminate={() =>
                void terminateBrowserSession(session.id, "Terminated from UI")
              }
            />
          ))}
          {runtimePlanningIssues.slice(0, 4).map((issue) => (
            <PlanningIssueRow
              key={issue.id}
              issue={issue}
              busy={isMutating}
              onDismiss={() =>
                void dismissRuntimePlanningIssue(issue.id, "Dismissed from UI")
              }
            />
          ))}
        </section>
      )}

      {journal?.rendered_markdown && (
        <section className="space-y-2">
          <SectionHeader title="Journal preview" />
          <pre className="max-h-48 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs leading-5 text-zinc-400">
            {journal.rendered_markdown}
          </pre>
        </section>
      )}
    </div>
  );
}

function GapCard({
  gap,
  busy,
  onApprove,
  onDismiss,
  onSnooze,
}: {
  gap: AcquisitionGap;
  busy: boolean;
  onApprove: () => void;
  onDismiss: () => void;
  onSnooze: () => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <CardTitle title={gap.title} tag={gap.status} />
      <div className="mt-2 space-y-1 text-xs text-zinc-400">
        <FactLine label="Problem" value={gap.description} />
        <FactLine label="Cause" value={gap.gap_type} />
        <FactLine label="Risk" value={gap.severity} />
        <FactLine value="Approve safe exploration, snooze it, or dismiss if it is not useful." label="Next step" />
        <FactLine value="Dismissed and snoozed gaps stay out of active review until revisited." label="Recovery" />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="xs"
          disabled={busy}
          className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
          onClick={onApprove}
        >
          Approve exploration
        </Button>
        <Button
          size="xs"
          variant="ghost"
          disabled={busy}
          className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          onClick={onSnooze}
        >
          Snooze
        </Button>
        <Button
          size="xs"
          variant="ghost"
          disabled={busy}
          className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          onClick={onDismiss}
        >
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function ProposalCard({
  proposal,
  busy,
  onVerify,
  onApprove,
  onActivate,
  onReject,
  onRollback,
}: {
  proposal: AcquisitionProposal;
  busy: boolean;
  onVerify: () => void;
  onApprove: () => void;
  onActivate: () => void;
  onReject: () => void;
  onRollback: () => void;
}) {
  const hasSnapshot = Boolean(proposal.activation_snapshot_hash);
  const canRollback = ["activated", "partial_activation", "activation_failed"].includes(
    proposal.status
  );

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <CardTitle title={proposal.title} tag={proposal.status} />
      <div className="mt-2 space-y-1 text-xs text-zinc-400">
        <FactLine label="Problem" value={proposal.user_visible_effect} />
        <FactLine label="Cause" value={proposal.reason} />
        <FactLine label="Risk" value={proposal.risk_level} />
        <FactLine label="Next step" value={proposal.status === "verified" ? "Approve activation with the verified snapshot hash." : "Follow the proposal state machine in order."} />
        <FactLine label="Recovery" value="Rollback is visible after activation or partial activation." />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {["drafted", "verification_requested"].includes(proposal.status) && (
          <Button
            size="xs"
            disabled={busy}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={onVerify}
          >
            Verify
          </Button>
        )}
        {["verified", "activation_requested"].includes(proposal.status) && (
          <Button
            size="xs"
            disabled={busy || !hasSnapshot}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={onApprove}
          >
            Approve activation
          </Button>
        )}
        {proposal.status === "activation_approved" && (
          <Button
            size="xs"
            disabled={busy || !hasSnapshot}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={onActivate}
          >
            Activate
          </Button>
        )}
        {["verified", "activation_requested", "activation_approved"].includes(
          proposal.status
        ) && (
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={onReject}
          >
            Reject
          </Button>
        )}
        {canRollback && (
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={onRollback}
          >
            Rollback
          </Button>
        )}
      </div>
    </div>
  );
}

function PermissionRow({
  permission,
  busy,
  onRevoke,
  onRenew,
}: {
  permission: StandingPermission;
  busy: boolean;
  onRevoke: () => void;
  onRenew: () => void;
}) {
  return (
    <CompactRow
      title={`${permission.target_type} permission`}
      detail={`${permission.status} · ${permission.risk_level}`}
      actionLabel="Revoke permission"
      busy={busy}
      onAction={onRevoke}
      secondaryLabel={permission.status === "revoked" ? "Renew" : undefined}
      onSecondary={permission.status === "revoked" ? onRenew : undefined}
    />
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
    <CompactRow
      title={connector.name}
      detail={`${connector.display_path} · ${connector.mount_health_status}`}
      actionLabel="Revoke connector"
      busy={busy || !connector.enabled}
      onAction={onRevoke}
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
    <CompactRow
      title={credential.name}
      detail={`${credential.provider} · ${credential.status}`}
      actionLabel="Validate"
      busy={busy}
      onAction={onValidate}
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
    <CompactRow
      title={session.name}
      detail={`${session.status} · ${session.runtime_service_name}`}
      actionLabel="Terminate"
      busy={busy || session.status === "terminated"}
      onAction={onTerminate}
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
    <CompactRow
      title={issue.issue_type}
      detail={`${issue.status} · ${issue.missed_signal}`}
      actionLabel="Dismiss"
      busy={busy}
      onAction={onDismiss}
    />
  );
}

function CompactRow({
  title,
  detail,
  actionLabel,
  busy,
  onAction,
  secondaryLabel,
  onSecondary,
}: {
  title: string;
  detail: string;
  actionLabel: string;
  busy: boolean;
  onAction: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium text-zinc-100">{title}</p>
          <p className="mt-1 truncate text-xs text-zinc-500">{detail}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          {secondaryLabel && onSecondary && (
            <Button
              size="xs"
              variant="ghost"
              disabled={busy}
              className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              onClick={onSecondary}
            >
              {secondaryLabel}
            </Button>
          )}
          <Button
            size="xs"
            variant="ghost"
            disabled={busy}
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={onAction}
          >
            {actionLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

function SectionHeader({
  title,
  trailing,
}: {
  title: string;
  trailing?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-xs font-medium text-zinc-400">{title}</p>
      {trailing && <span className="text-xs text-zinc-500">{trailing}</span>}
    </div>
  );
}

function CardTitle({ title, tag }: { title: string; tag: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="truncate font-medium text-zinc-100">{title}</p>
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

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-sm text-zinc-500">
      {text}
    </div>
  );
}
