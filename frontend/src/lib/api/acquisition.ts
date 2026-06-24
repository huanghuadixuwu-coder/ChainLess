import { api, type Page } from "@/lib/api";

type JsonRecord = Record<string, unknown>;

interface AcquisitionGap {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  description: string;
  gap_type: string;
  severity: string;
  status: string;
  source_kind: string;
  source_run_id: string;
  source_evidence: JsonRecord[];
  evidence: JsonRecord;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

interface AcquisitionExploration {
  id: string;
  tenant_id: string;
  user_id: string;
  gap_id: string;
  source_run_id: string;
  risk_level: string;
  approval_id?: string | null;
  strategy: string;
  status: string;
  tool_events: JsonRecord[];
  script_ref?: string | null;
  artifact_refs: JsonRecord[];
  stdout_excerpt?: string | null;
  stderr_excerpt?: string | null;
  result_summary?: string | null;
  failure_reason?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

interface AcquisitionRecommendation {
  id: string;
  tenant_id: string;
  user_id: string;
  gap_id: string;
  exploration_run_id?: string | null;
  recommendation_type: string;
  title: string;
  summary: string;
  reason: string;
  evidence: JsonRecord;
  risk_level: string;
  expected_value: JsonRecord;
  required_permissions: JsonRecord;
  candidate_targets: JsonRecord[];
  created_at: string;
  updated_at: string;
}

interface AcquisitionTarget {
  target_type: string;
  target_name: string;
  target_owner: string;
  target_payload: JsonRecord;
  permission_bundle: PermissionBundle;
  verification_plan: JsonRecord;
  rollback_plan: JsonRecord;
  activation_status?: string;
  activation_result?: JsonRecord;
  activated_resource_ref?: JsonRecord | null;
}

interface PermissionBundle {
  target_id?: string | null;
  target_type: string;
  target_version_ref?: string | null;
  permission_scope: JsonRecord;
  risk_level: string;
  confirmation_policy: string;
  credential_scope: string;
  credential_connection_refs: string[];
  data_scope: string;
  network_scope: string;
  egress_policy: JsonRecord;
  write_scope: string;
  execution_scope: string;
  duration: string;
  expires_at?: string | null;
  revocation_plan: JsonRecord;
  audit_events: JsonRecord[];
  approved_snapshot_hash?: string | null;
}

interface AcquisitionProposal {
  id: string;
  tenant_id: string;
  user_id: string;
  proposal_kind: "runtime_activation" | "development_patch_proposal" | string;
  gap_id: string;
  recommendation_id: string;
  title: string;
  reason: string;
  evidence: JsonRecord;
  status: string;
  risk_level: string;
  permission_bundle: PermissionBundle;
  primary_target?: AcquisitionTarget | null;
  secondary_targets: AcquisitionTarget[];
  development_handoff?: JsonRecord | null;
  verification_plan: JsonRecord;
  rollback_plan: JsonRecord;
  user_visible_effect: string;
  approval_history: JsonRecord[];
  activation_snapshot_hash?: string | null;
  snapshot_created_at?: string | null;
  rollback?: JsonRecord;
  created_at: string;
  updated_at: string;
}

interface RuntimePlanningIssue {
  id: string;
  tenant_id: string;
  user_id: string;
  source_run_id: string;
  conversation_id?: string | null;
  issue_type: string;
  available_capability_ref: JsonRecord;
  missed_signal: string;
  planner_decision_summary: string;
  expected_decision_summary: string;
  severity: string;
  status: string;
  evidence: JsonRecord;
  created_at: string;
  updated_at: string;
}

interface CredentialConnection {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  provider: string;
  connection_type: string;
  credential_kind: string;
  secret_storage_kind: string;
  secret_generation: number;
  secret_ref_present: boolean;
  scopes: string[];
  allowed_target_types: string[];
  allowed_target_refs: JsonRecord[];
  status: string;
  metadata_redacted: JsonRecord;
  expires_at?: string | null;
  last_validated_at?: string | null;
  rotation_required_at?: string | null;
  revoked_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface BrowserSession {
  id: string;
  tenant_id: string;
  user_id: string;
  activation_target_id?: string | null;
  name: string;
  status: string;
  allowlisted_domains: string[];
  credential_ref?: string | null;
  credential_generation?: number | null;
  runtime_service_name: string;
  runtime_image_ref: string;
  runtime_health_check: JsonRecord;
  network_policy: JsonRecord;
  cookie_scope: JsonRecord;
  profile_policy: JsonRecord;
  profile_storage_ref?: string | null;
  profile_retention_policy: JsonRecord;
  max_session_seconds: number;
  max_actions_per_run: number;
  concurrency_limit: number;
  cpu_limit: string;
  memory_limit_mb: number;
  max_trace_bytes: number;
  trace_retention_days: number;
  action_redaction_policy: JsonRecord;
  write_confirmation_policy: JsonRecord;
  enabled: boolean;
  last_verified_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface BrowserTrace {
  id: string;
  tenant_id: string;
  user_id: string;
  target_id: string;
  proposal_id: string;
  trace: JsonRecord;
  created_at: string;
  updated_at: string;
}

interface StandingPermission {
  id: string;
  tenant_id: string;
  user_id: string;
  proposal_id: string;
  target_id: string;
  target_type: string;
  permission_scope: JsonRecord;
  risk_level: string;
  duration: string;
  approved_snapshot_hash: string;
  status: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  renewal_required_at?: string | null;
  revocation_plan: JsonRecord;
  audit_events: JsonRecord[];
  created_at: string;
  updated_at: string;
}

interface AcquisitionJournal {
  tenant_id: string;
  user_id: string;
  generated_at: string;
  entries: JsonRecord[];
  rendered_markdown: string;
}

interface WorkspaceConnector {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  connector_id: string;
  display_path: string;
  container_mount_path: string;
  backend_mount_path: string;
  sandbox_mount_path: string;
  connector_root: string;
  mount_generation: number;
  mount_health_status: string;
  mode: string;
  allowlist_rule: JsonRecord;
  standing_permission_id?: string | null;
  enabled: boolean;
  expires_at?: string | null;
  last_verified_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface ApproveExplorationBody {
  source_run_id: string;
  strategy: string;
  risk_level: string;
  bounds?: JsonRecord;
  approval_id?: string | null;
}

interface VerifyProposalBody {
  verification_kind?: string;
  input_fixture?: JsonRecord;
  expected_result?: JsonRecord;
  actual_result?: JsonRecord;
  artifact_refs?: JsonRecord[];
  target_id?: string | null;
}

interface ApproveActivationBody {
  approved_snapshot_hash: string;
  reason?: string | null;
}

interface ActivateProposalBody {
  approved_snapshot_hash: string;
  verification_id?: string | null;
  target_ids?: string[] | null;
}

interface CreateCredentialBody {
  name: string;
  provider: string;
  connection_type: string;
  credential_kind: string;
  secret_storage_kind: string;
  secret_value?: string | null;
  secret_ref?: string | null;
  scopes?: string[];
  allowed_target_types?: string[];
  allowed_target_refs?: JsonRecord[];
  metadata_redacted?: JsonRecord;
  expires_at?: string | null;
}

interface RotateCredentialBody {
  secret_value?: string | null;
  secret_ref?: string | null;
  secret_storage_kind?: string | null;
  metadata_redacted?: JsonRecord | null;
}

const acquisitionPath = "/api/v1/acquisition";

function query(params: { limit?: number; offset?: number } = {}) {
  return new URLSearchParams({
    limit: String(params.limit ?? 20),
    offset: String(params.offset ?? 0),
  });
}

async function json<T>(response: Response) {
  return (await response.json()) as T;
}

const getPage = async <T>(path: string, params?: { limit?: number; offset?: number }) =>
  json<Page<T>>(await api.get(`${path}?${query(params)}`));

const getOne = async <T>(path: string) => json<T>(await api.get(path));

const postOne = async <T>(path: string, body: unknown = {}) =>
  json<T>(await api.post(path, body));

export const acquisitionApi = {
  listGaps: (params?: { limit?: number; offset?: number }) =>
    getPage<AcquisitionGap>(`${acquisitionPath}/gaps`, params),
  getGap: (gapId: string) =>
    getOne<AcquisitionGap>(`${acquisitionPath}/gaps/${encodeURIComponent(gapId)}`),
  dismissGap: (gapId: string, reason?: string | null) =>
    postOne<AcquisitionGap>(
      `${acquisitionPath}/gaps/${encodeURIComponent(gapId)}/dismiss`,
      { reason }
    ),
  snoozeGap: (gapId: string, snoozedUntil: string) =>
    postOne<AcquisitionGap>(
      `${acquisitionPath}/gaps/${encodeURIComponent(gapId)}/snooze`,
      { snoozed_until: snoozedUntil }
    ),
  approveExploration: (gapId: string, body: ApproveExplorationBody) =>
    postOne<AcquisitionExploration>(
      `${acquisitionPath}/gaps/${encodeURIComponent(gapId)}/approve-exploration`,
      { ...body, bounds: body.bounds || {} }
    ),
  listExplorations: (params?: { limit?: number; offset?: number }) =>
    getPage<AcquisitionExploration>(`${acquisitionPath}/explorations`, params),
  getExploration: (explorationId: string) =>
    getOne<AcquisitionExploration>(
      `${acquisitionPath}/explorations/${encodeURIComponent(explorationId)}`
    ),
  listRecommendations: (params?: { limit?: number; offset?: number }) =>
    getPage<AcquisitionRecommendation>(`${acquisitionPath}/recommendations`, params),
  getRecommendation: (recommendationId: string) =>
    getOne<AcquisitionRecommendation>(
      `${acquisitionPath}/recommendations/${encodeURIComponent(recommendationId)}`
    ),
  draftProposal: (recommendationId: string, body: Omit<AcquisitionProposal, "id" | "tenant_id" | "user_id" | "status" | "approval_history" | "created_at" | "updated_at">) =>
    postOne<AcquisitionProposal>(
      `${acquisitionPath}/recommendations/${encodeURIComponent(recommendationId)}/draft-proposal`,
      body
    ),
  listProposals: (params?: { limit?: number; offset?: number }) =>
    getPage<AcquisitionProposal>(`${acquisitionPath}/proposals`, params),
  getProposal: (proposalId: string) =>
    getOne<AcquisitionProposal>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}`
    ),
  verifyProposal: (proposalId: string, body: VerifyProposalBody) =>
    postOne<JsonRecord>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/verify`,
      body
    ),
  approveActivation: (proposalId: string, body: ApproveActivationBody) =>
    postOne<AcquisitionProposal>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/approve-activation`,
      body
    ),
  rejectActivation: (proposalId: string, reason?: string | null) =>
    postOne<AcquisitionProposal>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/reject-activation`,
      { reason }
    ),
  activateProposal: (proposalId: string, body: ActivateProposalBody) =>
    postOne<AcquisitionProposal>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/activate`,
      body
    ),
  rollbackProposal: (proposalId: string, reason?: string | null) =>
    postOne<AcquisitionProposal>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/rollback`,
      { reason }
    ),
  handoffDevelopmentPatch: (proposalId: string) =>
    postOne<JsonRecord>(
      `${acquisitionPath}/proposals/${encodeURIComponent(proposalId)}/handoff-development-patch`
    ),
  listRuntimePlanningIssues: (params?: { limit?: number; offset?: number }) =>
    getPage<RuntimePlanningIssue>(
      `${acquisitionPath}/runtime-planning-issues`,
      params
    ),
  getRuntimePlanningIssue: (issueId: string) =>
    getOne<RuntimePlanningIssue>(
      `${acquisitionPath}/runtime-planning-issues/${encodeURIComponent(issueId)}`
    ),
  dismissRuntimePlanningIssue: (issueId: string, reason?: string | null) =>
    postOne<RuntimePlanningIssue>(
      `${acquisitionPath}/runtime-planning-issues/${encodeURIComponent(issueId)}/dismiss`,
      { reason }
    ),
  listCredentialConnections: (params?: { limit?: number; offset?: number }) =>
    getPage<CredentialConnection>(
      `${acquisitionPath}/credential-connections`,
      params
    ),
  createCredentialConnection: (body: CreateCredentialBody) =>
    postOne<CredentialConnection>(`${acquisitionPath}/credential-connections`, body),
  getCredentialConnection: (credentialId: string) =>
    getOne<CredentialConnection>(
      `${acquisitionPath}/credential-connections/${encodeURIComponent(credentialId)}`
    ),
  validateCredentialConnection: (credentialId: string) =>
    postOne<CredentialConnection>(
      `${acquisitionPath}/credential-connections/${encodeURIComponent(credentialId)}/validate`
    ),
  rotateCredentialConnection: (credentialId: string, body: RotateCredentialBody) =>
    postOne<CredentialConnection>(
      `${acquisitionPath}/credential-connections/${encodeURIComponent(credentialId)}/rotate`,
      body
    ),
  revokeCredentialConnection: (credentialId: string, reason?: string | null) =>
    postOne<CredentialConnection>(
      `${acquisitionPath}/credential-connections/${encodeURIComponent(credentialId)}/revoke`,
      { reason }
    ),
  listBrowserSessions: (params?: { limit?: number; offset?: number }) =>
    getPage<BrowserSession>(`${acquisitionPath}/browser-sessions`, params),
  getBrowserSession: (sessionId: string) =>
    getOne<BrowserSession>(
      `${acquisitionPath}/browser-sessions/${encodeURIComponent(sessionId)}`
    ),
  terminateBrowserSession: (sessionId: string, reason?: string | null) =>
    postOne<BrowserSession>(
      `${acquisitionPath}/browser-sessions/${encodeURIComponent(sessionId)}/terminate`,
      { reason }
    ),
  getBrowserTrace: (traceId: string) =>
    getOne<BrowserTrace>(
      `${acquisitionPath}/browser-traces/${encodeURIComponent(traceId)}`
    ),
  listPermissions: (params?: { limit?: number; offset?: number }) =>
    getPage<StandingPermission>(`${acquisitionPath}/permissions`, params),
  revokePermission: (permissionId: string, reason?: string | null) =>
    postOne<StandingPermission>(
      `${acquisitionPath}/permissions/${encodeURIComponent(permissionId)}/revoke`,
      { reason }
    ),
  renewPermission: (permissionId: string) =>
    postOne<StandingPermission>(
      `${acquisitionPath}/permissions/${encodeURIComponent(permissionId)}/renew`
    ),
  getJournal: (sectionLimit?: number) => {
    const suffix = sectionLimit ? `?section_limit=${sectionLimit}` : "";
    return getOne<AcquisitionJournal>(`${acquisitionPath}/journal${suffix}`);
  },
  listWorkspaceConnectors: (params?: { limit?: number; offset?: number }) =>
    getPage<WorkspaceConnector>(`${acquisitionPath}/workspace-connectors`, params),
  getWorkspaceConnector: (connectorId: string) =>
    getOne<WorkspaceConnector>(
      `${acquisitionPath}/workspace-connectors/${encodeURIComponent(connectorId)}`
    ),
  revokeWorkspaceConnector: (connectorId: string, reason?: string | null) =>
    postOne<WorkspaceConnector>(
      `${acquisitionPath}/workspace-connectors/${encodeURIComponent(connectorId)}/revoke`,
      { reason }
    ),
};

export type {
  AcquisitionGap,
  AcquisitionExploration,
  AcquisitionRecommendation,
  AcquisitionProposal,
  AcquisitionTarget,
  PermissionBundle,
  RuntimePlanningIssue,
  CredentialConnection,
  BrowserSession,
  BrowserTrace,
  StandingPermission,
  AcquisitionJournal,
  WorkspaceConnector,
  ApproveExplorationBody,
  VerifyProposalBody,
  ApproveActivationBody,
  ActivateProposalBody,
  CreateCredentialBody,
  RotateCredentialBody,
};
