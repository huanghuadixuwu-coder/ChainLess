"use client";

import { Button } from "@/components/ui/button";
import type { AcquisitionNotice } from "@/lib/api";

interface AcquisitionHintCardProps {
  notice: AcquisitionNotice;
  compact?: boolean;
  onOpenInbox?: () => void;
}

const EVENT_LABELS: Record<string, string> = {
  acquisition_gap: "Capability gap",
  acquisition_exploration: "Exploration",
  acquisition_recommendation: "Recommendation",
  acquisition_approval_required: "Approval required",
  acquisition_verification: "Verification",
  acquisition_activation: "Activation",
  acquisition_runtime_planning_issue: "Planning issue",
  acquisition_permission: "Permission",
  acquisition_browser_trace: "Browser trace",
};

function payloadOf(notice: AcquisitionNotice) {
  return notice.payload && typeof notice.payload === "object"
    ? (notice.payload as Record<string, unknown>)
    : {};
}

function textValue(
  notice: AcquisitionNotice,
  key: string,
  fallback?: string
) {
  const payload = payloadOf(notice);
  const value = notice[key] ?? payload[key];
  return typeof value === "string" && value.trim() ? value : fallback || "";
}

function titleFor(notice: AcquisitionNotice) {
  return (
    textValue(notice, "title") ||
    EVENT_LABELS[notice.type] ||
    notice.type.replace(/_/g, " ")
  );
}

function nextStepFor(notice: AcquisitionNotice) {
  const explicit = textValue(notice, "next_step");
  if (explicit) return explicit;
  if (notice.type === "acquisition_exploration") {
    return "Review the exploration evidence before turning it into a durable capability.";
  }
  if (notice.type === "acquisition_approval_required") {
    return "Approve the exploration or activation only if the boundary is correct.";
  }
  if (notice.type === "acquisition_runtime_planning_issue") {
    return "Check whether the Agent missed an existing capability before creating a new one.";
  }
  return "Open Inbox to review the durable acquisition record.";
}

export function AcquisitionHintCard({
  notice,
  compact = false,
  onOpenInbox,
}: AcquisitionHintCardProps) {
  const status = textValue(notice, "status", "noticed");
  const risk = textValue(notice, "risk_level");
  const severity = textValue(notice, "severity");
  const problem =
    textValue(notice, "problem") ||
    textValue(notice, "description") ||
    textValue(notice, "failure_reason") ||
    textValue(notice, "message");
  const cause = textValue(notice, "cause") || textValue(notice, "reason");
  const recovery =
    textValue(notice, "recovery") ||
    (notice.type === "acquisition_activation"
      ? "Rollback remains available from the acquisition panel when activation creates runtime state."
      : "");

  return (
    <div
      data-testid="acquisition-hint-card"
      className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-zinc-100">
              {titleFor(notice)}
            </p>
            <span className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">
              {notice.type.replace("acquisition_", "")}
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-500">{status}</p>
        </div>
      </div>

      <div
        className={`mt-2 space-y-2 text-xs text-zinc-400 ${
          compact ? "line-clamp-6" : ""
        }`}
      >
        <FactLine label="Problem" value={problem || "A capability acquisition event was recorded."} />
        {cause && <FactLine label="Cause" value={cause} />}
        <FactLine label="Risk" value={risk || severity || "not specified"} />
        <FactLine label="Next step" value={nextStepFor(notice)} />
        {recovery && <FactLine label="Recovery" value={recovery} />}
      </div>

      {onOpenInbox && (
        <div className="mt-3">
          <Button
            size="xs"
            variant="ghost"
            className="text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            onClick={onOpenInbox}
          >
            Open Inbox
          </Button>
        </div>
      )}
    </div>
  );
}

function FactLine({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <span className="text-zinc-500">{label}: </span>
      <span className="text-zinc-300">{value}</span>
    </p>
  );
}
