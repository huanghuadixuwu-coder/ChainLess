"use client";

import { useChatStore, Message } from "@/stores/chat-store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "@/components/chat/message-bubble";
import { useEffect, useRef } from "react";

export function ChatPanel() {
  const { currentConversationId, messages, isStreaming, streamingContent } =
    useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  const conversationMessages = currentConversationId
    ? messages[currentConversationId] || []
    : [];

  const allMessages = isStreaming
    ? [
        ...conversationMessages,
        {
          id: "streaming",
          role: "assistant" as const,
          content: streamingContent,
          created_at: new Date().toISOString(),
        },
      ]
    : conversationMessages;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allMessages.length, streamingContent]);

  if (!currentConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950 text-zinc-500">
        <div className="text-center">
          <p className="text-lg mb-2">No conversation selected</p>
          <p className="text-sm">
            Click &quot;New Chat&quot; in the sidebar to start
          </p>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 p-4">
      <div className="max-w-3xl mx-auto space-y-4">
        {allMessages.map((msg: Message) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isStreaming && !streamingContent && (
          <div className="flex justify-start">
            <div className="bg-zinc-800 text-zinc-300 rounded-lg px-4 py-2 rounded-bl-none">
              <span className="inline-block w-2 h-4 bg-zinc-400 animate-pulse" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
