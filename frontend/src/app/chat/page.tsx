"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTokenPresent } from "@/lib/auth-token";
import { useChatStore } from "@/stores/chat-store";
import { useArtifactStore } from "@/stores/artifact-store";
import { Sidebar } from "@/components/layout/sidebar";
import { ChatPanel } from "@/components/chat/chat-panel";
import { InputArea } from "@/components/chat/input-area";
import { PreviewPanel, PanelTab } from "@/components/chat/preview-panel";
import { Button } from "@/components/ui/button";
import { CommandPalette } from "@/components/chat/command-palette";
import { api, type StreamArtifact, type UploadedArtifact } from "@/lib/api";

export default function ChatPage() {
  const router = useRouter();
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<PanelTab>("preview");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const hasToken = useTokenPresent();
  const {
    currentConversationId,
    loadConversations,
    createConversation,
    selectConversation,
    isStreaming,
    messages,
    toolEvents,
    streamingContent,
    error,
    clearError,
  } = useChatStore();
  const { loadArtifacts, ingestArtifacts } = useArtifactStore();

  useEffect(() => {
    if (hasToken === null) {
      return;
    }
    if (!hasToken) {
      router.replace("/login");
      if (typeof window !== "undefined") {
        window.location.replace("/login");
      }
      return;
    }
    void loadConversations();
  }, [router, loadConversations, hasToken]);

  const handleNewChat = useCallback(async () => {
    try {
      const id = await createConversation();
      await selectConversation(id);
    } catch {
      // Error already handled in store
    }
  }, [createConversation, selectConversation]);

  const ensureConversation = useCallback(async () => {
    const activeId = useChatStore.getState().currentConversationId;
    if (activeId) return activeId;
    const id = await createConversation();
    await selectConversation(id);
    return id;
  }, [createConversation, selectConversation]);

  const handleSend = async (
    content: string,
    attachmentArtifactIds: string[] = []
  ) => {
    await ensureConversation();
    await useChatStore.getState().sendMessage(content, {
      attachmentArtifactIds,
    });
  };

  const handleUploadFile = async (file: File) => {
    const conversationId = await ensureConversation();
    const artifact = await api.uploadFile(conversationId, file);
    if (!artifact.id) {
      throw new Error("Upload response did not include an artifact id");
    }
    ingestArtifacts(conversationId, [
      normalizeUploadedArtifact(artifact, conversationId, file),
    ]);
    return artifact;
  };

  useEffect(() => {
    if (!currentConversationId) return;
    void loadArtifacts(currentConversationId);
  }, [currentConversationId, loadArtifacts]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) {
        return;
      }

      const key = event.key.toLowerCase();
      if (key !== "n" && key !== "k") {
        return;
      }

      event.preventDefault();

      if (isUnsafeShortcutTarget(event.target)) {
        return;
      }

      if (key === "n") {
        void handleNewChat();
        return;
      }

      if (key === "k") {
        setCommandPaletteOpen(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleNewChat]);

  if (hasToken !== true) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-950">
        <div className="text-zinc-400">Loading...</div>
      </div>
    );
  }

  const latestAssistantMessage = currentConversationId
    ? [...(messages[currentConversationId] || [])]
        .reverse()
        .find((message) => message.role === "assistant")
    : undefined;
  const latestToolEvent = currentConversationId
    ? [...(toolEvents[currentConversationId] || [])].slice(-1)[0]
    : undefined;

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Left sidebar */}
      <Sidebar onNewChat={handleNewChat} />

      {/* Center chat panel */}
      <div className="flex-1 flex flex-col min-h-0 min-w-0">
        <ChatPanel />
        {error && (
          <div className="border-t border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-red-200">
            <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
              <span>{error}</span>
              <button
                type="button"
                onClick={clearError}
                className="text-xs text-zinc-400 hover:text-zinc-100"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
        <InputArea
          onSend={handleSend}
          onUploadFile={handleUploadFile}
          disabled={isStreaming}
        />
      </div>

      <PreviewPanel
        open={rightPanelOpen}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        latestAssistantMessage={latestAssistantMessage}
        latestToolEvent={latestToolEvent}
        streamingContent={streamingContent}
        conversationId={currentConversationId}
      />

      <CommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
        onNewChat={() => void handleNewChat()}
      />

      {/* Right panel toggle button */}
      <div className="flex">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setRightPanelOpen(!rightPanelOpen)}
          className="absolute right-2 top-2 z-10 text-zinc-400 hover:text-zinc-100"
          title="Toggle preview"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-5 w-5"
          >
            {rightPanelOpen ? (
              <path d="M18 8L12 12M18 16L12 12M12 12L6 8M12 12L6 16" />
            ) : (
              <><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><line x1="9" y1="3" x2="9" y2="21" /></>
            )}
          </svg>
        </Button>
      </div>
    </div>
  );
}

function isUnsafeShortcutTarget(target: EventTarget | null) {
  if (document.querySelector('[role="dialog"], [aria-modal="true"], [data-shortcut-scope="modal"]')) {
    return true;
  }
  if (!(target instanceof HTMLElement)) return false;
  if (
    target.closest('[role="dialog"], [aria-modal="true"], [data-shortcut-scope="modal"]')
  ) {
    return true;
  }
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function normalizeUploadedArtifact(
  artifact: UploadedArtifact,
  conversationId: string,
  file: File
): StreamArtifact {
  const path = typeof artifact.path === "string" ? artifact.path : file.name;
  const sizeBytes =
    typeof artifact.size_bytes === "number"
      ? artifact.size_bytes
      : typeof artifact.size === "number"
        ? artifact.size
        : file.size;

  return {
    id: artifact.id,
    conversation_id:
      typeof artifact.conversation_id === "string"
        ? artifact.conversation_id
        : conversationId,
    run_id: artifact.run_id ?? null,
    tool_call_id: artifact.tool_call_id ?? null,
    type: typeof artifact.type === "string" ? artifact.type : "file",
    operation:
      typeof artifact.operation === "string" ? artifact.operation : "upload",
    path,
    state: typeof artifact.state === "string" ? artifact.state : "available",
    mime_type:
      typeof artifact.mime_type === "string" ? artifact.mime_type : file.type || null,
    size_bytes: sizeBytes,
    content_bytes_stored:
      typeof artifact.content_bytes_stored === "number"
        ? artifact.content_bytes_stored
        : sizeBytes,
    diff_bytes_stored:
      typeof artifact.diff_bytes_stored === "number"
        ? artifact.diff_bytes_stored
        : 0,
    has_content:
      typeof artifact.has_content === "boolean" ? artifact.has_content : true,
    has_diff:
      typeof artifact.has_diff === "boolean" ? artifact.has_diff : false,
    preview:
      artifact.preview && typeof artifact.preview === "object"
        ? artifact.preview
        : undefined,
    created_at:
      typeof artifact.created_at === "string"
        ? artifact.created_at
        : new Date().toISOString(),
    updated_at:
      typeof artifact.updated_at === "string" ? artifact.updated_at : undefined,
    expires_at:
      typeof artifact.expires_at === "string" || artifact.expires_at === null
        ? artifact.expires_at
        : undefined,
  };
}
