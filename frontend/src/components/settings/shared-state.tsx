"use client";

import { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SecretMetadata } from "@/stores/platform-store";

export function SettingsCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card className="bg-zinc-900 border-zinc-800 text-zinc-100">
      <CardHeader>
        <CardTitle className="text-zinc-100">{title}</CardTitle>
        {description && <p className="text-sm text-zinc-400">{description}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-zinc-400">{label}</span>
      {children}
    </label>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-sm text-zinc-400">
      {children}
    </div>
  );
}

export function SecretBadge({ value }: { value?: SecretMetadata }) {
  if (!value?.configured) {
    return <span className="text-zinc-500">not configured</span>;
  }

  return (
    <span className="text-zinc-300">
      {value.mask} {value.fingerprint ? `(${value.fingerprint})` : ""}
    </span>
  );
}

export function StatusLine({
  error,
  notice,
}: {
  error: string | null;
  notice: string | null;
}) {
  if (!error && !notice) return null;

  return (
    <div
      className={`rounded-lg border px-3 py-2 text-sm ${
        error
          ? "border-zinc-700 bg-zinc-900 text-zinc-200"
          : "border-zinc-700 bg-zinc-900 text-zinc-200"
      }`}
    >
      {error ? `Error: ${error}` : notice}
    </div>
  );
}

export const inputClass = "bg-zinc-800 border-zinc-700 text-zinc-100";

export function splitTerms(value: string) {
  return value
    .split(",")
    .map((term) => term.trim())
    .filter(Boolean);
}
