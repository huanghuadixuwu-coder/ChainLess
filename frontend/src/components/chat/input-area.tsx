"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { AttachmentChip, AttachmentError } from "@/components/chat/file-attachment";
import { ToolPicker } from "@/components/chat/tool-picker";
import type { ToolOption, UploadedArtifact } from "@/lib/api";

interface InputAreaProps {
  onSend: (content: string, attachmentArtifactIds?: string[]) => void;
  onUploadFile: (file: File) => Promise<UploadedArtifact>;
  disabled?: boolean;
}

interface PendingAttachment {
  id: string;
  name: string;
  state: "uploading" | "available" | "failed";
}

export function InputArea({
  onSend,
  onUploadFile,
  disabled = false,
}: InputAreaProps) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [toolPickerActiveIndex, setToolPickerActiveIndex] = useState(0);
  const [toolPickerActiveOptionId, setToolPickerActiveOptionId] = useState<
    string | null
  >(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeToolRef = useRef<ToolOption | null>(null);

  useEffect(() => {
    if (!disabled && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [disabled]);

  const toolMention = getToolMention(value);
  const toolPickerOpen = !disabled && toolMention !== null;
  const hasBlockedAttachments = attachments.some(
    (attachment) => attachment.state === "uploading" || attachment.state === "failed"
  );

  const handleSend = () => {
    const trimmed = value.trim();
    if (
      (!trimmed && attachments.length === 0) ||
      disabled ||
      hasBlockedAttachments
    ) {
      return;
    }
    onSend(
      trimmed,
      attachments
        .filter((attachment) => attachment.state === "available")
        .map((attachment) => attachment.id)
    );
    setValue("");
    setAttachments([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
      return;
    }

    if (toolPickerOpen && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setToolPickerActiveIndex((index) => index + 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setToolPickerActiveIndex((index) => index - 1);
      } else if ((e.key === "Enter" || e.key === "Tab") && activeToolRef.current) {
        e.preventDefault();
        handleToolSelect(activeToolRef.current);
      }
    }
  };

  const handleFiles = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (!files.length || disabled) return;

    setAttachmentError(null);
    setIsUploading(true);
    try {
      for (const file of files) {
        const pendingId = createPendingAttachmentId();
        setAttachments((current) => [
          ...current,
          {
            id: pendingId,
            name: file.name,
            state: "uploading",
          },
        ]);
        try {
          const artifact = await onUploadFile(file);
          setAttachments((current) =>
            current.map((attachment) =>
              attachment.id === pendingId
                ? {
                    id: artifact.id,
                    name:
                      typeof artifact.path === "string" && artifact.path
                        ? artifact.path.split(/[\\/]/).pop() || file.name
                        : file.name,
                    state: "available",
                  }
                : attachment
            )
          );
        } catch (err: unknown) {
          setAttachmentError(
            err instanceof Error
              ? `${file.name}: ${err.message}`
              : `${file.name}: failed to upload attachment`
          );
          setAttachments((current) =>
            current.map((attachment) =>
              attachment.id === pendingId
                ? { ...attachment, state: "failed" }
                : attachment
            )
          );
        }
      }
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleToolSelect = (tool: ToolOption) => {
    if (toolMention === null) return;
    const before = value.slice(0, toolMention.start);
    const after = value.slice(toolMention.end);
    setValue(`${before}@${tool.name} ${after}`);
    setToolPickerActiveIndex(0);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className="border-t border-zinc-800 p-4 bg-zinc-900">
      <div
        className={`max-w-3xl mx-auto ${
          isDragOver ? "rounded-xl ring-1 ring-zinc-500" : ""
        }`}
        data-testid="file-dropzone"
        onDragOver={(event) => {
          if (disabled) return;
          event.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
          setIsDragOver(false);
        }}
        onDrop={(event) => {
          if (disabled) return;
          event.preventDefault();
          setIsDragOver(false);
          void handleFiles(event.dataTransfer.files);
        }}
      >
        {(attachments.length > 0 || attachmentError) && (
          <div className="mb-2 space-y-2">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {attachments.map((attachment) => (
                  <AttachmentChip
                    key={attachment.id}
                    name={attachment.name}
                    state={attachment.state}
                    onRemove={() =>
                      setAttachments((current) =>
                        current.filter((item) => item.id !== attachment.id)
                      )
                    }
                  />
                ))}
              </div>
            )}
            {attachmentError && (
              <AttachmentError
                message={attachmentError}
                onDismiss={() => setAttachmentError(null)}
              />
            )}
          </div>
        )}
        <div className="relative flex gap-2 items-end">
          <ToolPicker
            open={toolPickerOpen}
            query={toolMention?.query || ""}
            activeIndex={toolPickerActiveIndex}
            onActiveIndexChange={setToolPickerActiveIndex}
            onActiveToolChange={(tool) => {
              activeToolRef.current = tool;
            }}
            onActiveOptionIdChange={setToolPickerActiveOptionId}
            onSelect={handleToolSelect}
          />
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            aria-label="Attach files"
            onChange={(event) => {
              if (event.target.files) void handleFiles(event.target.files);
            }}
          />
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isUploading}
            size="icon"
            variant="ghost"
            className="h-10 w-10 shrink-0 border border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100"
            aria-label="Attach file"
            title="Attach file"
            data-testid="attach-file-button"
          >
            +
          </Button>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setToolPickerActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? "Waiting for response..." : "Type a message... (Ctrl+Enter to send)"}
            rows={1}
            disabled={disabled}
            aria-label="Chat input"
            aria-controls={toolPickerOpen ? "tool-picker-listbox" : undefined}
            aria-activedescendant={
              toolPickerOpen && toolPickerActiveOptionId
                ? toolPickerActiveOptionId
                : undefined
            }
            data-testid="chat-input"
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 resize-none focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-50"
            style={{ minHeight: "40px", maxHeight: "200px" }}
            onInput={(e) => {
              const target = e.currentTarget;
              target.style.height = "auto";
              target.style.height = Math.min(target.scrollHeight, 200) + "px";
            }}
          />
        <Button
          onClick={handleSend}
          disabled={
            disabled ||
            hasBlockedAttachments ||
            (!value.trim() && attachments.length === 0)
          }
          size="icon"
          className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300 h-10 w-10 shrink-0"
          aria-label="Send message"
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
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </Button>
        </div>
      </div>
    </div>
  );
}

function getToolMention(value: string) {
  const cursor = value.length;
  const prefix = value.slice(0, cursor);
  const match = /(^|\s)@([A-Za-z0-9_.-]*)$/.exec(prefix);
  if (!match || match.index < 0) return null;
  const start = match.index + match[1].length;
  return {
    start,
    end: cursor,
    query: match[2],
  };
}

function createPendingAttachmentId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `pending-${crypto.randomUUID()}`;
  }
  return `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
