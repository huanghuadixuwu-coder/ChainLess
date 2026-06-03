"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useChatStore } from "@/stores/chat-store";
import { Sidebar } from "@/components/layout/sidebar";
import { ChatPanel } from "@/components/chat/chat-panel";
import { InputArea } from "@/components/chat/input-area";
import { Button } from "@/components/ui/button";

export default function ChatPage() {
  const router = useRouter();
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const { currentConversationId, loadConversations, createConversation, selectConversation, sendMessage, isStreaming } = useChatStore();

  useEffect(() => {
    const token = api.getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    loadConversations();
  }, [router, loadConversations]);

  const handleNewChat = async () => {
    try {
      const id = await createConversation();
      await selectConversation(id);
    } catch {
      // Error already handled in store
    }
  };

  const handleSend = async (content: string) => {
    if (!currentConversationId) {
      const id = await createConversation();
      await selectConversation(id);
    }
    await sendMessage(content);
  };

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Left sidebar */}
      <Sidebar onNewChat={handleNewChat} />

      {/* Center chat panel */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel />
        <InputArea onSend={handleSend} disabled={isStreaming} />
      </div>

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
