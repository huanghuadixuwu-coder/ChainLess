"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePlatformStore, LlmProvider } from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SecretBadge,
  SettingsCard,
} from "@/components/settings/shared-state";

const emptyCreate = {
  name: "",
  api_base: "",
  api_key: "",
  model: "",
  embedding_model: "embedding-3",
  is_default: false,
};

export function ProvidersSection() {
  const { providers, createProvider, isMutating } = usePlatformStore();
  const [form, setForm] = useState(emptyCreate);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await createProvider({
      ...form,
      embedding_model: form.embedding_model || null,
    });
    if (saved) {
      setForm(emptyCreate);
    }
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Provider"
        description="Create a tenant LLM provider. API key is write-only and never rendered back."
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
          <Field label="API base">
            <Input
              className={inputClass}
              value={form.api_base}
              onChange={(event) =>
                setForm({ ...form, api_base: event.target.value })
              }
              required
            />
          </Field>
          <Field label="Model">
            <Input
              className={inputClass}
              value={form.model}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
              required
            />
          </Field>
          <Field label="Embedding model">
            <Input
              className={inputClass}
              value={form.embedding_model}
              onChange={(event) =>
                setForm({ ...form, embedding_model: event.target.value })
              }
            />
          </Field>
          <Field label="API key">
            <Input
              className={inputClass}
              type="password"
              value={form.api_key}
              onChange={(event) =>
                setForm({ ...form, api_key: event.target.value })
              }
              required
            />
          </Field>
          <label className="flex items-center gap-2 pt-5 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(event) =>
                setForm({ ...form, is_default: event.target.checked })
              }
            />
            Set as default
          </label>
          <div className="md:col-span-2">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Save provider
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Configured providers">
        {providers.length === 0 ? (
          <EmptyState>No providers configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {providers.map((provider) => (
              <ProviderRow key={provider.id} provider={provider} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function ProviderRow({ provider }: { provider: LlmProvider }) {
  const {
    updateProvider,
    testProvider,
    setDefaultProvider,
    deleteProvider,
    isMutating,
  } = usePlatformStore();
  const [form, setForm] = useState({
    api_base: provider.api_base,
    model: provider.model,
    embedding_model: provider.embedding_model || "",
    api_key: "",
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await updateProvider(provider.name, {
      api_base: form.api_base,
      model: form.model,
      embedding_model: form.embedding_model || null,
      ...(form.api_key ? { api_key: form.api_key } : {}),
    });
    if (saved) {
      setForm((current) => ({ ...current, api_key: "" }));
    }
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-zinc-100">{provider.name}</div>
          <div className="text-xs text-zinc-500">
            API key: <SecretBadge value={provider.api_key} />
          </div>
        </div>
        <span className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300">
          {provider.is_default ? "default" : "available"}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="API base">
          <Input
            className={inputClass}
            value={form.api_base}
            onChange={(event) =>
              setForm({ ...form, api_base: event.target.value })
            }
          />
        </Field>
        <Field label="Model">
          <Input
            className={inputClass}
            value={form.model}
            onChange={(event) => setForm({ ...form, model: event.target.value })}
          />
        </Field>
        <Field label="Embedding model">
          <Input
            className={inputClass}
            value={form.embedding_model}
            onChange={(event) =>
              setForm({ ...form, embedding_model: event.target.value })
            }
          />
        </Field>
        <Field label="Replace API key">
          <Input
            className={inputClass}
            type="password"
            value={form.api_key}
            onChange={(event) =>
              setForm({ ...form, api_key: event.target.value })
            }
            placeholder="Leave blank to keep current key"
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
          variant="outline"
          disabled={isMutating}
          className="border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
          onClick={() => void testProvider(provider.name)}
        >
          Test
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={isMutating || provider.is_default}
          className="border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
          onClick={() => void setDefaultProvider(provider.name)}
        >
          Make default
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={isMutating}
          onClick={() => void deleteProvider(provider.name)}
        >
          Delete
        </Button>
      </div>
    </form>
  );
}
