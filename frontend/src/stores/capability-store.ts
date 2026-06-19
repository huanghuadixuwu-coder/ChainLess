import { create } from "zustand";
import type { StateCreator } from "zustand";
import { api } from "@/lib/api";
import type {
  CapabilityCandidate,
  CapabilityCandidateHint,
  CandidateStatus,
  Worker,
  WorkerNotice,
  WorkerRun,
  WorkerVersion,
} from "@/lib/api";

type CandidatesByStatus = Record<string, CapabilityCandidate[]>;
type CapabilitySet = Parameters<StateCreator<CapabilityState>>[0];

interface CapabilityState {
  candidatesByStatus: CandidatesByStatus;
  candidateHintsByConversation: Record<string, CapabilityCandidateHint[]>;
  workers: Worker[];
  workerRuns: Record<string, WorkerRun[]>;
  workerVersions: Record<string, WorkerVersion[]>;
  workerNoticesByConversation: Record<string, WorkerNotice[]>;
  isLoadingCandidates: boolean;
  isLoadingWorkers: boolean;
  isMutating: boolean;
  error: string | null;
  notice: string | null;

  loadCandidates: () => Promise<void>;
  loadWorkers: () => Promise<void>;
  loadWorkerRuns: (workerId: string) => Promise<void>;
  loadWorkerVersions: (workerId: string) => Promise<void>;
  ingestCandidateHint: (
    conversationId: string,
    candidate: CapabilityCandidateHint
  ) => void;
  ingestWorkerNotice: (conversationId: string, notice: WorkerNotice) => void;
  acceptCandidate: (candidateId: string) => Promise<void>;
  dismissCandidate: (candidateId: string) => Promise<void>;
  archiveCandidate: (candidateId: string) => Promise<void>;
  snoozeCandidate: (candidateId: string, snoozedUntil: string) => Promise<void>;
  muteCandidatePattern: (candidateId: string, mutePattern: string) => Promise<void>;
  mergeCandidate: (
    candidateId: string,
    targetCandidateId: string,
    mergeReason?: string
  ) => Promise<void>;
  enableWorker: (workerId: string) => Promise<void>;
  disableWorker: (workerId: string) => Promise<void>;
  deleteWorker: (workerId: string) => Promise<void>;
  rollbackWorker: (
    workerId: string,
    body: {
      version_id: string;
      activation_token?: string | null;
      reason?: string | null;
    }
  ) => Promise<void>;
  sendWorkerFeedback: (
    workerId: string,
    feedback: string,
    options?: { sourceRunId?: string | null; reason?: string | null }
  ) => Promise<void>;
  clearMessages: () => void;
}

const groupCandidates = (candidates: CapabilityCandidate[]): CandidatesByStatus =>
  candidates.reduce<CandidatesByStatus>((groups, candidate) => {
    const status = candidate.status || "new";
    groups[status] = [...(groups[status] || []), candidate];
    return groups;
  }, {});

const allCandidates = (groups: CandidatesByStatus) =>
  Object.values(groups).flat();

const upsertCandidate = (
  groups: CandidatesByStatus,
  candidate: CapabilityCandidate
) => {
  const next = allCandidates(groups).filter((item) => item.id !== candidate.id);
  next.push(candidate);
  return groupCandidates(
    next.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
  );
};

const upsertWorker = (workers: Worker[], worker: Worker) =>
  [worker, ...workers.filter((item) => item.id !== worker.id)].sort((a, b) =>
    String(b.updated_at || b.created_at).localeCompare(
      String(a.updated_at || a.created_at)
    )
  );

const upsertHint = (
  hints: CapabilityCandidateHint[],
  candidate: CapabilityCandidateHint
) => {
  const next = [candidate, ...hints.filter((item) => item.id !== candidate.id)];
  return next.slice(0, 20);
};

const appendNotice = (notices: WorkerNotice[], notice: WorkerNotice) =>
  [notice, ...notices].slice(0, 20);

const oneDayFromNow = () =>
  new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

