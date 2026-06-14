"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Agent, usePlatformStore } from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
} from "@/components/settings/shared-state";

const textareaClass = `${inputClass} min-h-24 w-full rounded-lg border px-2.5 py-2 text-sm outline-none`;

const emptyAgent = {
  name: "",
  system_prompt: "You are a helpful AI assistant.",
  llm_provider: "default",
  is_active: true,
};

export function AgentsSection() {
  const { agents, providers, createAgent, isMutating } = usePlatformStore();
  const [form, setForm] = useState(emptyAgent);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await createAgent(form);
    if (saved) {
      setForm(emptyAgent);
    }
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Agent"
        description="Create tenant agents and bind them to an LLM provider."
      >
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <Field label="Name">
            <Input
              className={inputClass}
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </Field>
          <Field label="LLM provider">
            <Input
              className={inputClass}
              value={form.llm_provider}
              onChange={(event) =>
                setForm({ ...form, llm_provider: event.target.value })
              }
              list="agent-provider-options"
              required
            />
            <datalist id="agent-provider-options">
              {providers.map((provider) => (
                <option key={provider.id} value={provider.name} />
              ))}
            </datalist>
          </Field>
          <Field label="System prompt">
            <textarea
              className={textareaClass}
              value={form.system_prompt}
              onChange={(event) =>
                setForm({ ...form, system_prompt: event.target.value })
              }
              required
            />
          </Field>
          <label className="flex items-center gap-2 pt-5 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(event) =>
                setForm({ ...form, is_active: event.target.checked })
              }
            />
            Active
          </label>
          <div className="md:col-span-2">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Save agent
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Configured agents">
        {agents.length === 0 ? (
          <EmptyState>No agents configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {agents.map((agent) => (
              <AgentRow key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function AgentRow({ agent }: { agent: Agent }) {
  const { providers, updateAgent, deleteAgent, isMutating } = usePlatformStore();
  const [form, setForm] = useState({
    name: agent.name,
    system_prompt: agent.system_prompt,
    llm_provider: agent.llm_provider,
    is_active: agent.is_active,
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await updateAgent(agent.id, form);
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-zinc-100">{agent.name}</div>
          <div className="text-xs text-zinc-500">
            Provider: {agent.llm_provider}
          </div>
        </div>
        <span className="text-xs text-zinc-400">
          {agent.is_active ? "active" : "inactive"}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name">
          <Input
            className={inputClass}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </Field>
        <Field label="LLM provider">
          <Input
            className={inputClass}
            value={form.llm_provider}
            onChange={(event) =>
              setForm({ ...form, llm_provider: event.target.value })
            }
            list={`agent-provider-options-${agent.id}`}
          />
          <datalist id={`agent-provider-options-${agent.id}`}>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.name} />
            ))}
          </datalist>
        </Field>
        <Field label="System prompt">
          <textarea
            className={textareaClass}
            value={form.system_prompt}
            onChange={(event) =>
              setForm({ ...form, system_prompt: event.target.value })
            }
          />
        </Field>
        <label className="flex items-center gap-2 pt-5 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(event) =>
              setForm({ ...form, is_active: event.target.checked })
            }
          />
          Active
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          type="submit"
          disabled={isMutating}
          className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
        >
          Update
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={isMutating}
          onClick={() => {
            if (window.confirm(`Delete agent "${agent.name}"?`)) {
              void deleteAgent(agent.id);
            }
          }}
        >
          Delete
        </Button>
      </div>
    </form>
  );
}
