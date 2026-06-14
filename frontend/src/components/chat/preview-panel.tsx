"use client";

import { useEffect } from "react";
import Markdown from "react-markdown";

import { DiffView } from "@/components/chat/diff-view";
import { FileArtifactList } from "@/components/chat/file-artifact-list";
import { Message, ToolEvent } from "@/stores/chat-store";
import { useArtifactStore } from "@/stores/artifact-store";

type PanelTab = "preview" | "terminal" | "files" | "diff";

interface PreviewPanelProps {
  open: boolean;
  activeTab: PanelTab;
  onTabChange: (tab: PanelTab) => void;
  latestAssistantMessage?: Message;
  latestToolEvent?: ToolEvent;
  streamingContent?: string;
  conversationId?: string | null;
}

const TABS: Array<{ id: PanelTab; label: string }> = [
  { id: "preview", label: "Preview" },
  { id: "terminal", label: "Terminal" },
  { id: "files", label: "Files" },
  { id: "diff", label: "Diff" },
];

export function PreviewPanel({
  open,
  activeTab,
  onTabChange,
  latestAssistantMessage,
  latestToolEvent,
  streamingContent = "",
  conversationId = null,
}: PreviewPanelProps) {
  const { artifacts, selectedArtifactId, contentById, loadArtifactContent } =
    useArtifactStore();

  const assistantContent = streamingContent || latestAssistantMessage?.content || "";
  const conversationArtifacts = conversationId ? artifacts[conversationId] || [] : [];
  const selectedArtifactIdForConversation = conversationId
    ? selectedArtifactId[conversationId]
    : null;
  const selectedArtifact =
    conversationArtifacts.find(
      (artifact) => artifact.id === selectedArtifactIdForConversation
    ) ||
    conversationArtifacts.find((artifact) => artifact.has_content) ||
    null;
  const selectedArtifactContent = selectedArtifact
    ? contentById[selectedArtifact.id] || ""
    : "";
  const selectedArtifactContentLoaded = selectedArtifact
    ? Object.prototype.hasOwnProperty.call(contentById, selectedArtifact.id)
    : false;
  const previewMode = selectedArtifact?.preview?.mode || "";
  const canPreviewStoredContent =
    selectedArtifact?.state === "available" &&
    selectedArtifact.has_content &&
    selectedArtifact.preview?.allowed &&
    (previewMode === "code" || previewMode === "text");
  const canPreviewIframe =
    selectedArtifact?.state === "available" &&
    selectedArtifact.preview?.allowed &&
    previewMode === "iframe" &&
    Boolean(selectedArtifact.preview?.url);
  const terminalContent =
    latestToolEvent?.name === "code_as_action" ||
    latestToolEvent?.name === "shell_exec"
      ? latestToolEvent.result || latestToolEvent.error || ""
      : latestToolEvent?.result || latestToolEvent?.error || "";

  useEffect(() => {
    if (!selectedArtifact || !canPreviewStoredContent) return;
    void loadArtifactContent(selectedArtifact.id);
  }, [selectedArtifact, canPreviewStoredContent, loadArtifactContent]);

  if (!open) return null;

  return (
    <aside className="flex h-full w-[340px] shrink-0 flex-col border-l border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-3 py-2">
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                activeTab === tab.id
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4 text-sm text-zinc-300">
        {activeTab === "preview" && (
          selectedArtifact && selectedArtifact.state !== "available" ? (
            <EmptyState text={`Artifact is ${selectedArtifact.state}.`} />
          ) : canPreviewStoredContent && selectedArtifact ? (
            <ArtifactPreview
              path={selectedArtifact.path}
              content={selectedArtifactContent}
              isLoaded={selectedArtifactContentLoaded}
            />
          ) : canPreviewIframe && selectedArtifact?.preview?.url ? (
            <IframePreview
              path={selectedArtifact.path}
              url={selectedArtifact.preview.url}
            />
          ) : selectedArtifact && selectedArtifact.preview?.allowed === false ? (
            <EmptyState
              text={`Preview blocked: ${
                selectedArtifact.preview.reason || "not previewable"
              }.`}
            />
          ) : assistantContent ? (
            <div className="prose prose-invert prose-sm max-w-none">
              <Markdown>{assistantContent}</Markdown>
            </div>
          ) : (
            <EmptyState text="No preview content yet." />
          )
        )}

        {activeTab === "terminal" && (
          terminalContent ? (
            <pre className="overflow-x-auto rounded-lg bg-zinc-950 px-3 py-3 text-xs text-zinc-300">
              <AnsiText text={terminalContent} />
            </pre>
          ) : (
            <EmptyState text="No terminal output yet." />
          )
        )}

        {activeTab === "files" && (
          <FileArtifactList conversationId={conversationId} />
        )}

        {activeTab === "diff" && <DiffView conversationId={conversationId} />}
      </div>
    </aside>
  );
}

