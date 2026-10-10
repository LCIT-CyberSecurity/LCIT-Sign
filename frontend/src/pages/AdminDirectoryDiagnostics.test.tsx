import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminDirectoryPage from "./AdminDirectoryPage";
import { api } from "../api/client";
import type { DirectorySyncRun, DirectoryTestResult } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } };
});

const spec = (label: string) => ({
  label,
  description: `Lit les utilisateurs de ${label}.`,
  fields: [],
  secret: { name: "s", label: "Secret", help: "Un secret.", example: "", kind: "password", options: [], default: "", required: true },
});

const sources = [
  { source: "entra", configured: false, fields: {}, sync_interval_minutes: null, spec: spec("Microsoft Entra ID") },
  { source: "google", active: true, configured: true, fields: { admin_email: "a@corp.test" }, sync_interval_minutes: 60, spec: spec("Google Workspace") },
  { source: "ldap", configured: true, active: false, fields: {}, sync_interval_minutes: null, spec: spec("LDAP / Active Directory") },
];

const run = (patch: Partial<DirectorySyncRun>): DirectorySyncRun => ({
  id: "r1", source: "entra", status: "FAILED", started_at: "2026-10-05T10:00:00Z", finished_at: null,
  users_added: 0, users_updated: 0, users_deactivated: 0, groups_added: 0, groups_updated: 0,
  memberships_added: 0, memberships_removed: 0, error: null, ...patch,
});

let runs: DirectorySyncRun[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  runs = [];
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/sources")) return sources;
    if (path.endsWith("/groups")) return [];
    return runs;
  });
});

const ok = (name: string) => ({ name, status: "OK" as const, code: null, provider_code: null, message: "Fait", action: null });

describe("the connection test, on each connector's card", () => {
  it("is offered on a configured connector only, and never on the demonstration directory", async () => {
    render(<AdminDirectoryPage />);
    const entra = await screen.findByTestId("source-entra");
    expect(within(entra).getByRole("button", { name: "Tester la connexion" })).toBeDisabled();
    expect(within(screen.getByTestId("source-google")).getByRole("button", { name: "Tester la connexion" })).toBeEnabled();
    expect(within(screen.getByTestId("source-ldap")).getByRole("button", { name: "Tester la connexion" })).toBeEnabled();
  });

  it("says it is read-only and is not the synchronisation", async () => {
    render(<AdminDirectoryPage />);
    const google = await screen.findByTestId("source-google");
    expect(google).toHaveTextContent("sans rien modifier");
    expect(within(google).getByRole("button", { name: "Tester la connexion" })).not.toBe(
      within(google).getByRole("button", { name: /Synchroniser/ }),
    );
  });

  it("calls the test route only — never the synchronisation — and shows each step as done", async () => {
    const result: DirectoryTestResult = {
      source: "google", status: "OK",
      checks: ["authentication", "service_access", "users_read", "groups_read", "memberships_read"].map(ok),
    };
    vi.mocked(api.post).mockResolvedValue(result);
    render(<AdminDirectoryPage />);
    const google = await screen.findByTestId("source-google");
    await userEvent.setup().click(within(google).getByRole("button", { name: "Tester la connexion" }));
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/admin/directory/sources/google/test");
    const panel = await within(google).findByTestId("connection-test");
    for (const name of ["Authentification", "Accès au service", "Lecture des utilisateurs", "Lecture des groupes", "Lecture des appartenances"]) {
      expect(panel).toHaveTextContent(name);
    }
    expect(within(panel).getByTestId("connection-summary")).toHaveTextContent("Connexion opérationnelle.");
    expect(within(panel).getByTestId("check-users_read")).toHaveAttribute("data-status", "OK");
  });

  it("shows a partial failure with the provider's code and the advice, and keeps the steps that worked", async () => {
    vi.mocked(api.post).mockResolvedValue({
      source: "google", status: "ERROR",
      checks: [
        ok("authentication"), ok("users_read"),
        { name: "groups_read", status: "ERROR", code: "INSUFFICIENT_PERMISSIONS", provider_code: "HTTP 403",
          message: "Lecture des groupes refusée : permission Group.Read.All absente.",
          action: "Vérifier les permissions du connecteur." },
      ],
    } satisfies DirectoryTestResult);
    render(<AdminDirectoryPage />);
    const google = await screen.findByTestId("source-google");
    await userEvent.setup().click(within(google).getByRole("button", { name: "Tester la connexion" }));
    const panel = await within(google).findByTestId("connection-test");
    expect(within(panel).getByTestId("check-users_read")).toHaveAttribute("data-status", "OK");
    const groups = within(panel).getByTestId("check-groups_read");
    expect(groups).toHaveAttribute("data-status", "ERROR");
    expect(groups).toHaveTextContent("permission Group.Read.All absente");
    expect(groups).toHaveTextContent("Code fournisseur : HTTP 403");
    expect(groups).toHaveTextContent("Action recommandée : Vérifier les permissions du connecteur.");
    expect(within(panel).getByTestId("connection-summary")).toHaveTextContent("pas pleinement opérationnelle");
  });

  it("shows a warning as a reserve, not as a failure", async () => {
    vi.mocked(api.post).mockResolvedValue({
      source: "ldap", status: "WARN",
      checks: [ok("bind"), { name: "users_query", status: "WARN", code: "USER_QUERY_ERROR", provider_code: null,
        message: "La requête fonctionne mais ne renvoie aucun utilisateur.", action: "Vérifiez le filtre." }],
    } satisfies DirectoryTestResult);
    render(<AdminDirectoryPage />);
    const ldap = await screen.findByTestId("source-ldap");
    await userEvent.setup().click(within(ldap).getByRole("button", { name: "Tester la connexion" }));
    const panel = await within(ldap).findByTestId("connection-test");
    expect(within(panel).getByTestId("check-users_query")).toHaveAttribute("data-status", "WARN");
    expect(within(panel).getByTestId("connection-summary")).toHaveTextContent("avec des réserves");
  });

  it("only ever shows what a step is meant to say: nothing else the answer might carry", async () => {
    vi.mocked(api.post).mockResolvedValue({
      source: "google", status: "ERROR",
      checks: [{ ...ok("authentication"), status: "ERROR", message: "Refusé.", access_token: "LEAKED-TOKEN", secret: "LEAKED-SECRET" }],
      client_secret: "LEAKED-CLIENT-SECRET",
    });
    const { container } = render(<AdminDirectoryPage />);
    const google = await screen.findByTestId("source-google");
    await userEvent.setup().click(within(google).getByRole("button", { name: "Tester la connexion" }));
    await within(google).findByTestId("connection-test");
    expect(container.textContent).not.toMatch(/LEAKED/);
  });

  it("says when the test itself could not run", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("boom"));
    render(<AdminDirectoryPage />);
    const google = await screen.findByTestId("source-google");
    await userEvent.setup().click(within(google).getByRole("button", { name: "Tester la connexion" }));
    expect(await within(google).findByRole("alert")).toHaveTextContent("Le test de connexion a échoué");
  });
});

