import { create } from "zustand";
import { acquisitionApi } from "@/lib/api/acquisition";
import type {
  AcquisitionExploration,
  AcquisitionGap,
  AcquisitionJournal,
  AcquisitionProposal,
  AcquisitionRecommendation,
  ApproveActivationBody,
  ApproveExplorationBody,
  BrowserSession,
  CredentialConnection,
  CreateCredentialBody,
  RuntimePlanningIssue,
  StandingPermission,
  VerifyProposalBody,
  WorkspaceConnector,
} from "@/lib/api/acquisition";

interface AcquisitionState {
  gaps: AcquisitionGap[];
  explorations: AcquisitionExploration[];
  recommendations: AcquisitionRecommendation[];
  proposals: AcquisitionProposal[];
  runtimePlanningIssues: RuntimePlanningIssue[];
  credentialConnections: CredentialConnection[];
  browserSessions: BrowserSession[];
  permissions: StandingPermission[];
  workspaceConnectors: WorkspaceConnector[];
  journal: AcquisitionJournal | null;
  isLoading: boolean;
  isMutating: boolean;
  error: string | null;
  notice: string | null;

  loadOverview: () => Promise<void>;
  loadJournal: () => Promise<void>;
  dismissGap: (gapId: string, reason?: string | null) => Promise<void>;
  snoozeGap: (gapId: string, snoozedUntil: string) => Promise<void>;
  approveExploration: (gapId: string, body: ApproveExplorationBody) => Promise<void>;
  verifyProposal: (proposalId: string, body: VerifyProposalBody) => Promise<void>;
  approveActivation: (proposalId: string, body: ApproveActivationBody) => Promise<void>;
  rejectActivation: (proposalId: string, reason?: string | null) => Promise<void>;
  activateProposal: (proposalId: string, approvedSnapshotHash: string, verificationId?: string | null) => Promise<void>;
  rollbackProposal: (proposalId: string, reason?: string | null) => Promise<void>;
  dismissRuntimePlanningIssue: (issueId: string, reason?: string | null) => Promise<void>;
  createCredentialConnection: (body: CreateCredentialBody) => Promise<void>;
  validateCredentialConnection: (credentialId: string) => Promise<void>;
  rotateCredentialConnection: (
    credentialId: string,
    body: Parameters<typeof acquisitionApi.rotateCredentialConnection>[1]
  ) => Promise<void>;
  revokeCredentialConnection: (credentialId: string, reason?: string | null) => Promise<void>;
  terminateBrowserSession: (sessionId: string, reason?: string | null) => Promise<void>;
  revokeWorkspaceConnector: (connectorId: string, reason?: string | null) => Promise<void>;
  revokePermission: (permissionId: string, reason?: string | null) => Promise<void>;
  renewPermission: (permissionId: string) => Promise<void>;
  clearMessages: () => void;
}

const upsertByUpdatedAt = <T extends { id: string; created_at?: string; updated_at?: string }>(
  items: T[],
  item: T
) =>
  [item, ...items.filter((current) => current.id !== item.id)].sort((a, b) =>
    String(b.updated_at || b.created_at || "").localeCompare(
      String(a.updated_at || a.created_at || "")
    )
  );

const actionError = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

