export type Role = "SIGNER" | "OPERATOR" | "ADMIN";

export interface Me {
  id: string;
  email: string;
  display_name: string;
  roles: Role[];
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
}

export interface DocumentDetail {
  id: string;
  title: string;
  created_at: string;
  versions: DocumentVersion[];
}

export type AssignmentStatus = "PENDING" | "VIEWED" | "SIGNED" | "EXPIRED" | "CANCELLED";

export interface MyAssignment {
  id: string;
  campaign_id: string;
  campaign_name: string;
  document_version_id: string;
  document_title: string;
  version_label: string;
  status: AssignmentStatus;
  assigned_at: string;
  deadline: string | null;
  signed_at: string | null;
  signature_id: string | null;
}

export interface CampaignAssignment {
  id: string;
  document_version_id: string;
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
  assignment_counts: Record<AssignmentStatus, number>;
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
  roles: Role[];
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
}
