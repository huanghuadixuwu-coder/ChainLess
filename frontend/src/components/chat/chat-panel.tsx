"use client";

import {
  useChatStore,
  Message,
  ToolEvent,
} from "@/stores/chat-store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "@/components/chat/message-bubble";
import { ToolActivityRow } from "@/components/chat/tool-activity-row";
import { ConfirmCard } from "@/components/chat/confirm-card";
import { ContextBanner } from "@/components/chat/context-banner";
import { useEffect, useMemo, useRef, useState } from "react";

const VIRTUALIZATION_THRESHOLD = 30;
const ESTIMATED_MESSAGE_HEIGHT = 112;
const MESSAGE_GAP = 16;
const OVERSCAN_PX = 480;
const EMPTY_MESSAGES: Message[] = [];
const EMPTY_TOOL_EVENTS: ToolEvent[] = [];

export function ChatPanel() {
  const {
    currentConversationId,
    messages,
    toolEvents,
    pendingConfirmations,
    contextSummaries,
    isLoadingConversations,
    error,
    isStreaming,
    streamingContent,
    respondToConfirmation,
  } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [measuredHeights, setMeasuredHeights] = useState<Record<string, number>>({});
  const [viewportMetrics, setViewportMetrics] = useState({
    scrollTop: 0,
    height: 0,
  });

  const conversationMessages = currentConversationId
    ? messages[currentConversationId] || EMPTY_MESSAGES
    : EMPTY_MESSAGES;
  const conversationToolEvents = currentConversationId
    ? toolEvents[currentConversationId] || EMPTY_TOOL_EVENTS
    : EMPTY_TOOL_EVENTS;
  const pendingConfirmation = currentConversationId
    ? pendingConfirmations[currentConversationId]
    : null;
  const contextSummary = currentConversationId
    ? contextSummaries[currentConversationId]
    : null;

  const allMessages = useMemo(
    () =>
      isStreaming
        ? [
            ...conversationMessages,
            {
              id: "streaming",
              role: "assistant" as const,
              content: streamingContent,
              created_at: new Date().toISOString(),
            },
          ]
        : conversationMessages,
    [conversationMessages, isStreaming, streamingContent]
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allMessages.length, streamingContent]);

  useEffect(() => {
    const updateViewportMetrics = () => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      setViewportMetrics({
        scrollTop: viewport.scrollTop,
        height: viewport.clientHeight,
      });
    };

    updateViewportMetrics();
    window.addEventListener("resize", updateViewportMetrics);
    return () => window.removeEventListener("resize", updateViewportMetrics);
  }, [currentConversationId, allMessages.length]);

  useEffect(() => {
    if (!pendingConfirmation || isStreaming) {
      return;
    }

    const receivedAt = new Date(pendingConfirmation.received_at).getTime();
    const expiresAt = receivedAt + pendingConfirmation.timeout_s * 1000;
    const remaining = expiresAt - Date.now();

    if (remaining <= 0) {
      void respondToConfirmation(false, { timedOut: true });
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void respondToConfirmation(false, { timedOut: true });
    }, remaining);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [pendingConfirmation, isStreaming, respondToConfirmation]);

  const shouldVirtualizeMessages =
    allMessages.length > VIRTUALIZATION_THRESHOLD;
  const messageLayout = useMemo(() => {
    let offset = 0;
    const offsets: number[] = [];
    const heights: number[] = [];

    for (const message of allMessages) {
      offsets.push(offset);
      const height = measuredHeights[message.id] ?? ESTIMATED_MESSAGE_HEIGHT;
      heights.push(height);
      offset += height;
    }

    return { offsets, heights, totalHeight: offset };
  }, [allMessages, measuredHeights]);

  const visibleRange = useMemo(() => {
    if (!shouldVirtualizeMessages) {
      return { start: 0, end: allMessages.length };
    }

    const top = Math.max(0, viewportMetrics.scrollTop - OVERSCAN_PX);
    const bottom =
      viewportMetrics.scrollTop +
      (viewportMetrics.height || ESTIMATED_MESSAGE_HEIGHT * 8) +
      OVERSCAN_PX;
    let start = 0;
    while (
      start < allMessages.length &&
      messageLayout.offsets[start] + messageLayout.heights[start] < top
    ) {
      start += 1;
    }

    let end = start;
    while (end < allMessages.length && messageLayout.offsets[end] <= bottom) {
      end += 1;
    }

    return {
      start: Math.max(0, start),
      end: Math.min(allMessages.length, Math.max(end, start + 1)),
    };
  }, [allMessages.length, messageLayout, shouldVirtualizeMessages, viewportMetrics]);

  const measureMessageRow = (id: string, node: HTMLDivElement | null) => {
    if (!node || !shouldVirtualizeMessages) return;
    const nextHeight =
      Math.ceil(node.getBoundingClientRect().height) + MESSAGE_GAP;
    setMeasuredHeights((current) => {
      const previousHeight = current[id];
      if (Math.abs((previousHeight || 0) - nextHeight) <= 1) return current;
      return { ...current, [id]: nextHeight };
    });
  };

  const visibleMessages = allMessages.slice(visibleRange.start, visibleRange.end);

  if (isLoadingConversations) {
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950 text-zinc-500">
        <div className="text-center">
          <p className="text-lg mb-2">Loading conversations...</p>
          <p className="text-sm">Restoring your workspace</p>
        </div>
      </div>
    );
  }

  if (!currentConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950 text-zinc-500">
        <div className="text-center">
          <p className="text-lg mb-2">
            {error ? "Conversation unavailable" : "No conversation selected"}
          </p>
          <p className="text-sm">
            {error
              ? "Check the connection or start a new chat"
              : "Click \"New Chat\" in the sidebar to start"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea
      className="flex-1 min-h-0 overflow-hidden p-4"
      viewportRef={viewportRef}
      viewportTestId="chat-scroll-viewport"
      onViewportScroll={(event) => {
        setViewportMetrics({
          scrollTop: event.currentTarget.scrollTop,
          height: event.currentTarget.clientHeight,
        });
      }}
    >
      <div
        className="max-w-3xl mx-auto space-y-4"
        data-testid="virtual-message-window"
        data-total-messages={allMessages.length}
        data-rendered-messages={
          shouldVirtualizeMessages ? visibleMessages.length : allMessages.length
        }
      >
        <ContextBanner summary={contextSummary} />
        {shouldVirtualizeMessages ? (
          <div
            className="relative"
            data-testid="virtualized-message-list"
            style={{ height: Math.max(messageLayout.totalHeight - MESSAGE_GAP, 0) }}
          >
            {visibleMessages.map((msg: Message, localIndex) => {
              const index = visibleRange.start + localIndex;
              return (
                <div
                  key={msg.id}
                  ref={(node) => measureMessageRow(msg.id, node)}
                  data-testid="message-row"
                  className="absolute left-0 right-0"
                  style={{ top: messageLayout.offsets[index] }}
                >
                  <MessageBubble message={msg} />
                </div>
              );
            })}
          </div>
        ) : (
          allMessages.map((msg: Message) => (
            <div key={msg.id} data-testid="message-row">
              <MessageBubble message={msg} />
            </div>
          ))
        )}
        {conversationToolEvents.map((event: ToolEvent) => (
          <div key={event.id}>
            <ToolActivityRow event={event} />
          </div>
        ))}
        {pendingConfirmation && (
          <ConfirmCard
            confirmation={pendingConfirmation}
            busy={isStreaming}
            onApprove={() => void respondToConfirmation(true)}
            onDeny={() => void respondToConfirmation(false)}
          />
        )}
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
