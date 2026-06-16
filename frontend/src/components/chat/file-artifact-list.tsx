"use client";

import { useEffect } from "react";

import { api } from "@/lib/api";
import { useArtifactStore } from "@/stores/artifact-store";
import type { Artifact } from "@/stores/artifact-store";

interface FileArtifactListProps {
  conversationId?: string | null;
}

export function FileArtifactList({ conversationId }: FileArtifactListProps) {
  const {
    artifacts,
    selectedArtifactId,
    contentById,
    isLoading,
    error,
    selectArtifact,
    loadArtifactContent,
  } = useArtifactStore();

  const items = conversationId ? artifacts[conversationId] || [] : [];
  const selectedId = conversationId
    ? selectedArtifactId[conversationId] || items[0]?.id || null
    : null;
  const selected = items.find((item) => item.id === selectedId) || null;
  const selectedContent = selectedId ? contentById[selectedId] : "";
  const hasSelectedContent = selectedId
    ? Object.prototype.hasOwnProperty.call(contentById, selectedId)
    : false;

  const handleDownload = async (artifact: Artifact) => {
    try {
      await api.downloadArtifact(artifact);
    } catch (err: unknown) {
      window.alert(
        err instanceof Error ? err.message : "Failed to download artifact"
      );
    }
  };

  useEffect(() => {
    if (!selected || !selected.has_content) return;
    void loadArtifactContent(selected.id);
  }, [selected, loadArtifactContent]);

  if (!conversationId) {
    return <EmptyState text="No conversation selected." />;
  }

  if (isLoading[conversationId] && items.length === 0) {
    return <EmptyState text="Loading file artifacts..." />;
  }

  if (items.length === 0) {
    return <EmptyState text="No file artifacts yet." />;
  }

  return (
    <div className="space-y-3" data-testid="artifact-file-list">
      <div className="space-y-2">
        {items.map((artifact) => (
          <div
            key={artifact.id}
            className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
              selectedId === artifact.id
                ? "border-zinc-600 bg-zinc-800 text-zinc-100"
                : "border-zinc-800 bg-zinc-950 text-zinc-300 hover:border-zinc-700 hover:bg-zinc-900"
            }`}
            data-testid="artifact-row"
          >
            <div className="flex items-start justify-between gap-3">
              <button
                type="button"
                onClick={() => {
                  selectArtifact(conversationId, artifact.id);
                  if (artifact.has_content) {
                    void loadArtifactContent(artifact.id);
                  }
                }}
                className="min-w-0 flex-1 text-left"
              >
                <p className="truncate text-xs font-medium">{artifact.path}</p>
                <p className="mt-1 text-[11px] text-zinc-500">
                  {artifact.operation} / {formatBytes(artifact.size_bytes)}
                </p>
              </button>
              <div className="flex shrink-0 items-center gap-2">
                {artifact.state === "available" && (
                  <button
                    type="button"
                    onClick={() => void handleDownload(artifact)}
                    className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                    aria-label={`Download ${artifact.path}`}
                  >
                    Download
                  </button>
                )}
                <ArtifactStateBadge artifact={artifact} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950">
          <div className="border-b border-zinc-800 px-3 py-2">
            <p className="truncate text-xs font-medium text-zinc-200">
              {selected.path}
            </p>
            <p className="mt-1 text-[11px] text-zinc-500">
              {selected.mime_type || "unknown"} / expires{" "}
              {selected.expires_at ? new Date(selected.expires_at).toLocaleDateString() : "later"}
            </p>
          </div>
          {selected.state !== "available" ? (
            <div className="px-3 py-3 text-xs text-zinc-500">
              Artifact state: {selected.state}
            </div>
          ) : selected.has_content ? (
            <pre
              data-testid="artifact-content"
              className="max-h-72 overflow-auto px-3 py-3 text-xs text-zinc-300"
            >
              {hasSelectedContent ? selectedContent : "Loading content..."}
            </pre>
          ) : (
            <div className="px-3 py-3 text-xs text-zinc-500">
              Content is not stored for this artifact.
            </div>
          )}
        </div>
      )}

      {error && <p className="text-xs text-red-200">{error}</p>}
    </div>
  );
}

function ArtifactStateBadge({ artifact }: { artifact: Artifact }) {
  const isAvailable = artifact.state === "available";
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
        isAvailable
          ? "bg-emerald-950/40 text-emerald-200"
          : "bg-zinc-800 text-zinc-400"
      }`}
    >
      {artifact.state}
    </span>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center text-center text-sm text-zinc-500">
      <p>{text}</p>
    </div>
  );
}
