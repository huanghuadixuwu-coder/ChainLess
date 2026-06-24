import { create } from "zustand";
import { api } from "@/lib/api";
import type {
  AcquisitionNotice,
  CapabilityCandidateHint,
  MessageAttachment,
  StreamArtifact,
  StreamContext,
  WorkerNotice,
} from "@/lib/api";
import { useArtifactStore } from "@/stores/artifact-store";
import { useCapabilityStore } from "@/stores/capability-store";

const ACTIVE_CONVERSATION_STORAGE_KEY = "activeConversationId";

export interface Message {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  attachments?: MessageAttachment[];
}

export interface Conversation {
  id: string;
  title: string;
  status?: string;
  created_at: string;
  updated_at: string;
}

export interface ToolEvent {
  id: string;
  name: string;
  args: Record<string, unknown>;
  created_at: string;
  status: "running" | "completed" | "error" | "needs_confirmation" | "denied";
  risk?: string;
  result?: string;
  error?: string;
  artifacts?: StreamArtifact[];
}

export interface PendingConfirmation {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  risk: string;
  timeout_s: number;
  received_at: string;
}

interface ChatState {
  conversations: Conversation[];
  currentConversationId: string | null;
  messages: Record<string, Message[]>;
  toolEvents: Record<string, ToolEvent[]>;
  pendingConfirmations: Record<string, PendingConfirmation | null>;
  contextSummaries: Record<string, StreamContext | null>;
  capabilityCandidates: Record<string, CapabilityCandidateHint[]>;
  workerNotices: Record<string, WorkerNotice[]>;
  acquisitionNotices: Record<string, AcquisitionNotice[]>;
  isStreaming: boolean;
  streamingContent: string;
  isLoadingConversations: boolean;
  error: string | null;

  loadConversations: () => Promise<void>;
  createConversation: () => Promise<string>;
  selectConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  archiveConversation: (id: string) => Promise<void>;
  sendMessage: (
    content: string,
    options?: { attachmentArtifactIds?: string[] }
  ) => Promise<void>;
  respondToConfirmation: (
    approved: boolean,
    options?: { timedOut?: boolean }
  ) => Promise<void>;
  setStreamingContent: (content: string) => void;
  clearError: () => void;
}

const upsertToolEvent = (
  events: ToolEvent[],
  nextEvent: ToolEvent
): ToolEvent[] => {
  const existingIndex = events.findIndex((event) => event.id === nextEvent.id);
  if (existingIndex === -1) {
    return [...events, nextEvent];
  }

  const next = [...events];
  const existing = next[existingIndex];
  const nextArgs =
    Object.keys(nextEvent.args || {}).length > 0 ? nextEvent.args : existing.args;
  next[existingIndex] = {
    ...existing,
    ...nextEvent,
    args: nextArgs,
  };
  return next;
};

const readStoredConversationId = (): string | null => {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY);
};

const storeConversationId = (conversationId: string | null) => {
  if (typeof window === "undefined") {
    return;
  }

  if (conversationId) {
    window.localStorage.setItem(
      ACTIVE_CONVERSATION_STORAGE_KEY,
      conversationId
    );
    return;
  }

  window.localStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY);
};

const normalizeMessages = (messages: Message[] = []) =>
  messages.map((message) => ({
    ...message,
    attachments: Array.isArray(message.attachments)
      ? message.attachments
      : undefined,
  }));

const selectedAttachmentMetadata = (
  conversationId: string,
  attachmentArtifactIds: string[] = []
): MessageAttachment[] => {
  if (!attachmentArtifactIds.length) return [];

  const artifacts = useArtifactStore.getState().artifacts[conversationId] || [];
  const byId = new Map(artifacts.map((artifact) => [artifact.id, artifact]));
  return attachmentArtifactIds.map((id) => {
    const artifact = byId.get(id);
    return {
      id,
      path: artifact?.path || "attachment",
      state: artifact?.state || "available",
      size_bytes: artifact?.size_bytes,
      mime_type: artifact?.mime_type,
      download_url: artifact?.download_url,
      conversation_id: artifact?.conversation_id,
      type: artifact?.type,
      operation: artifact?.operation,
      has_content: artifact?.has_content,
      has_diff: artifact?.has_diff,
    };
  });
};

const upsertCapabilityHint = (
  hints: CapabilityCandidateHint[],
  candidate: CapabilityCandidateHint
) => [candidate, ...hints.filter((item) => item.id !== candidate.id)].slice(0, 20);

