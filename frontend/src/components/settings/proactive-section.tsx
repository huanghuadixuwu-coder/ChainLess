"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ProactiveRun,
  ProactiveTask,
  usePlatformStore,
} from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
} from "@/components/settings/shared-state";

const textareaClass = `${inputClass} min-h-24 w-full rounded-lg border px-2.5 py-2 text-sm outline-none`;

const emptyTask = {
  cron_expr: "0 9 * * *",
  agent_id: "default",
  prompt: "",
  channel_type: "feishu",
};

export function ProactiveSection() {
  const {
    proactiveTasks,
    proactiveRuns,
    agents,
    createProactiveTask,
    deleteProactiveTask,
    isMutating,
  } = usePlatformStore();
  const [form, setForm] = useState(emptyTask);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await createProactiveTask(form);
    if (saved) {
      setForm(emptyTask);
    }
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Proactive"
        description="Schedule proactive agent tasks. Delivery secrets stay in channel settings."
      >
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <Field label="Cron">
            <Input
              className={inputClass}
              value={form.cron_expr}
              onChange={(event) =>
                setForm({ ...form, cron_expr: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Agent ID">
            <Input
              className={inputClass}
              value={form.agent_id}
              onChange={(event) =>
                setForm({ ...form, agent_id: event.target.value })
              }
              list="proactive-agent-options"
              required
            />
            <datalist id="proactive-agent-options">
              <option value="default" />
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </datalist>
          </Field>
          <Field label="Channel type">
            <Input
              className={inputClass}
              value={form.channel_type}
              onChange={(event) =>
                setForm({ ...form, channel_type: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Prompt">
            <textarea
              className={textareaClass}
              value={form.prompt}
              onChange={(event) =>
                setForm({ ...form, prompt: event.target.value })
              }
              required
            />
          </Field>
          <div className="md:col-span-2">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Save proactive task
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Scheduled tasks">
        {proactiveTasks.length === 0 ? (
          <EmptyState>No proactive tasks configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {proactiveTasks.map((task) => (
              <TaskRow
                key={task.task_id}
                task={task}
                onDelete={deleteProactiveTask}
                disabled={isMutating}
              />
            ))}
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Run history">
        {proactiveRuns.length === 0 ? (
          <EmptyState>No proactive run history yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {proactiveRuns.map((run, index) => (
              <RunRow key={`${run.task_id || "run"}-${index}`} run={run} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function TaskRow({
  task,
  onDelete,
  disabled,
}: {
  task: ProactiveTask;
  onDelete: (id: string) => Promise<void>;
  disabled: boolean;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium text-zinc-100">{task.task_id}</div>
          <div className="mt-1 text-xs text-zinc-500">
            {task.cron_expr} | agent: {task.agent_id} | channel:{" "}
            {task.channel_type}
          </div>
          <p className="mt-2 whitespace-pre-wrap text-zinc-300">
            {task.prompt}
          </p>
        </div>
        <Button
          type="button"
          variant="destructive"
          disabled={disabled}
          onClick={() => {
            if (window.confirm(`Delete proactive task "${task.task_id}"?`)) {
              void onDelete(task.task_id);
            }
          }}
        >
          Delete
        </Button>
      </div>
    </div>
  );
}

function RunRow({ run }: { run: ProactiveRun }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-zinc-100">
          {run.task_id || "unknown task"}
        </div>
        <span className="text-xs text-zinc-400">
          {run.status || "unknown"}
        </span>
      </div>
      <div className="mt-2 space-y-1 text-zinc-400">
        <div>Created: {run.created_at || "unknown"}</div>
        <div>Delivered: {String(run.delivered ?? false)}</div>
        <div>Tools: {(run.tool_calls || []).join(", ") || "none"}</div>
        {run.response_length !== undefined && (
          <div>Response length: {run.response_length}</div>
        )}
        {run.prompt && (
          <p className="whitespace-pre-wrap text-zinc-300">
            Prompt: {run.prompt}
          </p>
        )}
        {run.error && <div>Error: {run.error}</div>}
      </div>
    </div>
  );
}
