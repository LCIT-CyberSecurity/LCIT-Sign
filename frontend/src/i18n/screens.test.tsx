import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import App from "../App";
import LoginPage from "../pages/LoginPage";
import OperatorDocumentsPage from "../pages/OperatorDocumentsPage";
import OperatorCampaignsPage from "../pages/OperatorCampaignsPage";
import SignAllPage from "../pages/SignAllPage";
import AdminUsersPage from "../pages/AdminUsersPage";
import AdminDirectoryPage from "../pages/AdminDirectoryPage";
import ChangePasswordDialog from "../components/ChangePasswordDialog";
import UserMenu from "../components/UserMenu";
import { api } from "../api/client";
import { setLocale, STORAGE_KEY } from "./index";

const auth = vi.hoisted(() => ({
  user: null as null | { display_name: string; email: string; roles: string[]; source?: string },
  roles: [] as string[],
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: auth.user,
    loading: false,
    hasRole: (role: string) => auth.roles.includes(role),
    refresh: vi.fn(),
  }),
}));
vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn(), patch: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const admin = { display_name: "Alice Martin", email: "alice.martin@lcit-test.local", roles: ["ADMIN"], source: "builtin" as const };

beforeEach(() => {
  vi.clearAllMocks();
  auth.user = admin;
  auth.roles = ["ADMIN"];
  vi.mocked(api.get).mockResolvedValue([]);
});

const rendered = (ui: React.ReactElement, path = "/") =>
  render(
    <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>,
  );

describe("login, in both languages", () => {
  const options = { sso: true, provider: "entra", local: true };
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/auth/options" ? options : { has_logo: false, logo_sha256: null },
    );
  });

  it("is French by default", async () => {
    auth.user = null;
    rendered(<LoginPage />);
    expect(await screen.findByRole("link", { name: /Continuer avec Microsoft/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Connexion" })).toBeInTheDocument();
    expect(screen.getByText("Signez facilement vos documents !")).toBeInTheDocument();
  });

  it("is English once the language is changed, with nothing left in French", async () => {
    await setLocale("en");
    auth.user = null;
    const { container } = rendered(<LoginPage />);
    expect(await screen.findByRole("link", { name: /Continue with Microsoft/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Sign your documents with ease!")).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/Connexion|Signez|Continuer|Espace/);
  });
});

describe("the account menu changes the language at once", () => {
  it("switches without any call to the server, and remembers it in the browser only", async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn();
    render(<UserMenu user={{ id: "1", ...admin, roles: ["ADMIN"] }} onSignOut={onSignOut} />);
    expect(screen.getByText("Langue")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Français/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /English/ })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: /English/ }));

    expect(screen.getByText("Language")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sign out/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /English/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Night/ })).toBeInTheDocument();
    expect(screen.queryByText("Se déconnecter")).toBeNull();
    expect(document.documentElement.lang).toBe("en");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("en");
    for (const call of [api.get, api.post, api.put, api.patch, api.del]) expect(call).not.toHaveBeenCalled();
    // The person's name and email are data: the same in both languages.
    expect(screen.getAllByText("Alice Martin").length).toBeGreaterThan(0);
    expect(screen.getByText("alice.martin@lcit-test.local")).toBeInTheDocument();
    // The roles are shown in the new language, the API values are not touched.
    expect(screen.getAllByText("Administrator").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /Français/ }));
    expect(screen.getByRole("button", { name: /Se déconnecter/ })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fr");
  });
});

