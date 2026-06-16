"use client";

import { useChatStore } from "@/stores/chat-store";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { usePathname, useRouter } from "next/navigation";

interface SidebarProps {
  onNewChat: () => void;
}

export function Sidebar({ onNewChat }: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const {
    conversations,
    currentConversationId,
    isLoadingConversations,
    error,
    selectConversation,
    renameConversation,
    archiveConversation,
  } =
    useChatStore();

  const handleLogout = () => {
    api.clearToken();
    router.push("/login");
  };

  const handleRename = async (id: string, currentTitle: string) => {
    const nextTitle = window.prompt(
      "Rename conversation",
      currentTitle || "Untitled"
    );
    if (nextTitle === null) return;

    try {
      await renameConversation(id, nextTitle);
    } catch (error) {
      window.alert(
        error instanceof Error ? error.message : "Failed to rename conversation"
      );
    }
  };

  const handleArchive = async (id: string, title: string) => {
    const confirmed = window.confirm(
      `Archive conversation "${title || "Untitled"}"?`
    );
    if (!confirmed) return;

    try {
      await archiveConversation(id);
    } catch (error) {
      window.alert(
        error instanceof Error
          ? error.message
          : "Failed to archive conversation"
      );
    }
  };

  const handleSelectConversation = async (id: string) => {
    await selectConversation(id);
    if (!pathname?.startsWith("/chat")) {
      router.push("/chat");
    }
  };

  return (
    <div className="w-[260px] bg-zinc-900 border-r border-zinc-800 flex flex-col shrink-0">
      {/* Header */}
      <div className="p-3 border-b border-zinc-800">
        <Button
          onClick={onNewChat}
          className="w-full bg-zinc-800 text-zinc-100 hover:bg-zinc-700 border border-zinc-700"
          variant="outline"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4 w-4 mr-2"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Chat
        </Button>
      </div>

      {/* Conversation list */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {conversations.length === 0 && (
            <p className="text-xs text-zinc-500 text-center py-4">
              {isLoadingConversations
                ? "Loading conversations..."
                : error
                  ? "Could not load conversations"
                  : "No conversations yet"}
            </p>
          )}
          {conversations.map((conv) => (
            <div
              key={conv.id}
              className={`group flex items-center gap-1 rounded-md text-sm transition-colors ${
                currentConversationId === conv.id
                  ? "bg-zinc-700 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              }`}
            >
              <button
                onClick={() => void handleSelectConversation(conv.id)}
                className="min-w-0 flex-1 px-3 py-2 text-left"
              >
                <span className="truncate block">{conv.title || "Untitled"}</span>
              </button>

              <div className="flex items-center pr-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    void handleRename(conv.id, conv.title || "Untitled");
                  }}
                  className="rounded p-1 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-100"
                  title="Rename conversation"
                  aria-label="Rename conversation"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-3.5 w-3.5"
                  >
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                  </svg>
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    void handleArchive(conv.id, conv.title || "Untitled");
                  }}
                  className="rounded p-1 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-100"
                  title="Archive conversation"
                  aria-label="Archive conversation"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-3.5 w-3.5"
                  >
                    <path d="M3 6h18" />
                    <path d="M8 6V4h8v2" />
                    <path d="M19 6l-1 14H6L5 6" />
                    <path d="M10 11v6" />
                    <path d="M14 11v6" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="p-3 border-t border-zinc-800">
        <Separator className="mb-2 bg-zinc-800" />
        <button
          onClick={() => router.push("/settings")}
          className={`mb-1 w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors ${
            pathname === "/settings"
              ? "bg-zinc-800 text-zinc-100"
              : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
          }`}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4 w-4"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1A2 2 0 1 1 4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1A2 2 0 1 1 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 .9-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1A2 2 0 1 1 19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5.9h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
          </svg>
          Settings
        </button>
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-md transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4 w-4"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Logout
        </button>
      </div>
    </div>
  );
}