const appendWorkerNotice = (notices: WorkerNotice[], notice: WorkerNotice) =>
  [notice, ...notices].slice(0, 20);

const appendAcquisitionNotice = (
  notices: AcquisitionNotice[],
  notice: AcquisitionNotice
) => [notice, ...notices].slice(0, 20);

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: {},
  toolEvents: {},
  pendingConfirmations: {},
  contextSummaries: {},
  capabilityCandidates: {},
  workerNotices: {},
  acquisitionNotices: {},
  isStreaming: false,
  streamingContent: "",
  isLoadingConversations: false,
  error: null,

  loadConversations: async () => {
    set({ isLoadingConversations: true, error: null });
    try {
      const res = await api.get("/api/v1/conversations/");
      const data = await res.json();
      const conversations = data.items || [];
      const currentConversationId = get().currentConversationId;
      const storedConversationId = readStoredConversationId();
      const candidateConversationId =
        currentConversationId || storedConversationId;
      const restoredConversationId = conversations.some(
        (conversation: Conversation) => conversation.id === candidateConversationId
      )
        ? candidateConversationId
        : null;

      set({
        conversations,
        currentConversationId: restoredConversationId,
      });

      if (!restoredConversationId) {
        storeConversationId(null);
        set({ isLoadingConversations: false });
        return;
      }

      if (get().messages[restoredConversationId]) {
        storeConversationId(restoredConversationId);
        set({ isLoadingConversations: false });
        return;
      }

      try {
        const detailRes = await api.get(
          `/api/v1/conversations/${restoredConversationId}`
        );
        const detail = await detailRes.json();
        set((state) => ({
          messages: {
            ...state.messages,
            [restoredConversationId]: normalizeMessages(detail.messages || []),
          },
          toolEvents: {
            ...state.toolEvents,
            [restoredConversationId]:
              state.toolEvents[restoredConversationId] || [],
          },
          pendingConfirmations: {
            ...state.pendingConfirmations,
            [restoredConversationId]:
              state.pendingConfirmations[restoredConversationId] || null,
          },
          contextSummaries: {
            ...state.contextSummaries,
            [restoredConversationId]:
              state.contextSummaries[restoredConversationId] || null,
          },
          capabilityCandidates: {
            ...state.capabilityCandidates,
            [restoredConversationId]:
              state.capabilityCandidates[restoredConversationId] || [],
          },
          workerNotices: {
            ...state.workerNotices,
            [restoredConversationId]:
              state.workerNotices[restoredConversationId] || [],
          },
          acquisitionNotices: {
            ...state.acquisitionNotices,
            [restoredConversationId]:
              state.acquisitionNotices[restoredConversationId] || [],
          },
        }));
      } catch {
        set((state) => ({
          messages: {
            ...state.messages,
            [restoredConversationId]: [],
          },
          toolEvents: {
            ...state.toolEvents,
            [restoredConversationId]:
              state.toolEvents[restoredConversationId] || [],
          },
          pendingConfirmations: {
            ...state.pendingConfirmations,
            [restoredConversationId]:
              state.pendingConfirmations[restoredConversationId] || null,
          },
          contextSummaries: {
            ...state.contextSummaries,
            [restoredConversationId]:
              state.contextSummaries[restoredConversationId] || null,
          },
          capabilityCandidates: {
            ...state.capabilityCandidates,
            [restoredConversationId]:
              state.capabilityCandidates[restoredConversationId] || [],
          },
          workerNotices: {
            ...state.workerNotices,
            [restoredConversationId]:
              state.workerNotices[restoredConversationId] || [],
          },
          acquisitionNotices: {
            ...state.acquisitionNotices,
            [restoredConversationId]:
              state.acquisitionNotices[restoredConversationId] || [],
          },
        }));
      }

      storeConversationId(restoredConversationId);
      set({ isLoadingConversations: false });
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to load conversations";
      set({ isLoadingConversations: false, error: errorMessage });
    }
  },

  createConversation: async () => {
    try {
      const res = await api.post("/api/v1/conversations/", { title: "New Chat" });
      const data = await res.json();
      const conv = data;
      set((state) => ({
        conversations: [conv, ...state.conversations],
        currentConversationId: conv.id,
        messages: { ...state.messages, [conv.id]: [] },
        toolEvents: { ...state.toolEvents, [conv.id]: [] },
        pendingConfirmations: { ...state.pendingConfirmations, [conv.id]: null },
        contextSummaries: { ...state.contextSummaries, [conv.id]: null },
        capabilityCandidates: { ...state.capabilityCandidates, [conv.id]: [] },
        workerNotices: { ...state.workerNotices, [conv.id]: [] },
        acquisitionNotices: { ...state.acquisitionNotices, [conv.id]: [] },
      }));
      storeConversationId(conv.id);
      return conv.id;
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to create conversation";
      set({ error: errorMessage });
      throw new Error("Failed to create conversation");
    }
  },

  selectConversation: async (id: string) => {
    set({ currentConversationId: id });
    storeConversationId(id);
    const existing = get().messages[id];
    if (!existing) {
      try {
        const res = await api.get(`/api/v1/conversations/${id}`);
        const data = await res.json();
        set((state) => ({
          messages: {
            ...state.messages,
            [id]: normalizeMessages(data.messages || []),
          },
          toolEvents: {
            ...state.toolEvents,
            [id]: state.toolEvents[id] || [],
          },
          pendingConfirmations: {
            ...state.pendingConfirmations,
            [id]: state.pendingConfirmations[id] || null,
          },
          contextSummaries: {
            ...state.contextSummaries,
            [id]: state.contextSummaries[id] || null,
          },
          capabilityCandidates: {
            ...state.capabilityCandidates,
            [id]: state.capabilityCandidates[id] || [],
          },
          workerNotices: {
            ...state.workerNotices,
            [id]: state.workerNotices[id] || [],
          },
          acquisitionNotices: {
            ...state.acquisitionNotices,
            [id]: state.acquisitionNotices[id] || [],
          },
        }));
      } catch (err: unknown) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to load conversation";
        set((state) => ({
          messages: { ...state.messages, [id]: [] },
          toolEvents: { ...state.toolEvents, [id]: state.toolEvents[id] || [] },
          pendingConfirmations: {
            ...state.pendingConfirmations,
            [id]: state.pendingConfirmations[id] || null,
          },
          contextSummaries: {
            ...state.contextSummaries,
            [id]: state.contextSummaries[id] || null,
          },
          capabilityCandidates: {
            ...state.capabilityCandidates,
            [id]: state.capabilityCandidates[id] || [],
          },
          workerNotices: {
            ...state.workerNotices,
            [id]: state.workerNotices[id] || [],
          },
          acquisitionNotices: {
            ...state.acquisitionNotices,
            [id]: state.acquisitionNotices[id] || [],
          },
          error: errorMessage,
        }));
      }
    }
  },

  renameConversation: async (id: string, title: string) => {
    const nextTitle = title.trim();
    if (!nextTitle) {
      throw new Error("Conversation title cannot be empty");
    }

    const res = await api.patch(`/api/v1/conversations/${id}`, {
      title: nextTitle,
    });
    const data = await res.json();
    set((state) => ({
      conversations: state.conversations.map((conv) =>
        conv.id === id ? { ...conv, ...data } : conv
      ),
      error: null,
    }));
  },

  archiveConversation: async (id: string) => {
    await api.delete(`/api/v1/conversations/${id}`);
    useArtifactStore.getState().clearConversationArtifacts(id);
    set((state) => {
      const nextMessages = { ...state.messages };
      const nextToolEvents = { ...state.toolEvents };
      const nextPending = { ...state.pendingConfirmations };
      const nextContext = { ...state.contextSummaries };
      const nextCandidates = { ...state.capabilityCandidates };
      const nextWorkerNotices = { ...state.workerNotices };
      const nextAcquisitionNotices = { ...state.acquisitionNotices };
      delete nextMessages[id];
      delete nextToolEvents[id];
      delete nextPending[id];
      delete nextContext[id];
      delete nextCandidates[id];
      delete nextWorkerNotices[id];
      delete nextAcquisitionNotices[id];

      return {
        conversations: state.conversations.filter((conv) => conv.id !== id),
        currentConversationId:
          state.currentConversationId === id ? null : state.currentConversationId,
        messages: nextMessages,
        toolEvents: nextToolEvents,
        pendingConfirmations: nextPending,
        contextSummaries: nextContext,
        capabilityCandidates: nextCandidates,
        workerNotices: nextWorkerNotices,
        acquisitionNotices: nextAcquisitionNotices,
        streamingContent:
          state.currentConversationId === id ? "" : state.streamingContent,
        isStreaming:
          state.currentConversationId === id ? false : state.isStreaming,
      };
    });
    if (get().currentConversationId === null) {
      storeConversationId(null);
    }
    set({ error: null });
  },

  sendMessage: async (
    content: string,
    options: { attachmentArtifactIds?: string[] } = {}
  ) => {
    const { currentConversationId } = get();
    if (!currentConversationId) return;
    const targetConversationId = currentConversationId;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
      attachments: selectedAttachmentMetadata(
        targetConversationId,
        options.attachmentArtifactIds
      ),
    };

    set((state) => ({
      messages: {
        ...state.messages,
        [targetConversationId]: [
          ...(state.messages[targetConversationId] || []),
          userMessage,
        ],
      },
      toolEvents: {
        ...state.toolEvents,
        [targetConversationId]: state.toolEvents[targetConversationId] || [],
      },
      pendingConfirmations: {
        ...state.pendingConfirmations,
        [targetConversationId]: null,
      },
      contextSummaries: {
        ...state.contextSummaries,
        [targetConversationId]: null,
      },
      capabilityCandidates: {
        ...state.capabilityCandidates,
        [targetConversationId]: state.capabilityCandidates[targetConversationId] || [],
      },
      workerNotices: {
        ...state.workerNotices,
        [targetConversationId]: state.workerNotices[targetConversationId] || [],
      },
      acquisitionNotices: {
        ...state.acquisitionNotices,
        [targetConversationId]:
          state.acquisitionNotices[targetConversationId] || [],
      },
      isStreaming: true,
      streamingContent: "",
    }));

    const assistantId = `assistant-${Date.now()}`;

    try {
      await api.streamChat(
        currentConversationId,
        content,
        {
          onContext: (context) => {
            set((state) => ({
              contextSummaries: {
                ...state.contextSummaries,
                [targetConversationId]: context,
              },
            }));
          },
          onDelta: (delta) => {
            set((state) => ({
              streamingContent: state.streamingContent + delta,
            }));
          },
          onToolCallStart: (toolCallId, name, args, risk) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [targetConversationId]: upsertToolEvent(
                  state.toolEvents[targetConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args,
                    created_at: new Date().toISOString(),
                    status: "running",
                    risk,
                  }
                ),
              },
            }));
          },
          onToolResult: (toolCallId, name, result, artifacts = []) => {
            if (artifacts.length) {
              useArtifactStore
                .getState()
                .ingestArtifacts(targetConversationId, artifacts);
            }
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [targetConversationId]: upsertToolEvent(
                  state.toolEvents[targetConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args: {},
                    created_at: new Date().toISOString(),
                    status: "completed",
                    result,
                    artifacts,
                  }
                ),
              },
              pendingConfirmations: {
                ...state.pendingConfirmations,
                [targetConversationId]:
                  state.pendingConfirmations[targetConversationId]?.tool_call_id === toolCallId
                    ? null
                    : state.pendingConfirmations[targetConversationId] || null,
              },
            }));
          },
          onToolError: (toolCallId, name, error) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [targetConversationId]: upsertToolEvent(
                  state.toolEvents[targetConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args: {},
                    created_at: new Date().toISOString(),
                    status: "error",
                    error,
                  }
                ),
              },
            }));
          },
          onConfirmationRequired: (confirmation) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [targetConversationId]: upsertToolEvent(
                  state.toolEvents[targetConversationId] || [],
                  {
                    id: confirmation.tool_call_id,
                    name: confirmation.tool_name,
                    args: confirmation.args,
                    created_at: new Date().toISOString(),
                    status: "needs_confirmation",
                    risk: confirmation.risk,
                  }
                ),
              },
              pendingConfirmations: {
                ...state.pendingConfirmations,
                [targetConversationId]: {
                  ...confirmation,
                  received_at: new Date().toISOString(),
                },
              },
              isStreaming: false,
            }));
          },
          onCapabilityCandidate: (candidate) => {
            useCapabilityStore
              .getState()
              .ingestCandidateHint(targetConversationId, candidate);
            set((state) => ({
              capabilityCandidates: {
                ...state.capabilityCandidates,
                [targetConversationId]: upsertCapabilityHint(
                  state.capabilityCandidates[targetConversationId] || [],
                  candidate
                ),
              },
            }));
            void useCapabilityStore.getState().loadCandidates();
          },
          onWorkerNotice: (notice) => {
            useCapabilityStore
              .getState()
              .ingestWorkerNotice(targetConversationId, notice);
            set((state) => ({
              workerNotices: {
                ...state.workerNotices,
                [targetConversationId]: appendWorkerNotice(
                  state.workerNotices[targetConversationId] || [],
                  notice
                ),
              },
            }));
          },
          onAcquisitionNotice: (notice) => {
            set((state) => ({
              acquisitionNotices: {
                ...state.acquisitionNotices,
                [targetConversationId]: appendAcquisitionNotice(
                  state.acquisitionNotices[targetConversationId] || [],
                  notice
                ),
              },
            }));
          },
          onError: (errorMsg) => {
            set((state) => {
              const assistantMessage: Message = {
                id: assistantId,
                role: "assistant",
                content: `Error: ${errorMsg}`,
                created_at: new Date().toISOString(),
              };
              return {
                isStreaming: false,
                streamingContent: "",
                messages: {
                  ...state.messages,
                  [targetConversationId]: [
                    ...(state.messages[targetConversationId] || []),
                    assistantMessage,
                  ],
                },
              };
            });
          },
          onDone: () => {
            set((state) => {
              const streamingContent = state.streamingContent;
              if (!streamingContent.trim()) {
                return {
                  isStreaming: false,
                  streamingContent: "",
                };
              }
              const assistantMessage: Message = {
                id: assistantId,
                role: "assistant",
                content: streamingContent,
                created_at: new Date().toISOString(),
              };
              return {
                isStreaming: false,
                streamingContent: "",
                messages: {
                  ...state.messages,
                  [targetConversationId]: [
                    ...(state.messages[targetConversationId] || []),
                    assistantMessage,
                  ],
                },
              };
            });
          },
        },
        { attachmentArtifactIds: options.attachmentArtifactIds }
      );
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to send message";
      set((state) => {
        const assistantMessage: Message = {
          id: assistantId,
          role: "assistant",
          content: `Error: ${errorMessage}`,
          created_at: new Date().toISOString(),
        };
        return {
          isStreaming: false,
          streamingContent: "",
          error: errorMessage,
          messages: {
            ...state.messages,
            [targetConversationId]: [
              ...(state.messages[targetConversationId] || []),
              assistantMessage,
            ],
          },
        };
      });
    }
  },

  respondToConfirmation: async (
    approved: boolean,
    options?: { timedOut?: boolean }
  ) => {
    const { currentConversationId, pendingConfirmations } = get();
    if (!currentConversationId) return;

    const pending = pendingConfirmations[currentConversationId];
    if (!pending) return;

    const timedOut = options?.timedOut ?? false;

    set({ isStreaming: true, streamingContent: "" });

    if (!approved) {
      set((state) => ({
        toolEvents: {
          ...state.toolEvents,
          [currentConversationId]: upsertToolEvent(
            state.toolEvents[currentConversationId] || [],
            {
              id: pending.tool_call_id,
              name: pending.tool_name,
              args: pending.args,
              created_at: new Date().toISOString(),
              status: "denied",
              error: timedOut
                ? "Confirmation timed out."
                : "User denied this action.",
            }
          ),
        },
        pendingConfirmations: {
          ...state.pendingConfirmations,
          [currentConversationId]: null,
        },
      }));
    }

    const assistantId = `assistant-${Date.now()}`;

    try {
      await api.streamConfirmation(
        currentConversationId,
        {
          tool_call_id: pending.tool_call_id,
          approved,
          decision: timedOut ? "timeout" : approved ? "approve" : "deny",
          tool_name: pending.tool_name,
          args: pending.args,
        },
        {
          onContext: (context) => {
            set((state) => ({
              contextSummaries: {
                ...state.contextSummaries,
                [currentConversationId]: context,
              },
            }));
          },
          onDelta: (delta) => {
            set((state) => ({
              streamingContent: state.streamingContent + delta,
            }));
          },
          onToolCallStart: (toolCallId, name, args, risk) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [currentConversationId]: upsertToolEvent(
                  state.toolEvents[currentConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args,
                    created_at: new Date().toISOString(),
                    status: "running",
                    risk,
                  }
                ),
              },
            }));
          },
          onToolResult: (toolCallId, name, result, artifacts = []) => {
            if (artifacts.length) {
              useArtifactStore
                .getState()
                .ingestArtifacts(currentConversationId, artifacts);
            }
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [currentConversationId]: upsertToolEvent(
                  state.toolEvents[currentConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args: {},
                    created_at: new Date().toISOString(),
                    status: "completed",
                    result,
                    artifacts,
                  }
                ),
              },
              pendingConfirmations: {
                ...state.pendingConfirmations,
                [currentConversationId]: null,
              },
            }));
          },
          onToolError: (toolCallId, name, error) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [currentConversationId]: upsertToolEvent(
                  state.toolEvents[currentConversationId] || [],
                  {
                    id: toolCallId || `${name}-${Date.now()}`,
                    name,
                    args: {},
                    created_at: new Date().toISOString(),
                    status: "error",
                    error,
                  }
                ),
              },
              pendingConfirmations: {
                ...state.pendingConfirmations,
                [currentConversationId]: null,
              },
            }));
          },
          onConfirmationRequired: (confirmation) => {
            set((state) => ({
              toolEvents: {
                ...state.toolEvents,
                [currentConversationId]: upsertToolEvent(
                  state.toolEvents[currentConversationId] || [],
                  {
                    id: confirmation.tool_call_id,
                    name: confirmation.tool_name,
                    args: confirmation.args,
                    created_at: new Date().toISOString(),
                    status: "needs_confirmation",
                    risk: confirmation.risk,
                  }
                ),
              },
              pendingConfirmations: {
                ...state.pendingConfirmations,
                [currentConversationId]: {
                  ...confirmation,
                  received_at: new Date().toISOString(),
                },
              },
              isStreaming: false,
            }));
          },
          onCapabilityCandidate: (candidate) => {
            useCapabilityStore
              .getState()
              .ingestCandidateHint(currentConversationId, candidate);
            set((state) => ({
              capabilityCandidates: {
                ...state.capabilityCandidates,
                [currentConversationId]: upsertCapabilityHint(
                  state.capabilityCandidates[currentConversationId] || [],
                  candidate
                ),
              },
            }));
            void useCapabilityStore.getState().loadCandidates();
          },
          onWorkerNotice: (notice) => {
            useCapabilityStore
              .getState()
              .ingestWorkerNotice(currentConversationId, notice);
            set((state) => ({
              workerNotices: {
                ...state.workerNotices,
                [currentConversationId]: appendWorkerNotice(
                  state.workerNotices[currentConversationId] || [],
                  notice
                ),
              },
            }));
          },
          onAcquisitionNotice: (notice) => {
            set((state) => ({
              acquisitionNotices: {
                ...state.acquisitionNotices,
                [currentConversationId]: appendAcquisitionNotice(
                  state.acquisitionNotices[currentConversationId] || [],
                  notice
                ),
              },
            }));
          },
          onError: (errorMsg) => {
            set((state) => {
              const assistantMessage: Message = {
                id: assistantId,
                role: "assistant",
                content: `Error: ${errorMsg}`,
                created_at: new Date().toISOString(),
              };
              return {
                isStreaming: false,
                streamingContent: "",
                messages: {
                  ...state.messages,
                  [currentConversationId]: [
                    ...(state.messages[currentConversationId] || []),
                    assistantMessage,
                  ],
                },
              };
            });
          },
          onDone: () => {
            set((state) => {
              const streamingContent = state.streamingContent;
              if (!streamingContent.trim()) {
                return {
                  isStreaming: false,
                  streamingContent: "",
                  pendingConfirmations: {
                    ...state.pendingConfirmations,
                    [currentConversationId]: null,
                  },
                };
              }
              const assistantMessage: Message = {
                id: assistantId,
                role: "assistant",
                content: streamingContent,
                created_at: new Date().toISOString(),
              };
              return {
                isStreaming: false,
                streamingContent: "",
                pendingConfirmations: {
                  ...state.pendingConfirmations,
                  [currentConversationId]: null,
                },
                messages: {
                  ...state.messages,
                  [currentConversationId]: [
                    ...(state.messages[currentConversationId] || []),
                    assistantMessage,
                  ],
                },
              };
            });
          },
        }
      );
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to continue after confirmation";
      set((state) => ({
        isStreaming: false,
        streamingContent: "",
        error: errorMessage,
        pendingConfirmations: {
          ...state.pendingConfirmations,
          [currentConversationId]: null,
        },
        messages: {
          ...state.messages,
          [currentConversationId]: [
            ...(state.messages[currentConversationId] || []),
            {
              id: assistantId,
              role: "assistant",
              content: `Error: ${errorMessage}`,
              created_at: new Date().toISOString(),
            },
          ],
        },
      }));
    }
  },

  setStreamingContent: (content: string) => {
    set({ streamingContent: content });
  },

  clearError: () => {
    set({ error: null });
  },
}));