describe("navigation and the shell", () => {
  it.each([
    ["fr", ["Mes signatures", "Faire signer", "Suivi", "Clés de signature", "Identités & accès", "Diagnostic"], "Navigation principale"],
    ["en", ["My signatures", "Send for signature", "Tracking", "Signing keys", "Identities & access", "Diagnostics"], "Main navigation"],
  ])("labels the sidebar in %s", async (locale, labels, navLabel) => {
    await setLocale(locale);
    rendered(
      <App />,
      "/admin/users",
    );
    const nav = await screen.findByRole("navigation", { name: navLabel });
    for (const label of labels) expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
  });

  it("opens the mobile menu with a translated label and titles the page", async () => {
    await setLocale("en");
    rendered(<App />, "/admin/signing-keys");
    expect(await screen.findByRole("button", { name: "Open menu" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Signing keys" })).toBeInTheDocument();
  });
});

describe("documents", () => {
  const drop = (name: string) =>
    fireEvent.change(screen.getByTestId("dropzone-input"), { target: { files: [new File(["%PDF"], name)] } });

  it("words the import in each language and keeps the file's own name", async () => {
    rendered(<OperatorDocumentsPage />);
    drop("charte_it-2026.pdf");
    expect(screen.getByRole("button", { name: "Importer le document" })).toBeInTheDocument();
    expect(screen.getByTestId("pending-files")).toHaveTextContent("charte_it-2026.pdf");
    await setLocale("en");
    expect(await screen.findByRole("button", { name: "Import the document" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove charte_it-2026.pdf" })).toBeInTheDocument();
    expect(screen.getByTestId("pending-files")).toHaveTextContent("charte_it-2026.pdf");
  });
});

describe("signing everything at once", () => {
  const plan = (count: number) => ({
    campaign: { id: "c1", name: "Signature NDA France 2026" },
    documents: Array.from({ length: count }, (_, i) => ({
      version_id: `v${i}`, title: `Document ${i + 1}`, version_label: "1.0", inputs: [],
    })),
    waiting: 2,
  });
  const open = (count: number) => {
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/config" ? { consent_text: "J'atteste.", consent_version: "1", app_version: "x" } : plan(count),
    );
    render(
      <MemoryRouter initialEntries={["/sign-all/c1"]}>
        <Routes>
          <Route path="/sign-all/:campaignId" element={<SignAllPage />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  it("counts in French", async () => {
    open(2);
    expect(await screen.findByTestId("sign-all-documents")).toHaveTextContent("2 document(s) à signer");
  });

  it("counts in English, with the right plural, and never touches the campaign's name", async () => {
    await setLocale("en");
    open(1);
    const card = await screen.findByTestId("sign-all-documents");
    expect(card).toHaveTextContent("1 document to sign");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign everything — Signature NDA France 2026");
    expect(card).toHaveTextContent("2 other documents are waiting for you");
    // The consent text is the one the server holds (it ends up in the proof): shown as it is.
    expect(screen.getByText("J'atteste.")).toBeInTheDocument();
  });
});

describe("tracking", () => {
  const campaign = {
    id: "c1", name: "Signature NDA France 2026", description: "", status: "ACTIVE", target_mode: "ALL_USERS",
    created_at: "2026-10-01T10:00:00Z", launch_at: "2026-10-02T10:00:00Z", scheduled_start: null,
    deadline: "2026-10-30T10:00:00Z", closed_at: null, delete_blockers: [], document_version_ids: ["v1", "v2"],
    plan: null, roles_required: 1, roles: [], documents: [], policies: {}, renewal_of_campaign_id: null,
    assignment_counts: { SIGNED: 1, PENDING: 2, WAITING: 0, VIEWED: 0, EXPIRED: 0, CANCELLED: 0 },
  };
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) => (path === "/campaigns" ? [campaign] : null));
  });

  it("shows the status and the target in French, the name as typed", async () => {
    rendered(<OperatorCampaignsPage />);
    expect(await screen.findByText("Signature NDA France 2026")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Tous les utilisateurs")).toBeInTheDocument();
    expect(screen.getByText("2 document(s)")).toBeInTheDocument();
    expect(screen.getByText("02/10/2026")).toBeInTheDocument();
  });

  it("shows them in English, with the same name and the same date", async () => {
    await setLocale("en");
    rendered(<OperatorCampaignsPage />);
    expect(await screen.findByText("Signature NDA France 2026")).toBeInTheDocument();
    expect(screen.getByText("All users")).toBeInTheDocument();
    expect(screen.getByText("2 documents")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Signed documents" })).toBeInTheDocument();
    expect(screen.getByText("02/10/2026")).toBeInTheDocument();
  });
});

describe("administration", () => {
  it("words the users page in English and leaves each person's data alone", async () => {
    await setLocale("en");
    vi.mocked(api.get).mockResolvedValue([
      {
        id: "u1", email: "jean.dupont@entreprise.fr", display_name: "Jean Dupont", active: true,
        manually_disabled: false, external: false, source: "ldap", last_login_at: null,
        roles: ["SIGNER"], can_delete: false,
        delete_blockers: ["3 signature(s)", "géré par la source « ldap »"],
      },
    ]);
    rendered(<AdminUsersPage />);
    expect(await screen.findByText("Add someone by email")).toBeInTheDocument();
    const row = screen.getByTestId("user-jean.dupont@entreprise.fr");
    expect(row).toHaveTextContent("Jean Dupont");
    expect(row).toHaveTextContent("LDAP");
    expect(row).toHaveTextContent("Never signed in");
    expect(row).toHaveTextContent("Kept — 3 signatures ; managed by the source “ldap”");
    expect(screen.getByRole("checkbox", { name: "Operator — jean.dupont@entreprise.fr" })).toBeInTheDocument();
  });

  it("words a directory connector in English and keeps the name of its sources", async () => {
    await setLocale("en");
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.endsWith("/sources")) {
        return [{ source: "ldap", configured: false, active: false, fields: {}, sync_interval_minutes: null, spec: null }];
      }
      return [];
    });
    rendered(<AdminDirectoryPage />);
    expect(await screen.findByRole("heading", { name: /Directory/ })).toBeInTheDocument();
    expect(screen.getByText("No directory configured. Choose Microsoft Entra ID, Google Workspace or LDAP / OpenLDAP below.")).toBeInTheDocument();
  });
});

describe("dialogs", () => {
  it.each([
    ["fr", "Changer le mot de passe", "Mot de passe actuel", "Plus tard"],
    ["en", "Change password", "Current password", "Later"],
  ])("labels the password dialog in %s", async (locale, title, current, later) => {
    await setLocale(locale);
    render(<ChangePasswordDialog onClose={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    expect(screen.getByLabelText(current)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: later })).toBeInTheDocument();
  });

  it("says the two passwords differ in the active language", async () => {
    await setLocale("en");
    const user = userEvent.setup();
    render(<ChangePasswordDialog onClose={vi.fn()} />);
    await user.type(screen.getByLabelText("Current password"), "old-password-1");
    await user.type(screen.getByLabelText("New password"), "a-new-long-password");
    await user.type(screen.getByLabelText("Confirm new password"), "another-long-password");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("The two new passwords do not match."));
    expect(api.post).not.toHaveBeenCalled();
  });
});
