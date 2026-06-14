"use client";

import { useEffect } from "react";

import { useArtifactStore } from "@/stores/artifact-store";

interface DiffViewProps {
  conversationId?: string | null;
}

export function DiffView({ conversationId }: DiffViewProps) {
  const {
    artifacts,
    selectedArtifactId,
    diffById,
    isLoading,
    error,
    selectArtifact,
    loadArtifactDiff,
  } = useArtifactStore();

  const items = conversationId ? artifacts[conversationId] || [] : [];
  const selectedId = conversationId ? selectedArtifactId[conversationId] : null;
  const selected =
    items.find((item) => item.id === selectedId && item.has_diff) ||
    items.find((item) => item.has_diff) ||
    null;
  const diff = selected ? diffById[selected.id] : "";
  const hasDiff = selected
    ? Object.prototype.hasOwnProperty.call(diffById, selected.id)
    : false;

  useEffect(() => {
    if (!conversationId || !selected) return;
    selectArtifact(conversationId, selected.id);
    void loadArtifactDiff(selected.id);
  }, [conversationId, selected, selectArtifact, loadArtifactDiff]);

  if (!conversationId) {
    return <EmptyState text="No conversation selected." />;
  }

  if (isLoading[conversationId] && items.length === 0) {
    return <EmptyState text="Loading diff artifacts..." />;
  }

  if (!selected) {
    return <EmptyState text="No diff available yet." />;
  }

  return (
    <div className="space-y-3" data-testid="artifact-diff-panel">
      <div className="rounded-lg border border-zinc-800 bg-zinc-950">
        <div className="border-b border-zinc-800 px-3 py-2">
          <p className="truncate text-xs font-medium text-zinc-200">
            {selected.path}
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            unified diff / {selected.state}
          </p>
        </div>
        <pre
          data-testid="artifact-diff"
          className="max-h-[calc(100vh-180px)] overflow-auto px-3 py-3 text-xs leading-5"
        >
          {hasDiff ? renderDiff(diff) : "Loading diff..."}
        </pre>
      </div>
      {error && <p className="text-xs text-red-200">{error}</p>}
    </div>
  );
}

function renderDiff(diff: string) {
  return diff.split("\n").map((line, index) => {
    const key = `${index}-${line}`;
    const className = diffLineClass(line);
    return (
      <span key={key} className={className}>
        {line || " "}
        {"\n"}
      </span>
    );
  });
}

function diffLineClass(line: string) {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-sky-300";
  }
  if (line.startsWith("+")) {
    return "text-emerald-300";
  }
  if (line.startsWith("-")) {
    return "text-red-300";
  }
  if (line.startsWith("@@")) {
    return "text-amber-200";
  }
  return "text-zinc-400";
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center text-center text-sm text-zinc-500">
      <p>{text}</p>
    </div>
  );
}
