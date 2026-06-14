"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePlatformStore, Skill } from "@/stores/platform-store";
import {
  EmptyState,
  Field,
  inputClass,
  SettingsCard,
  splitTerms,
} from "@/components/settings/shared-state";

const emptySkill = {
  name: "",
  description: "",
  trigger_terms: "",
  enabled: true,
};

export function SkillsSection() {
  const { skills, skillMatches, createSkill, matchSkills, isMutating } =
    usePlatformStore();
  const [form, setForm] = useState(emptySkill);
  const [matchText, setMatchText] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await createSkill({
      name: form.name,
      description: form.description || null,
      trigger_terms: splitTerms(form.trigger_terms),
      enabled: form.enabled,
    });
    setForm(emptySkill);
  };

  return (
    <div className="space-y-4">
      <SettingsCard
        title="Skills"
        description="Manage passive skill metadata and trigger terms."
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
          <Field label="Description">
            <Input
              className={inputClass}
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
            />
          </Field>
          <Field label="Trigger terms (comma-separated)">
            <Input
              className={inputClass}
              value={form.trigger_terms}
              onChange={(event) =>
                setForm({ ...form, trigger_terms: event.target.value })
              }
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
          <div className="md:col-span-2">
            <Button
              type="submit"
              disabled={isMutating}
              className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            >
              Save skill
            </Button>
          </div>
        </form>
      </SettingsCard>

      <SettingsCard title="Trigger match tester">
        <div className="flex gap-2">
          <Input
            className={inputClass}
            value={matchText}
            onChange={(event) => setMatchText(event.target.value)}
            placeholder="Paste text to match against enabled skill triggers"
          />
          <Button
            disabled={isMutating || !matchText.trim()}
            className="bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
            onClick={() => void matchSkills(matchText)}
          >
            Test
          </Button>
        </div>
        <div className="mt-3 space-y-2">
          {skillMatches.length === 0 ? (
            <EmptyState>No trigger matches to show.</EmptyState>
          ) : (
            skillMatches.map((match) => (
              <div
                key={match.skill.id}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm"
              >
                <div className="font-medium text-zinc-100">
                  {match.skill.name}
                </div>
                <div className="text-zinc-400">
                  Matched: {match.matched_terms.join(", ")}
                </div>
              </div>
            ))
          )}
        </div>
      </SettingsCard>

      <SettingsCard title="Configured skills">
        {skills.length === 0 ? (
          <EmptyState>No skills configured yet.</EmptyState>
        ) : (
          <div className="space-y-3">
            {skills.map((skill) => (
              <SkillRow key={skill.id} skill={skill} />
            ))}
          </div>
        )}
      </SettingsCard>
    </div>
  );
}

function SkillRow({ skill }: { skill: Skill }) {
  const { updateSkill, deleteSkill, isMutating } = usePlatformStore();
  const [form, setForm] = useState({
    name: skill.name,
    description: skill.description || "",
    trigger_terms: skill.trigger_terms.join(", "),
    enabled: skill.enabled,
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await updateSkill(skill.id, {
      name: form.name,
      description: form.description || null,
      trigger_terms: splitTerms(form.trigger_terms),
      enabled: form.enabled,
    });
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="font-medium text-zinc-100">{skill.name}</div>
        <span className="text-xs text-zinc-400">
          {skill.enabled ? "enabled" : "disabled"}
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
        <Field label="Description">
          <Input
            className={inputClass}
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
          />
        </Field>
        <Field label="Trigger terms">
          <Input
            className={inputClass}
            value={form.trigger_terms}
            onChange={(event) =>
              setForm({ ...form, trigger_terms: event.target.value })
            }
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
          onClick={() => void deleteSkill(skill.id)}
        >
          Delete
        </Button>
      </div>
    </form>
  );
}
