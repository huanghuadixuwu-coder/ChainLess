import { create } from "zustand";
import { api } from "@/lib/api";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ChatState {
  conversations: Conversation[];
  currentConversationId: string | null;
  messages: Record<string, Message[]>;
  isStreaming: boolean;
  streamingContent: string;

  loadConversations: () => Promise<void>;
  createConversation: () => Promise<string>;
  selectConversation: (id: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  setStreamingContent: (content: string) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: {},
  isStreaming: false,
  streamingContent: "",

  loadConversations: async () => {
    try {
      const res = await api.get("/api/v1/conversations");
      const data = await res.json();
      set({ conversations: data.conversations || data || [] });
    } catch {
      // silently fail
    }
  },

  createConversation: async () => {
    try {
      const res = await api.post("/api/v1/conversations", { title: "New Chat" });
      const data = await res.json();
      const conv = data.conversation || data;
      set((state) => ({
        conversations: [conv, ...state.conversations],
        currentConversationId: conv.id,
        messages: { ...state.messages, [conv.id]: [] },
      }));
      return conv.id;
    } catch {
      throw new Error("Failed to create conversation");
    }
  },

  selectConversation: async (id: string) => {
    set({ currentConversationId: id });
    const existing = get().messages[id];
    if (!existing) {
      try {
        const res = await api.get(`/api/v1/conversations/${id}/messages`);
        const data = await res.json();
        set((state) => ({
          messages: {
            ...state.messages,
            [id]: data.messages || data || [],
          },
        }));
      } catch {
        set((state) => ({
          messages: { ...state.messages, [id]: [] },
        }));
      }
    }
  },

  sendMessage: async (content: string) => {
    const { currentConversationId } = get();
    if (!currentConversationId) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };

    set((state) => ({
      messages: {
        ...state.messages,
        [currentConversationId]: [
          ...(state.messages[currentConversationId] || []),
          userMessage,
        ],
      },
      isStreaming: true,
      streamingContent: "",
    }));

    const assistantId = `assistant-${Date.now()}`;

    try {
      await api.streamChat(
        currentConversationId,
        content,
        (delta) => {
          set((state) => ({
            streamingContent: state.streamingContent + delta,
          }));
        },
        (errorMsg) => {
          set((state) => {
            const assistantMessage: Message = {
              id: assistantId,
              role: "assistant",
              content: `Error: ${errorMsg}`,
              created_at: new Date().toISOString(),
            };
            const convId = state.currentConversationId!;
            return {
              isStreaming: false,
              streamingContent: "",
              messages: {
                ...state.messages,
                [convId]: [...(state.messages[convId] || []), assistantMessage],
              },
            };
          });
        },
        () => {
          set((state) => {
            const streamingContent = state.streamingContent;
            const assistantMessage: Message = {
              id: assistantId,
              role: "assistant",
              content: streamingContent,
              created_at: new Date().toISOString(),
            };
            const convId = state.currentConversationId!;
            return {
              isStreaming: false,
              streamingContent: "",
              messages: {
                ...state.messages,
                [convId]: [
                  ...(state.messages[convId] || []),
                  assistantMessage,
                ],
              },
            };
          });
        }
      );
    } catch (err: unknown) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to send message";
      set((state) => {
        const convId = state.currentConversationId!;
        const assistantMessage: Message = {
          id: assistantId,
          role: "assistant",
          content: `Error: ${errorMessage}`,
          created_at: new Date().toISOString(),
        };
        return {
          isStreaming: false,
          streamingContent: "",
          messages: {
            ...state.messages,
            [convId]: [...(state.messages[convId] || []), assistantMessage],
          },
        };
      });
    }
  },

  setStreamingContent: (content: string) => {
    set({ streamingContent: content });
  },
}));
