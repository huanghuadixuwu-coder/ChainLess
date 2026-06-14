"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Memory, usePlatformStore } from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
  splitTerms,
} from "@/components/settings/shared-state";

const textareaClass = `${inputClass} min-h-24 w-full rounded-lg border px-2.5 py-2 text-sm outline-none`;

const emptyMemory = {
  type: "user",
  name: "",
  content: "",
  description: "",
  tags: "",
};

export function MemoriesSection() {
  const {
    memories,
    memorySearchResults,
    memoryMergeResult,
    createMemory,
    searchMemories,
    mergeMemories,
    isMutating,
  } = usePlatformStore();
  const [form, setForm] = useState(emptyMemory);
  const [searchText, setSearchText] = useState("");
  const [mergeTask, setMergeTask] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await createMemory({
      type: form.type,
      name: form.name,
      content: form.content,
      description: form.description || null,
      tags: splitTerms(form.tags),
    });
    if (saved) {
      setForm(emptyMemory);
    }
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Memories"
        description="Manage tenant memory content used for contextual recall."
      >
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <Field label="Type">
            <Input
              className={inputClass}
              value={form.type}
              onChange={(event) =>
                setForm({ ...form, type: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Name">
            <Input
              className={inputClass}
              value={form.name}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Description">
            <Input
              className={inputClass}
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
            />
          </Field>
          <Field label="Tags (comma-separated)">
            <Input
              className={inputClass}
              value={form.tags}
              onChange={(event) =>
                setForm({ ...form, tags: event.target.value })
              }
            />
          </Field>
          <Field label="Content">
            <textarea
              className={textareaClass}
              value={form.content}
              onChange={(event) =>
                setForm({ ...form, content: event.target.value })
              }
              required
            />
          </Field>
          <div className="flex items-end">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Save memory
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Search memories">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void searchMemories(searchText);
          }}
          className="space-y-3"
        >
          <div className="flex gap-2">
            <Input
              className={inputClass}
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="Search memory content or tags"
            />
            <Button
              type="submit"
              disabled={isMutating || !searchText.trim()}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Search
            </Button>
          </div>
          {memorySearchResults.length === 0 ? (
            <EmptyState>No memory search results to show.</EmptyState>
          ) : (
            <div className="space-y-3">
              {memorySearchResults.map((memory) => (
                <MemorySummary key={memory.id} memory={memory} />
              ))}
            </div>
          )}
        </form>
      </SettingsCard>

      <SettingsCard title="Merge context">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void mergeMemories(mergeTask);
          }}
          className="space-y-3"
        >
          <Field label="Task">
            <textarea
              className={textareaClass}
              value={mergeTask}
              onChange={(event) => setMergeTask(event.target.value)}
              placeholder="Describe the task to merge relevant memories"
            />
          </Field>
          <Button
            type="submit"
            disabled={isMutating || !mergeTask.trim()}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
          >
            Merge
          </Button>
          {!memoryMergeResult ? (
            <EmptyState>No merged context to show.</EmptyState>
          ) : (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
              <div className="mb-2 text-xs text-zinc-400">
                Memories: {memoryMergeResult.memories.length} | Instructions:{" "}
                {memoryMergeResult.has_instructions ? "yes" : "no"}
              </div>
              <pre className="whitespace-pre-wrap text-zinc-300">
                {memoryMergeResult.context || "No context returned."}
              </pre>
            </div>
          )}
        </form>
      </SettingsCard>

      <SettingsCard title="Configured memories">
        {memories.length === 0 ? (
          <EmptyState>No memories configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {memories.map((memory) => (
              <MemoryRow key={memory.id} memory={memory} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function MemoryRow({ memory }: { memory: Memory }) {
  const { updateMemory, deleteMemory, isMutating } = usePlatformStore();
  const [form, setForm] = useState({
    name: memory.name,
    content: memory.content || "",
    description: memory.description || "",
    tags: (memory.tags || []).join(", "),
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await updateMemory(memory.id, {
      name: form.name,
      content: form.content,
      description: form.description,
      tags: splitTerms(form.tags),
    });
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-zinc-100">{memory.name}</div>
          <div className="text-xs text-zinc-500">
            {memory.type} | {(memory.tags || []).join(", ") || "no tags"}
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name">
          <Input
            className={inputClass}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </Field>
        <Field label="Description">
          <Input
            className={inputClass}
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
          />
        </Field>
        <Field label="Tags">
          <Input
            className={inputClass}
            value={form.tags}
            onChange={(event) => setForm({ ...form, tags: event.target.value })}
          />
        </Field>
        <Field label="Content">
          <textarea
            className={textareaClass}
            value={form.content}
            onChange={(event) =>
              setForm({ ...form, content: event.target.value })
            }
          />
        </Field>
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
            if (window.confirm(`Delete memory "${memory.name}"?`)) {
              void deleteMemory(memory.id);
            }
          }}
        >
          Delete
        </Button>
      </div>
    </form>
  );
}

function MemorySummary({ memory }: { memory: Memory }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <div className="font-medium text-zinc-100">{memory.name}</div>
      <div className="text-xs text-zinc-500">
        {memory.type} | {(memory.tags || []).join(", ") || "no tags"}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-zinc-300">
        {memory.content || ""}
      </p>
    </div>
  );
}
