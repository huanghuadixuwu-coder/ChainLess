"use client";

import React, { useState } from "react";
import { Message } from "@/stores/chat-store";
import Markdown from "react-markdown";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isTool = message.role === "tool";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? "bg-zinc-700 text-zinc-100 rounded-br-none"
            : isTool
              ? "bg-zinc-900 border border-zinc-800 text-zinc-300 rounded-bl-none"
              : "bg-zinc-800 text-zinc-300 rounded-bl-none"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : isTool ? (
          <pre className="whitespace-pre-wrap text-xs text-zinc-300">
            {message.content}
          </pre>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none">
            <Markdown
              components={{
                pre: MarkdownPre,
              }}
            >
              {message.content}
            </Markdown>
          </div>
        )}
      </div>
    </div>
  );
}

function MarkdownPre(props: React.ComponentProps<"pre">) {
  const child = React.Children.toArray(props.children)[0];
  if (!React.isValidElement<React.ComponentProps<"code">>(child)) {
    return <pre {...props} />;
  }

  const className = child.props.className || "";
  const language = /language-([A-Za-z0-9_-]+)/.exec(className)?.[1] || "code";
  const code = String(child.props.children || "").replace(/\n$/, "");

  return <CodeBlock code={code} language={language} />;
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [isFolded, setIsFolded] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="not-prose my-3 overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <span className="text-xs text-zinc-500">{language}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsFolded((value) => !value)}
            className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label={isFolded ? "Expand code block" : "Fold code block"}
            data-testid="code-fold-button"
          >
            {isFolded ? "Expand" : "Fold"}
          </button>
          <button
            type="button"
            onClick={() => void copyCode()}
            className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="Copy code block"
            data-testid="code-copy-button"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      {!isFolded && (
        <pre className="m-0 overflow-x-auto p-3 text-xs leading-5 text-zinc-300">
          <code className={`language-${language}`}>
            {highlightCode(code, language)}
          </code>
        </pre>
      )}
    </div>
  );
}

function highlightCode(code: string, language: string) {
  const keywords = keywordPatternFor(language);
  const tokenPattern = new RegExp(
    [
      "(#.*$|//.*$)",
      "(`[^`]*`|\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*')",
      "(\\b\\d+(?:\\.\\d+)?\\b)",
      keywords ? `(${keywords})` : "",
    ]
      .filter(Boolean)
      .join("|"),
    "gm"
  );
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(code)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(code.slice(lastIndex, match.index));
    }
    const token = match[0];
    const className = token.startsWith("#") || token.startsWith("//")
      ? "text-zinc-500"
      : /^["'`]/.test(token)
        ? "text-emerald-300"
        : /^\d/.test(token)
          ? "text-amber-300"
          : "text-sky-300";
    nodes.push(
      <span key={`${match.index}-${token}`} className={className}>
        {token}
      </span>
    );
    lastIndex = tokenPattern.lastIndex;
  }

  if (lastIndex < code.length) {
    nodes.push(code.slice(lastIndex));
  }
  return nodes.length ? nodes : code;
}

function keywordPatternFor(language: string) {
  const normalized = language.toLowerCase();
  if (["py", "python"].includes(normalized)) {
    return "\\b(?:async|await|class|def|elif|else|except|finally|for|from|if|import|in|lambda|None|pass|return|True|False|try|while|with|yield|print)\\b";
  }
  if (["js", "jsx", "ts", "tsx", "javascript", "typescript"].includes(normalized)) {
    return "\\b(?:async|await|break|case|catch|class|const|continue|default|else|export|for|from|function|if|import|let|new|null|return|switch|throw|true|false|try|type|undefined|while)\\b";
  }
  if (["json"].includes(normalized)) {
    return "\\b(?:true|false|null)\\b";
  }
  if (["bash", "sh", "shell"].includes(normalized)) {
    return "\\b(?:case|do|done|elif|else|esac|fi|for|function|if|in|then|while)\\b";
  }
  return "";
}
