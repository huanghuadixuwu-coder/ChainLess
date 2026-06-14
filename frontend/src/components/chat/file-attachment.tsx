"use client";

interface AttachmentChipProps {
  name: string;
  state?: string;
  onRemove: () => void;
}

interface AttachmentErrorProps {
  message: string;
  onDismiss: () => void;
}

export function AttachmentChip({
  name,
  state = "available",
  onRemove,
}: AttachmentChipProps) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-2 rounded-full border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs text-zinc-300"
      data-testid="attachment-chip"
    >
      <span className="truncate">{name}</span>
      <span className="text-zinc-500">{state}</span>
      <button
        type="button"
        onClick={onRemove}
        className="text-zinc-500 hover:text-zinc-100"
        aria-label={`Remove attachment ${name}`}
      >
        x
      </button>
    </span>
  );
}

export function AttachmentError({ message, onDismiss }: AttachmentErrorProps) {
  return (
    <div
      className="flex items-center justify-between gap-3 rounded-lg border border-red-950 bg-red-950/30 px-3 py-2 text-xs text-red-200"
      role="alert"
      data-testid="attachment-error"
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-red-200/70 hover:text-red-100"
        aria-label="Dismiss attachment error"
      >
        Dismiss
      </button>
    </div>
  );
}
