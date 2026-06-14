"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePlatformStore } from "@/stores/platform-store";
import { AgentsSection } from "@/components/settings/agents-section";
import { ChannelsSection } from "@/components/settings/channels-section";
import { EvalSection } from "@/components/settings/eval-section";
import { MemoriesSection } from "@/components/settings/memories-section";
import { ProactiveSection } from "@/components/settings/proactive-section";
import { ProvidersSection } from "@/components/settings/providers-section";
import { SkillsSection } from "@/components/settings/skills-section";
import { StatusLine, EmptyState } from "@/components/settings/shared-state";
import { SystemSection } from "@/components/settings/system-section";
import { ToolsSection } from "@/components/settings/tools-section";

type SectionKey =
  | "provider"
  | "agent"
  | "tools"
  | "memories"
  | "channel"
  | "proactive"
  | "skills"
  | "eval"
  | "system";

const readySections: Array<{ key: SectionKey; label: string }> = [
  { key: "provider", label: "Provider" },
  { key: "agent", label: "Agent" },
  { key: "tools", label: "Tools" },
  { key: "memories", label: "Memories" },
  { key: "channel", label: "Channel" },
  { key: "proactive", label: "Proactive" },
  { key: "skills", label: "Skills" },
  { key: "eval", label: "Eval" },
  { key: "system", label: "System" },
];

export function SettingsShell() {
  const [activeSection, setActiveSection] = useState<SectionKey>("provider");
  const { error, notice, isLoadingSettings, clearMessages } = usePlatformStore();

  const renderSection = () => {
    if (activeSection === "provider") return <ProvidersSection />;
    if (activeSection === "agent") return <AgentsSection />;
    if (activeSection === "tools") return <ToolsSection />;
    if (activeSection === "memories") return <MemoriesSection />;
    if (activeSection === "channel") return <ChannelsSection />;
    if (activeSection === "proactive") return <ProactiveSection />;
    if (activeSection === "skills") return <SkillsSection />;
    if (activeSection === "eval") return <EvalSection />;
    return <SystemSection />;
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col bg-zinc-950 text-zinc-100">
      <div className="border-b border-zinc-800 px-6 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Settings</h1>
            <p className="text-sm text-zinc-400">
              Admin controls for configured platform sections.
            </p>
          </div>
          {isLoadingSettings && (
            <span className="text-sm text-zinc-400">Loading settings...</span>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="w-48 shrink-0 border-r border-zinc-800 p-3">
          <div className="space-y-1">
            {readySections.map((section) => (
              <Button
                key={section.key}
                variant="ghost"
                onClick={() => {
                  clearMessages();
                  setActiveSection(section.key);
                }}
                className={`w-full justify-start ${
                  activeSection === section.key
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }`}
              >
                {section.label}
              </Button>
            ))}
          </div>
        </div>

        <ScrollArea className="min-w-0 flex-1">
          <div className="mx-auto max-w-5xl space-y-4 p-6">
            <StatusLine error={error} notice={notice} />
            {isLoadingSettings ? (
              <EmptyState>Loading section data...</EmptyState>
            ) : (
              renderSection()
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
