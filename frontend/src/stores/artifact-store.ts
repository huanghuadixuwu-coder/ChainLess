import { create } from "zustand";
import { api } from "@/lib/api";
import type { StreamArtifact } from "@/lib/api";

interface ArtifactPage {
  items?: Artifact[];
}

export interface Artifact extends StreamArtifact {
  tenant_id?: string;
  before_sha256?: string | null;
  after_sha256?: string | null;
  metadata?: Record<string, unknown>;
}

interface ArtifactPayload {
  artifact: Artifact;
  kind: "content" | "diff";
  content: string;
}

interface ArtifactState {
  artifacts: Record<string, Artifact[]>;
  selectedArtifactId: Record<string, string | null>;
  contentById: Record<string, string>;
  diffById: Record<string, string>;
  isLoading: Record<string, boolean>;
  error: string | null;

  loadArtifacts: (conversationId: string) => Promise<void>;
  ingestArtifacts: (conversationId: string, artifacts: StreamArtifact[]) => void;
  selectArtifact: (conversationId: string, artifactId: string | null) => void;
  loadArtifactContent: (artifactId: string) => Promise<void>;
  loadArtifactDiff: (artifactId: string) => Promise<void>;
  clearConversationArtifacts: (conversationId: string) => void;
  clearError: () => void;
}

const upsertArtifacts = (
  current: Artifact[],
  incoming: StreamArtifact[]
): Artifact[] => {
  const byId = new Map(current.map((artifact) => [artifact.id, artifact]));
  for (const artifact of incoming) {
    byId.set(artifact.id, {
      ...byId.get(artifact.id),
      ...artifact,
    });
  }
  return Array.from(byId.values()).sort((a, b) =>
    String(b.created_at || "").localeCompare(String(a.created_at || ""))
  );
};

export const useArtifactStore = create<ArtifactState>((set, get) => ({
  artifacts: {},
  selectedArtifactId: {},
  contentById: {},
  diffById: {},
  isLoading: {},
  error: null,

  loadArtifacts: async (conversationId: string) => {
    set((state) => ({
      isLoading: { ...state.isLoading, [conversationId]: true },
      error: null,
    }));
    try {
      const res = await api.get(
        `/api/v1/artifacts/?conversation_id=${encodeURIComponent(conversationId)}`
      );
      const data = (await res.json()) as ArtifactPage;
      const items = data.items || [];
      set((state) => ({
        artifacts: {
          ...state.artifacts,
          [conversationId]: items,
        },
        selectedArtifactId: {
          ...state.selectedArtifactId,
          [conversationId]:
            state.selectedArtifactId[conversationId] ||
            (items[0] ? items[0].id : null),
        },
        isLoading: { ...state.isLoading, [conversationId]: false },
      }));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load artifacts";
      set((state) => ({
        isLoading: { ...state.isLoading, [conversationId]: false },
        error: message,
      }));
    }
  },

  ingestArtifacts: (conversationId: string, artifacts: StreamArtifact[]) => {
    if (!artifacts.length) return;
    set((state) => {
      const nextArtifacts = upsertArtifacts(
        state.artifacts[conversationId] || [],
        artifacts
      );
      return {
        artifacts: {
          ...state.artifacts,
          [conversationId]: nextArtifacts,
        },
        selectedArtifactId: {
          ...state.selectedArtifactId,
          [conversationId]:
            state.selectedArtifactId[conversationId] || nextArtifacts[0]?.id || null,
        },
      };
    });
  },

  selectArtifact: (conversationId: string, artifactId: string | null) => {
    set((state) => ({
      selectedArtifactId: {
        ...state.selectedArtifactId,
        [conversationId]: artifactId,
      },
    }));
  },

  loadArtifactContent: async (artifactId: string) => {
    if (Object.prototype.hasOwnProperty.call(get().contentById, artifactId)) return;
    try {
      const res = await api.get(`/api/v1/artifacts/${artifactId}/content`);
      const data = (await res.json()) as ArtifactPayload;
      set((state) => ({
        contentById: { ...state.contentById, [artifactId]: data.content },
        error: null,
      }));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load artifact content";
      set({ error: message });
    }
  },

  loadArtifactDiff: async (artifactId: string) => {
    if (Object.prototype.hasOwnProperty.call(get().diffById, artifactId)) return;
    try {
      const res = await api.get(`/api/v1/artifacts/${artifactId}/diff`);
      const data = (await res.json()) as ArtifactPayload;
      set((state) => ({
        diffById: { ...state.diffById, [artifactId]: data.content },
        error: null,
      }));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load artifact diff";
      set({ error: message });
    }
  },

  clearConversationArtifacts: (conversationId: string) => {
    set((state) => {
      const nextArtifacts = { ...state.artifacts };
      const nextSelected = { ...state.selectedArtifactId };
      delete nextArtifacts[conversationId];
      delete nextSelected[conversationId];
      return {
        artifacts: nextArtifacts,
        selectedArtifactId: nextSelected,
      };
    });
  },

  clearError: () => {
    set({ error: null });
  },
}));