function ArtifactPreview({
  path,
  content,
  isLoaded,
}: {
  path: string;
  content: string;
  isLoaded: boolean;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950">
      <div className="border-b border-zinc-800 px-3 py-2">
        <p className="truncate text-xs font-medium text-zinc-200">{path}</p>
      </div>
      <pre className="max-h-[calc(100vh-160px)] overflow-auto px-3 py-3 text-xs leading-5 text-zinc-300">
        {isLoaded ? renderHighlightedCode(content, path) : "Loading content..."}
      </pre>
    </div>
  );
}

function IframePreview({ path, url }: { path: string; url: string }) {
  return (
    <div className="h-full rounded-lg border border-zinc-800 bg-zinc-950">
      <div className="border-b border-zinc-800 px-3 py-2">
        <p className="truncate text-xs font-medium text-zinc-200">{path}</p>
        <p className="mt-1 truncate text-[11px] text-zinc-500">{url}</p>
      </div>
      <iframe
        title={`Preview ${path}`}
        src={url}
        sandbox="allow-scripts allow-same-origin"
        className="h-[calc(100vh-170px)] w-full bg-white"
      />
    </div>
  );
}

function renderHighlightedCode(content: string, path: string) {
  const language = codeLanguage(path);
  return content.split("\n").map((line, index) => (
    <span key={`${index}-${line}`}>
      {highlightLine(line, language)}
      {"\n"}
    </span>
  ));
}

function highlightLine(line: string, language: string) {
  const trimmed = line.trimStart();
  if (
    trimmed.startsWith("#") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/*") ||
    trimmed.startsWith("*")
  ) {
    return <span className="text-zinc-500">{line}</span>;
  }

  const keywordPattern =
    language === "python"
      ? /\b(def|return|class|import|from|as|if|elif|else|for|while|try|except|with|async|await|True|False|None)\b/g
      : /\b(const|let|var|function|return|class|import|from|export|if|else|for|while|try|catch|async|await|true|false|null)\b/g;
  const stringPattern = /("[^"]*"|'[^']*'|`[^`]*`)/g;
  const parts = line.split(stringPattern);

  return parts.map((part, index) => {
    if (stringPattern.test(part)) {
      stringPattern.lastIndex = 0;
      return (
        <span key={`${index}-${part}`} className="text-emerald-300">
          {part}
        </span>
      );
    }
    stringPattern.lastIndex = 0;
    const keywordParts = part.split(keywordPattern);
    return keywordParts.map((keywordPart, keywordIndex) =>
      isKeyword(keywordPart, language) ? (
        <span
          key={`${index}-${keywordIndex}-${keywordPart}`}
          className="text-sky-300"
        >
          {keywordPart}
        </span>
      ) : (
        <span key={`${index}-${keywordIndex}-${keywordPart}`}>
          {keywordPart}
        </span>
      )
    );
  });
}

function isKeyword(value: string, language: string) {
  const pythonKeywords = new Set([
    "def",
    "return",
    "class",
    "import",
    "from",
    "as",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "try",
    "except",
    "with",
    "async",
    "await",
    "True",
    "False",
    "None",
  ]);
  const javascriptKeywords = new Set([
    "const",
    "let",
    "var",
    "function",
    "return",
    "class",
    "import",
    "from",
    "export",
    "if",
    "else",
    "for",
    "while",
    "try",
    "catch",
    "async",
    "await",
    "true",
    "false",
    "null",
  ]);
  return language === "python"
    ? pythonKeywords.has(value)
    : javascriptKeywords.has(value);
}

function codeLanguage(path: string) {
  if (path.endsWith(".py")) return "python";
  return "javascript";
}

function AnsiText({ text }: { text: string }) {
  return (
    <>
      {parseAnsi(text).map((segment, index) => (
        <span key={`${index}-${segment.text}`} className={segment.className}>
          {segment.text}
        </span>
      ))}
    </>
  );
}

function parseAnsi(text: string): Array<{ text: string; className: string }> {
  const segments: Array<{ text: string; className: string }> = [];
  const pattern = /\x1b\[([0-9;]*)m/g;
  let className = "text-zinc-300";
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      segments.push({ text: text.slice(cursor, match.index), className });
    }
    className = ansiClass(match[1], className);
    cursor = pattern.lastIndex;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), className });
  }
  return segments.length ? segments : [{ text, className }];
}

function ansiClass(code: string, current: string) {
  const codes = code.split(";").filter(Boolean);
  if (codes.length === 0 || codes.includes("0")) return "text-zinc-300";
  if (codes.includes("31")) return "text-red-300";
  if (codes.includes("32")) return "text-emerald-300";
  if (codes.includes("33")) return "text-amber-200";
  if (codes.includes("34")) return "text-sky-300";
  if (codes.includes("35")) return "text-fuchsia-300";
  if (codes.includes("36")) return "text-cyan-300";
  if (codes.includes("90")) return "text-zinc-500";
  return current;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center text-center text-sm text-zinc-500">
      <p>{text}</p>
    </div>
  );
}

export type { PanelTab };
