export type Role = "SIGNER" | "PREPARER" | "OPERATOR" | "ADMIN";

export interface Me {
  id: string;
  email: string;
  display_name: string;
  roles: Role[];
  // The built-in account still has its initial password: remind at every sign-in.
  must_change_password?: boolean;
  source?: "builtin" | "local" | "sso";
}

export interface PublicConfig {
  app_version: string;
  consent_text: string;
  consent_version: string;
  /** Word / LibreOffice files can be dropped (the server converts them to PDF). */
  office_conversion?: boolean;
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
  signature_method?: SignatureMethod;
  docusign?: DocusignFollowUp | null;
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
  /** The signers (positions) with something to fill on it, and those with a signature placed. */
  element_roles: number[];
  signature_roles: number[];
  /** Copies sent to the signers. A document added to a running campaign is not until released. */
  released: boolean;
}

export type SignatureMethod = "LOCAL" | "DOCUSIGN";

/** One way to sign a request, as the "Faire signer" choice offers it. */
export interface SignatureMethodOption {
  method: SignatureMethod;
  label: string;
  description: string;
  available: boolean;
  unavailable_reason?: string | null;
}

/** What the signer is told about the DocuSign envelope of a request signed through DocuSign. */
export interface DocusignFollowUp {
  status: "QUEUED" | "SENT" | "COMPLETED" | "DECLINED" | "VOIDED" | "FAILED";
  error: string | null;
  /** Only on the test stack: where the mock DocuSign's mailbox is. */
  inbox_url: string | null;
}

export interface CampaignPlan {
  signature_method?: SignatureMethod;
  all_users?: boolean;
  group_ids?: string[];
  user_ids?: string[];
  start_at?: string | null;
  deadline?: string | null;
  reminder_first_days?: number | null;
  reminder_interval_days?: number | null;
  renewal_every?: number | null;
  renewal_unit?: "DAYS" | "MONTHS" | null;
}

export type CampaignStatus = "DRAFT" | "SCHEDULED" | "ACTIVE" | "CLOSED" | "CANCELLED" | "ARCHIVED";

export interface Campaign {
  id: string;
  name: string;
  description: string;
  status: CampaignStatus;
  target_mode: string;
  signature_method?: SignatureMethod;
  created_at: string;
  launch_at: string | null;
  scheduled_start: string | null;
  deadline: string | null;
  closed_at: string | null;
  delete_blockers: string[];
  document_version_ids: string[];
  /** The work in progress of a draft (recipients, planning), kept as the operator goes. */
  plan: CampaignPlan | null;
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
  /** From outside the company: added by e-mail address, signs in with their own account. */
  external?: boolean;
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

/** A mail connector as the server describes it: its settings, with help for each. */
export interface MailKindSpec {
  kind: "smtp" | "graph" | "gmail";
  label: string;
  description: string;
  fields: ConnectorField[];
  secret: ConnectorField;
}

export interface MailConnectorConfig {
  kind: "smtp" | "graph" | "gmail";
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

/** One setting of a connector, as the server describes it (label, help bubble, example). */
export interface ConnectorField {
  name: string;
  label: string;
  help: string;
  example: string;
  kind: "text" | "password" | "textarea" | "select" | "number" | "checkbox";
  options: { value: string; label: string }[];
  default: string;
  required: boolean;
}

export interface ConnectorSpec {
  label: string;
  description: string;
  fields: ConnectorField[];
  secret: ConnectorField;
  /** Steps to prepare on the provider's side, when there are some. */
  guide?: string[];
}

export interface DirectorySource {
  source: string;
  configured: boolean;
  fields: Record<string, string>;
  sync_interval_minutes: number | null;
  /** Absent for the demonstration directory, which has nothing to configure. */
  spec?: ConnectorSpec;
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

export interface SignedRow {
  id: string;
  display_id: string;
  signed_at: string;
  document_title: string;
  version_label: string;
  campaign_id: string | null;
  campaign_name: string | null;
  signer_name: string;
  signer_email: string;
  signed_file_sha256: string;
}

export interface OutstandingRow {
  id: string;
  status: AssignmentStatus;
  document_title: string;
  version_label: string;
  campaign_id: string;
  campaign_name: string;
  signer_name: string;
  signer_email: string;
  deadline: string | null;
}

export interface SignedDocumentsResponse {
  campaigns: { id: string; name: string; status: CampaignStatus }[];
  signed: SignedRow[];
  outstanding: OutstandingRow[];
  totals: { signed: number; outstanding: number; waiting: number };
}

export interface SignAllInput {
  id: string;
  label: string;
  required: boolean;
  group_key: string | null;
  kind: string;
}

export interface SignAllDocument {
  version_id: string;
  title: string;
  version_label: string;
  inputs: SignAllInput[];
}

export interface SignAllPlan {
  campaign: { id: string; name: string };
  documents: SignAllDocument[];
  waiting: number;
}

/** Who signed a document in a campaign, in order, and who is left. */
export interface SignatureStep {
  role: number;
  role_label: string;
  name: string;
  email: string;
  status: "SIGNED" | "PENDING" | "VIEWED" | "WAITING" | "EXPIRED";
  signed_at: string | null;
  display_id: string | null;
  mine: boolean;
}

export interface SignatureChain {
  steps: SignatureStep[];
  /** Other recipients, counted but not named (for someone who is only a recipient). */
  others: { count: number; signed: number } | null;
  complete: boolean;
}

export interface Branding {
  has_logo: boolean;
  logo_sha256: string | null;
}

/** The DocuSign connection as the administration page shows it (the private key never comes back). */
export interface DocusignAdmin {
  configured: boolean;
  values: { environment: string; integration_key: string; user_id: string; account_id: string };
  has_private_key: boolean;
  fields: ConnectorField[];
  private_key: ConnectorField;
  guide: string[];
  test_setup_available: boolean;
  mock: boolean;
}
