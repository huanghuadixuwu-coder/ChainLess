"use client";

import { useEffect, useMemo, useState } from "react";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNewChat: () => void;
}

const COMMANDS = [
  {
    id: "new-chat",
    label: "New conversation",
    hint: "Ctrl+N",
  },
];

export function CommandPalette({
  open,
  onOpenChange,
  onNewChat,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const filteredCommands = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return COMMANDS;
    return COMMANDS.filter((command) =>
      command.label.toLowerCase().includes(normalized)
    );
  }, [query]);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setQuery("");
        onOpenChange(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const runNewChat = () => {
    setQuery("");
    onOpenChange(false);
    onNewChat();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-zinc-950/70 px-4 pt-[18vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      data-testid="command-palette"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          setQuery("");
          onOpenChange(false);
        }
      }}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl">
        <div className="border-b border-zinc-800 px-3 py-3">
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && filteredCommands[0]) {
                event.preventDefault();
                runNewChat();
              }
            }}
            placeholder="Search commands..."
            aria-label="Search commands"
            className="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 outline-none"
          />
        </div>
        <div className="max-h-72 overflow-auto p-2">
          {filteredCommands.length ? (
            filteredCommands.map((command) => (
              <button
                key={command.id}
                type="button"
                onClick={runNewChat}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-zinc-200 hover:bg-zinc-800"
              >
                <span>{command.label}</span>
                <kbd className="rounded border border-zinc-700 px-1.5 py-0.5 text-[11px] text-zinc-500">
                  {command.hint}
                </kbd>
              </button>
            ))
          ) : (
            <p className="px-3 py-4 text-sm text-zinc-500">No commands found.</p>
          )}
        </div>
      </div>
    </div>
  );
}
