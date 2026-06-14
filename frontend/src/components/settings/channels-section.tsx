"use client";

import { FormEvent, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ChannelConfiguration,
  usePlatformStore,
} from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SecretBadge,
  SettingsCard,
} from "@/components/settings/shared-state";

export function ChannelsSection() {
  const { channels } = usePlatformStore();
  const feishu = useMemo(
    () => channels.find((channel) => channel.channel_type === "feishu"),
    [channels]
  );

  const formKey = [
    feishu?.id || "new",
    feishu?.config?.label || "",
    String(feishu?.enabled ?? true),
  ].join(":");

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Feishu channel"
        description="Configure the Feishu delivery channel. Webhook and signing secret are write-only."
      >
        <FeishuForm key={formKey} feishu={feishu} />
      </SettingsCard>

      <SettingsCard title="Channel status">
        {!feishu ? (
          <EmptyState>Feishu is not configured yet.</EmptyState>
        ) : (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-zinc-100">
                {feishu.config?.label || "Feishu"}
              </span>
              <span className="text-zinc-400">
                {feishu.enabled ? "enabled" : "disabled"}
              </span>
            </div>
            <div className="mt-2 space-y-1 text-zinc-400">
              <div>
                Webhook: <SecretBadge value={feishu.secrets.webhook_url} />
              </div>
              <div>
                Signing secret: <SecretBadge value={feishu.secrets.secret} />
              </div>
            </div>
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function FeishuForm({ feishu }: { feishu?: ChannelConfiguration }) {
  const { configureFeishu, testFeishu, isMutating } = usePlatformStore();
  const [form, setForm] = useState({
    label: feishu?.config?.label || "",
    webhook_url: "",
    secret: "",
    enabled: feishu?.enabled ?? true,
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const saved = await configureFeishu({
      label: form.label,
      webhook_url: form.webhook_url,
      secret: form.secret,
      enabled: form.enabled,
    });
    if (saved) {
      setForm((current) => ({ ...current, webhook_url: "", secret: "" }));
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
      <Field label="Public label">
        <Input
          className={inputClass}
          value={form.label}
          onChange={(event) => setForm({ ...form, label: event.target.value })}
          placeholder="Ops notifications"
        />
      </Field>
      <label className="flex items-center gap-2 pt-5 text-sm text-zinc-300">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) =>
            setForm({ ...form, enabled: event.target.checked })
          }
        />
        Enabled
      </label>
      <Field label="Webhook URL">
        <Input
          className={inputClass}
          type="password"
          value={form.webhook_url}
          onChange={(event) =>
            setForm({ ...form, webhook_url: event.target.value })
          }
          placeholder={feishu ? "Leave blank to keep current webhook" : ""}
          required={!feishu}
        />
      </Field>
      <Field label="Signing secret">
        <Input
          className={inputClass}
          type="password"
          value={form.secret}
          onChange={(event) => setForm({ ...form, secret: event.target.value })}
          placeholder="Leave blank to keep or skip"
        />
      </Field>
      <div className="flex flex-wrap gap-2 md:col-span-2">
        <Button
          type="submit"
          disabled={isMutating}
          className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
        >
          Save Feishu
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={isMutating || !feishu}
          className="border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
          onClick={() => void testFeishu()}
        >
          Test Feishu
        </Button>
      </div>
    </form>
  );
}