export const useAcquisitionStore = create<AcquisitionState>((set, get) => ({
  gaps: [],
  explorations: [],
  recommendations: [],
  proposals: [],
  runtimePlanningIssues: [],
  credentialConnections: [],
  browserSessions: [],
  permissions: [],
  workspaceConnectors: [],
  journal: null,
  isLoading: false,
  isMutating: false,
  error: null,
  notice: null,

  loadOverview: async () => {
    set({ isLoading: true, error: null });
    try {
      const [
        gaps,
        explorations,
        recommendations,
        proposals,
        runtimePlanningIssues,
        credentialConnections,
        browserSessions,
        permissions,
        workspaceConnectors,
      ] = await Promise.all([
        acquisitionApi.listGaps({ limit: 100 }),
        acquisitionApi.listExplorations({ limit: 100 }),
        acquisitionApi.listRecommendations({ limit: 100 }),
        acquisitionApi.listProposals({ limit: 100 }),
        acquisitionApi.listRuntimePlanningIssues({ limit: 100 }),
        acquisitionApi.listCredentialConnections({ limit: 100 }),
        acquisitionApi.listBrowserSessions({ limit: 100 }),
        acquisitionApi.listPermissions({ limit: 100 }),
        acquisitionApi.listWorkspaceConnectors({ limit: 100 }),
      ]);
      set({
        gaps: gaps.items || [],
        explorations: explorations.items || [],
        recommendations: recommendations.items || [],
        proposals: proposals.items || [],
        runtimePlanningIssues: runtimePlanningIssues.items || [],
        credentialConnections: credentialConnections.items || [],
        browserSessions: browserSessions.items || [],
        permissions: permissions.items || [],
        workspaceConnectors: workspaceConnectors.items || [],
        isLoading: false,
      });
    } catch (error) {
      set({ isLoading: false, error: actionError(error, "Failed to load acquisition state") });
    }
  },

  loadJournal: async () => {
    set({ error: null });
    try {
      const journal = await acquisitionApi.getJournal();
      set({ journal });
    } catch (error) {
      set({ error: actionError(error, "Failed to load acquisition journal") });
    }
  },

  dismissGap: async (gapId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const gap = await acquisitionApi.dismissGap(gapId, reason);
      set((state) => ({
        gaps: upsertByUpdatedAt(state.gaps, gap),
        isMutating: false,
        notice: "Gap dismissed.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to dismiss gap") });
    }
  },

  snoozeGap: async (gapId, snoozedUntil) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const gap = await acquisitionApi.snoozeGap(gapId, snoozedUntil);
      set((state) => ({
        gaps: upsertByUpdatedAt(state.gaps, gap),
        isMutating: false,
        notice: "Gap snoozed.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to snooze gap") });
    }
  },

  approveExploration: async (gapId, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const exploration = await acquisitionApi.approveExploration(gapId, body);
      set((state) => ({
        explorations: upsertByUpdatedAt(state.explorations, exploration),
        isMutating: false,
        notice: "Exploration approved.",
      }));
      void get().loadOverview();
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to approve exploration") });
    }
  },

  verifyProposal: async (proposalId, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await acquisitionApi.verifyProposal(proposalId, body);
      set({ isMutating: false, notice: "Proposal verified." });
      void get().loadOverview();
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to verify proposal") });
    }
  },

  approveActivation: async (proposalId, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const proposal = await acquisitionApi.approveActivation(proposalId, body);
      set((state) => ({
        proposals: upsertByUpdatedAt(state.proposals, proposal),
        isMutating: false,
        notice: "Activation approved.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to approve activation") });
    }
  },

  rejectActivation: async (proposalId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const proposal = await acquisitionApi.rejectActivation(proposalId, reason);
      set((state) => ({
        proposals: upsertByUpdatedAt(state.proposals, proposal),
        isMutating: false,
        notice: "Activation rejected.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to reject activation") });
    }
  },

  activateProposal: async (proposalId, approvedSnapshotHash, verificationId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const proposal = await acquisitionApi.activateProposal(proposalId, {
        approved_snapshot_hash: approvedSnapshotHash,
        verification_id: verificationId,
      });
      set((state) => ({
        proposals: upsertByUpdatedAt(state.proposals, proposal),
        isMutating: false,
        notice: "Capability activated.",
      }));
      void get().loadOverview();
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to activate proposal") });
    }
  },

  rollbackProposal: async (proposalId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const proposal = await acquisitionApi.rollbackProposal(proposalId, reason);
      set((state) => ({
        proposals: upsertByUpdatedAt(state.proposals, proposal),
        isMutating: false,
        notice: "Activation rolled back.",
      }));
      void get().loadOverview();
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to roll back activation") });
    }
  },

  dismissRuntimePlanningIssue: async (issueId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const issue = await acquisitionApi.dismissRuntimePlanningIssue(issueId, reason);
      set((state) => ({
        runtimePlanningIssues: upsertByUpdatedAt(state.runtimePlanningIssues, issue),
        isMutating: false,
        notice: "Planning issue dismissed.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to dismiss planning issue") });
    }
  },

  createCredentialConnection: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const credential = await acquisitionApi.createCredentialConnection(body);
      set((state) => ({
        credentialConnections: upsertByUpdatedAt(state.credentialConnections, credential),
        isMutating: false,
        notice: "Credential connection created.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to create credential") });
    }
  },

  validateCredentialConnection: async (credentialId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const credential = await acquisitionApi.validateCredentialConnection(credentialId);
      set((state) => ({
        credentialConnections: upsertByUpdatedAt(state.credentialConnections, credential),
        isMutating: false,
        notice: "Credential connection validated.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to validate credential") });
    }
  },

  rotateCredentialConnection: async (credentialId, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const credential = await acquisitionApi.rotateCredentialConnection(credentialId, body);
      set((state) => ({
        credentialConnections: upsertByUpdatedAt(state.credentialConnections, credential),
        isMutating: false,
        notice: "Credential connection rotated.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to rotate credential") });
    }
  },

  revokeCredentialConnection: async (credentialId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const credential = await acquisitionApi.revokeCredentialConnection(credentialId, reason);
      set((state) => ({
        credentialConnections: upsertByUpdatedAt(state.credentialConnections, credential),
        isMutating: false,
        notice: "Credential connection revoked.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to revoke credential") });
    }
  },

  terminateBrowserSession: async (sessionId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const session = await acquisitionApi.terminateBrowserSession(sessionId, reason);
      set((state) => ({
        browserSessions: upsertByUpdatedAt(state.browserSessions, session),
        isMutating: false,
        notice: "Browser session terminated.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to terminate browser session") });
    }
  },

  revokeWorkspaceConnector: async (connectorId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const connector = await acquisitionApi.revokeWorkspaceConnector(connectorId, reason);
      set((state) => ({
        workspaceConnectors: upsertByUpdatedAt(state.workspaceConnectors, connector),
        isMutating: false,
        notice: "Workspace connector revoked.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to revoke workspace connector") });
    }
  },

  revokePermission: async (permissionId, reason) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const permission = await acquisitionApi.revokePermission(permissionId, reason);
      set((state) => ({
        permissions: upsertByUpdatedAt(state.permissions, permission),
        isMutating: false,
        notice: "Permission revoked.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to revoke permission") });
    }
  },

  renewPermission: async (permissionId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const permission = await acquisitionApi.renewPermission(permissionId);
      set((state) => ({
        permissions: upsertByUpdatedAt(state.permissions, permission),
        isMutating: false,
        notice: "Permission renewed.",
      }));
    } catch (error) {
      set({ isMutating: false, error: actionError(error, "Failed to renew permission") });
    }
  },

  clearMessages: () => set({ error: null, notice: null }),
}));

export type { AcquisitionState };