describe("the synchronisation history", () => {
  it("offers 'Voir le détail' on a failed run, with the provider's code and the advice", async () => {
    runs = [
      run({
        id: "r1", error: "Microsoft a refusé la connexion (AADSTS7000222) : le secret client a expiré",
        error_detail: {
          message: "Microsoft a refusé la connexion (AADSTS7000222) : le secret client a expiré",
          provider_code: "AADSTS7000222",
          action: "Créer un nouveau secret dans Entra > Certificats et secrets.",
        },
      }),
      run({ id: "r2", status: "SUCCESS", source: "google" }),
    ];
    render(<AdminDirectoryPage />);
    const user = userEvent.setup();
    expect(await screen.findByRole("columnheader", { name: "Détail" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Voir le détail" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Voir le détail" }));
    const detail = screen.getByTestId("run-detail-r1");
    expect(detail).toHaveTextContent("entra");
    expect(detail).toHaveTextContent("le secret client a expiré");
    expect(detail).toHaveTextContent("AADSTS7000222");
    expect(detail).toHaveTextContent("Créer un nouveau secret");
    await user.click(screen.getByRole("button", { name: "Voir le détail" }));
    expect(screen.queryByTestId("run-detail-r1")).toBeNull();
  });

  it("reads an older failed run that only has a plain sentence", async () => {
    runs = [run({ id: "r3", source: "ldap", error: "Erreur LDAP (LDAPSocketOpenError)." })];
    render(<AdminDirectoryPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Voir le détail" }));
    const detail = screen.getByTestId("run-detail-r3");
    expect(detail).toHaveTextContent("Erreur LDAP (LDAPSocketOpenError).");
    expect(detail).not.toHaveTextContent("Code fournisseur");
    expect(detail).not.toHaveTextContent("Action recommandée");
  });

  it("does not break on a failed run with no message at all", async () => {
    runs = [run({ id: "r4", error: null })];
    render(<AdminDirectoryPage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Voir le détail" }));
    expect(screen.getByTestId("run-detail-r4")).toHaveTextContent("Aucun détail enregistré.");
  });
});
