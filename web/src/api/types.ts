export type Role = "SIGNER" | "OPERATOR" | "ADMIN";

export interface Me {
  id: string;
  email: string;
  display_name: string;
  roles: Role[];
  // The built-in account still has its initial password: remind at every sign-in.
  must_change_password?: boolean;
  source?: "builtin" | "sso";
}

export interface PublicConfig {
  app_version: string;
  consent_text: string;
  consent_version: string;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_label: string;
  original_filename: string;
  file_size: number;
  mime_type: string;
  sha256: string;
  status: "DRAFT" | "PUBLISHED" | "SUPERSEDED" | "ARCHIVED";
  created_at: string;
  published_at: string | null;
  // null when the server did not compute it; false = part of the evidence trail.
  can_delete: boolean | null;
  delete_blockers: string[];
}

export interface DocumentDetail {
  id: string;
  title: string;
  description: string;
  category: string;
  can_delete: boolean | null;
  created_at: string;
  versions: DocumentVersion[];
}

export type AssignmentStatus =
  | "WAITING"
  | "PENDING"
  | "VIEWED"
  | "SIGNED"
  | "EXPIRED"
  | "CANCELLED";

/** Who is "Signataire N" in a campaign: one named person, or the list of recipients. */
export interface CampaignRole {
  role: number;
  label: string;
  mode: "FIXED" | "EACH" | null;
  user_id: string | null;
  user_display_name: string | null;
}

export interface MyAssignment {
  id: string;
  campaign_id: string;
  campaign_name: string;
  document_version_id: string;
  document_title: string;
  version_label: string;
  role?: number;
  waiting_on?: string[];
  status: AssignmentStatus;
  assigned_at: string;
  deadline: string | null;
  signed_at: string | null;
  signature_id: string | null;
}

export interface CampaignAssignment {
  id: string;
  document_version_id: string;
  document_title: string;
  signature_id: string | null;
  groups: string[];
  role?: number;
  role_label?: string;
  waiting_on?: string[];
  user_id: string;
  user_email: string;
  user_display_name: string;
  status: AssignmentStatus;
  assigned_at: string;
  first_viewed_at: string | null;
  signed_at: string | null;
  deadline: string | null;
  reminder_count: number;
}

export interface CampaignDocumentInfo {
  version_id: string;
  title: string;
  version_label: string;
  status: string;
  elements: number;
}

export type CampaignStatus = "DRAFT" | "ACTIVE" | "CLOSED" | "CANCELLED" | "ARCHIVED";

export interface Campaign {
  id: string;
  name: string;
  description: string;
  status: CampaignStatus;
  target_mode: string;
  created_at: string;
  launch_at: string | null;
  deadline: string | null;
  closed_at: string | null;
  document_version_ids: string[];
  roles_required: number;
  roles: CampaignRole[];
  documents: CampaignDocumentInfo[];
  assignment_counts: Record<AssignmentStatus, number>;
  policies: CampaignPolicies;
  renewal_of_campaign_id: string | null;
}

export interface SignatureDetail extends SignatureSummary {
  campaign_id: string | null;
  document_title: string;
  version_label: string;
  campaign_name: string | null;
  signed_file_sha256: string;
  original_file_sha256: string;
  signing_key_id: string;
}

export interface VerificationResult {
  valid: boolean;
  checks: Record<string, boolean>;
}

export interface SignatureSummary {
  id: string;
  display_id: string;
  document_id: string;
  document_version_id: string;
  signed_at_utc: string;
  display_name_snapshot: string;
  email_snapshot: string;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  active: boolean;
  manually_disabled: boolean;
  source: string;
  last_login_at: string | null;
  roles: Role[];
  can_delete: boolean;
  delete_blockers: string[];
}

export interface AuditEvent {
  event_id: string;
  timestamp_utc: string;
  actor_id: string | null;
  actor_identity_snapshot: { email?: string; display_name?: string } | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  result: string;
  request_id: string | null;
  metadata: Record<string, unknown> | null;
}

export interface DirectoryGroup {
  id: string;
  source: string;
  name: string;
  description: string;
  active: boolean;
  member_count: number;
}

export interface DirectorySyncRun {
  id: string;
  source: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  users_added: number;
  users_updated: number;
  users_deactivated: number;
  groups_added: number;
  groups_updated: number;
  memberships_added: number;
  memberships_removed: number;
  error: string | null;
}

export interface MailConnectorConfig {
  kind: "smtp" | "graph";
  graph_tenant_id: string | null;
  graph_client_id: string | null;
  host: string;
  port: number;
  use_tls: boolean;
  use_starttls: boolean;
  username: string;
  password_configured: boolean;
  from_address: string;
  reply_to: string | null;
  timeout_seconds: number;
  updated_at: string;
}

export interface SigningKeyInfo {
  revoked_at: string | null;
  key_id: string;
  public_key_hex: string;
  status: "ACTIVE" | "RETIRED" | "REVOKED";
  created_at: string;
  activated_at: string | null;
  retired_at: string | null;
}

export interface ReportSummary {
  id: string;
  display_id: string;
  campaign_id: string;
  generated_at: string;
  pdf_sha256: string;
  csv_sha256: string;
}

export interface DirectorySource {
  source: string;
  configured: boolean;
  fields: Record<string, string>;
  sync_interval_minutes: number | null;
}

export interface OperatorDashboard {
  campaigns: { active: number; closed: number; draft: number };
  assignments: {
    expected: number;
    signed: number;
    outstanding: number;
    not_viewed: number;
    overdue: number;
  };
  signature_rate: number | null;
  reminders_sent: number;
}

export interface DiagnosticCheck {
  name: string;
  status: "OK" | "WARN" | "ERROR" | "DISABLED";
  detail: string;
}

export interface DiagnosticsReport {
  status: "OK" | "WARN" | "ERROR";
  checked_at: string;
  checks: DiagnosticCheck[];
}

export interface CampaignPolicies {
  reminder_first_days: number | null;
  reminder_interval_days: number | null;
  reminder_max_count: number | null;
  reminder_before_deadline_days: number | null;
  renewal_every: number | null;
  renewal_unit: "DAYS" | "MONTHS" | null;
}