const mutation =
  (
    set: CapabilitySet,
    action: () => Promise<CapabilityCandidate>,
    success: string
  ) =>
  async () => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const candidate = await action();
      set((state) => ({
        candidatesByStatus: upsertCandidate(state.candidatesByStatus, candidate),
        isMutating: false,
        notice: success,
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Capability action failed";
      set({ isMutating: false, error: message });
    }
  };

export const useCapabilityStore = create<CapabilityState>((set, get) => ({
  candidatesByStatus: {},
  candidateHintsByConversation: {},
  workers: [],
  workerRuns: {},
  workerVersions: {},
  workerNoticesByConversation: {},
  isLoadingCandidates: false,
  isLoadingWorkers: false,
  isMutating: false,
  error: null,
  notice: null,

  loadCandidates: async () => {
    set({ isLoadingCandidates: true, error: null });
    try {
      const page = await api.listCapabilityCandidates({ limit: 100 });
      set({
        candidatesByStatus: groupCandidates(page.items || []),
        isLoadingCandidates: false,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load candidates";
      set({ isLoadingCandidates: false, error: message });
    }
  },

  loadWorkers: async () => {
    set({ isLoadingWorkers: true, error: null });
    try {
      const page = await api.listWorkers({ limit: 100 });
      set({ workers: page.items || [], isLoadingWorkers: false });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load workers";
      set({ isLoadingWorkers: false, error: message });
    }
  },

  loadWorkerRuns: async (workerId: string) => {
    set({ error: null });
    try {
      const page = await api.listWorkerRuns(workerId, { limit: 20 });
      set((state) => ({
        workerRuns: { ...state.workerRuns, [workerId]: page.items || [] },
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load worker runs";
      set({ error: message });
    }
  },

  loadWorkerVersions: async (workerId: string) => {
    set({ error: null });
    try {
      const page = await api.listWorkerVersions(workerId);
      set((state) => ({
        workerVersions: { ...state.workerVersions, [workerId]: page.items || [] },
      }));
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to load worker versions";
      set({ error: message });
    }
  },

  ingestCandidateHint: (conversationId, candidate) => {
    set((state) => ({
      candidateHintsByConversation: {
        ...state.candidateHintsByConversation,
        [conversationId]: upsertHint(
          state.candidateHintsByConversation[conversationId] || [],
          candidate
        ),
      },
    }));
  },

  ingestWorkerNotice: (conversationId, notice) => {
    set((state) => ({
      workerNoticesByConversation: {
        ...state.workerNoticesByConversation,
        [conversationId]: appendNotice(
          state.workerNoticesByConversation[conversationId] || [],
          notice
        ),
      },
    }));
  },

  acceptCandidate: (candidateId) =>
    mutation(
      set,
      () => api.acceptCapabilityCandidate(candidateId),
      "Candidate accepted."
    )(),

  dismissCandidate: (candidateId) =>
    mutation(
      set,
      () => api.dismissCapabilityCandidate(candidateId),
      "Candidate dismissed."
    )(),

  archiveCandidate: (candidateId) =>
    mutation(
      set,
      () => api.archiveCapabilityCandidate(candidateId),
      "Candidate archived."
    )(),

  snoozeCandidate: (candidateId, snoozedUntil = oneDayFromNow()) =>
    mutation(
      set,
      () => api.snoozeCapabilityCandidate(candidateId, snoozedUntil),
      "Candidate snoozed."
    )(),

  muteCandidatePattern: (candidateId, mutePattern) =>
    mutation(
      set,
      () => api.muteCapabilityCandidatePattern(candidateId, mutePattern),
      "Candidate pattern muted."
    )(),

  mergeCandidate: (candidateId, targetCandidateId, mergeReason) =>
    mutation(
      set,
      () => api.mergeCapabilityCandidate(candidateId, targetCandidateId, mergeReason),
      "Candidate merged."
    )(),

  enableWorker: async (workerId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const worker = await api.enableWorker(workerId);
      set((state) => ({
        workers: upsertWorker(state.workers, worker),
        isMutating: false,
        notice: "Worker enabled.",
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to enable worker";
      set({ isMutating: false, error: message });
    }
  },

  disableWorker: async (workerId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const worker = await api.disableWorker(workerId);
      set((state) => ({
        workers: upsertWorker(state.workers, worker),
        isMutating: false,
        notice: "Worker disabled.",
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to disable worker";
      set({ isMutating: false, error: message });
    }
  },

  deleteWorker: async (workerId) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const worker = await api.deleteWorker(workerId);
      set((state) => ({
        workers: upsertWorker(state.workers, worker),
        isMutating: false,
        notice: "Worker deleted.",
      }));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete worker";
      set({ isMutating: false, error: message });
    }
  },

  rollbackWorker: async (workerId, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const worker = await api.rollbackWorker(workerId, {
        ...body,
        confirmation_evidence: { source: "settings_workers_section" },
      });
      set((state) => ({
        workers: upsertWorker(state.workers, worker),
        isMutating: false,
        notice: "Worker rolled back.",
      }));
      void get().loadWorkerVersions(workerId);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to rollback worker";
      set({ isMutating: false, error: message });
    }
  },

  sendWorkerFeedback: async (workerId, feedback, options = {}) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.sendWorkerFeedback(workerId, {
        feedback,
        source_run_id: options.sourceRunId,
        reason: options.reason,
        metadata: { source: "frontend" },
      });
      set({ isMutating: false, notice: "Worker feedback recorded." });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to send feedback";
      set({ isMutating: false, error: message });
    }
  },

  clearMessages: () => set({ error: null, notice: null }),
}));

export type { CandidateStatus };
