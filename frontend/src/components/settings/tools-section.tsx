"use client";

import { FormEvent, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToolDefinition, usePlatformStore } from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
} from "@/components/settings/shared-state";

const textareaClass = `${inputClass} min-h-20 w-full rounded-lg border px-2.5 py-2 text-sm outline-none`;

const emptyMcp = {
  name: "",
  command: "",
  args: "",
  env: "",
};

const emptyTest = {
  serverName: "",
  toolName: "",
  args: "",
};

export function ToolsSection() {
  const {
    tools,
    registerMcpTool,
    testTool,
    deleteMcpServer,
    reportSettingsError,
    isMutating,
  } = usePlatformStore();
  const [mcpForm, setMcpForm] = useState(emptyMcp);
  const [testForm, setTestForm] = useState(emptyTest);

  const mcpServerNames = useMemo(() => {
    const names = new Set<string>();
    for (const tool of tools) {
      const name = tool.function?.name || "";
      const match = name.match(/^mcp__(.+?)__/);
      if (tool.tool_type === "mcp" && match?.[1]) {
        names.add(match[1]);
      }
    }
    return Array.from(names).sort();
  }, [tools]);

  const submitMcp = async (event: FormEvent) => {
    event.preventDefault();
    let env: Record<string, string> = {};
    if (mcpForm.env.trim()) {
      try {
        env = parseJsonObject(mcpForm.env) as Record<string, string>;
      } catch {
        reportSettingsError("MCP env must be valid JSON or empty.");
        return;
      }
    }

    const registered = await registerMcpTool({
      name: mcpForm.name,
      tool_type: "mcp",
      config: {
        command: mcpForm.command,
        args: splitArgs(mcpForm.args),
        env,
      },
    });
    if (registered) {
      setMcpForm(emptyMcp);
    }
  };

  const submitTest = async (event: FormEvent) => {
    event.preventDefault();
    let args: Record<string, unknown> = {};
    if (testForm.args.trim()) {
      try {
        args = parseJsonObject(testForm.args);
      } catch {
        reportSettingsError("Tool test args must be valid JSON or empty.");
        return;
      }
    }

    await testTool(testForm.serverName, {
      tool_name: testForm.toolName,
      args,
    });
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Tools"
        description="List builtin tools and register MCP servers. Env values are write-only."
      >
        <form onSubmit={submitMcp} className="grid gap-3 md:grid-cols-2">
          <Field label="MCP server name">
            <Input
              className={inputClass}
              value={mcpForm.name}
              onChange={(event) =>
                setMcpForm({ ...mcpForm, name: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Command">
            <Input
              className={inputClass}
              value={mcpForm.command}
              onChange={(event) =>
                setMcpForm({ ...mcpForm, command: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Args (comma or space separated)">
            <Input
              className={inputClass}
              value={mcpForm.args}
              onChange={(event) =>
                setMcpForm({ ...mcpForm, args: event.target.value })
              }
              placeholder="scripts/mcp_echo_server.py"
            />
          </Field>
          <Field label="Env JSON">
            <Input
              className={inputClass}
              type="password"
              value={mcpForm.env}
              onChange={(event) =>
                setMcpForm({ ...mcpForm, env: event.target.value })
              }
              placeholder='{"TOKEN":"..."} or empty'
            />
          </Field>
          <div className="md:col-span-2">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Register MCP server
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Tool tester">
        <form onSubmit={submitTest} className="grid gap-3 md:grid-cols-2">
          <Field label="MCP server name">
            <Input
              className={inputClass}
              value={testForm.serverName}
              onChange={(event) =>
                setTestForm({ ...testForm, serverName: event.target.value })
              }
              list="mcp-server-options"
              required
            />
            <datalist id="mcp-server-options">
              {mcpServerNames.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </Field>
          <Field label="Tool name">
            <Input
              className={inputClass}
              value={testForm.toolName}
              onChange={(event) =>
                setTestForm({ ...testForm, toolName: event.target.value })
              }
              list="mcp-tool-options"
              required
            />
            <datalist id="mcp-tool-options">
              {tools
                .filter((tool) => tool.tool_type === "mcp")
                .map((tool) => (
                  <option
                    key={tool.function?.name}
                    value={tool.function?.name || ""}
                  />
                ))}
            </datalist>
          </Field>
          <Field label="Args JSON">
            <textarea
              className={textareaClass}
              value={testForm.args}
              onChange={(event) =>
                setTestForm({ ...testForm, args: event.target.value })
              }
              placeholder='{"text":"hello"} or empty'
            />
          </Field>
          <div className="flex items-end">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Test tool
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Registered MCP servers">
        {mcpServerNames.length === 0 ? (
          <EmptyState>No MCP servers registered yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {mcpServerNames.map((name) => (
              <div
                key={name}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-zinc-100">{name}</div>
                    <div className="text-xs text-zinc-500">tool_type: mcp</div>
                  </div>
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={isMutating}
                    onClick={() => {
                      if (window.confirm(`Delete MCP server "${name}"?`)) {
                        void deleteMcpServer(name);
                      }
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Available tools">
        {tools.length === 0 ? (
          <EmptyState>No tools available.</EmptyState>
        ) : (
          <div className="space-y-3">
            {tools.map((tool, index) => (
              <ToolRow
                key={tool.function?.name || `tool-${index}`}
                tool={tool}
              />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function ToolRow({ tool }: { tool: ToolDefinition }) {
  const { configureTool, isMutating } = usePlatformStore();
  const name = tool.function?.name || "unnamed";
  const description = tool.function?.description || "No description provided.";
  const configuredRisk = tool.risk_override || "";

  return (
    <div
      data-testid="tool-row"
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-zinc-100">{name}</div>
        <div className="flex gap-2 text-xs text-zinc-300">
          <span className="rounded border border-zinc-700 px-2 py-1">
            {tool.tool_type}
          </span>
          <span className="rounded border border-zinc-700 px-2 py-1">
            {tool.risk}
          </span>
          <span className="rounded border border-zinc-700 px-2 py-1">
            {tool.enabled ? "enabled" : "disabled"}
          </span>
        </div>
      </div>
      <p className="mt-2 text-zinc-400">{description}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input
            type="checkbox"
            checked={tool.enabled}
            disabled={isMutating}
            onChange={(event) =>
              void configureTool(name, { enabled: event.target.checked })
            }
            className="h-4 w-4 rounded border-zinc-700 bg-zinc-900"
          />
          Available to agents
        </label>
        <label className="space-y-1 text-xs text-zinc-400">
          <span>Risk override</span>
          <select
            value={configuredRisk}
            disabled={isMutating}
            onChange={(event) =>
              void configureTool(name, {
                risk_override:
                  event.target.value === ""
                    ? null
                    : (event.target.value as "safe" | "risky" | "destructive"),
              })
            }
            className={`${inputClass} w-full rounded-lg border px-2.5 py-2 text-sm outline-none`}
          >
            <option value="">Use classifier ({tool.risk})</option>
            <option value="safe">safe</option>
            <option value="risky">risky</option>
            <option value="destructive">destructive</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function splitArgs(value: string) {
  return value
    .split(/[,\s]+/)
    .map((arg) => arg.trim())
    .filter(Boolean);
}

function parseJsonObject(value: string) {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Expected JSON object");
  }
  return parsed as Record<string, unknown>;
}
