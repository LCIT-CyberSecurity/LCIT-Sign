import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import AdminDirectoryPage, { scheduleLabel } from "./AdminDirectoryPage";
import { api } from "../api/client";

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
  { source: "local", configured: true, fields: {}, sync_interval_minutes: null },
  { source: "entra", configured: false, fields: {}, sync_interval_minutes: null, spec: spec("Microsoft Entra ID") },
  { source: "google", configured: true, fields: { admin_email: "a@corp.test" }, sync_interval_minutes: 60, spec: spec("Google Workspace") },
  { source: "ldap", configured: false, fields: {}, sync_interval_minutes: null, spec: spec("LDAP / Active Directory") },
];

describe("AdminDirectoryPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.endsWith("/sources")) return sources;
      if (path.endsWith("/groups")) return [{ id: "g1", source: "google", name: "SRE", description: "", active: true, member_count: 12 }];
      return [
        { id: "r1", source: "google", status: "SUCCESS", started_at: "2026-10-05T10:00:00Z", finished_at: null,
          users_added: 3, users_updated: 7, users_deactivated: 1, groups_added: 1, groups_updated: 2,
          memberships_added: 5, memberships_removed: 0, error: null },
      ];
    });
  });

  it("shows every source as its own card with its state — not a one-entry selector", async () => {
    render(<AdminDirectoryPage />);
    const entra = await screen.findByTestId("source-entra");
    expect(within(entra).getByTestId("source-state")).toHaveTextContent("Non configurée");
    expect(within(entra).getByRole("button", { name: /Configurer/ })).toBeInTheDocument();
    expect(within(entra).getByRole("button", { name: /Synchroniser/ })).toBeDisabled();

    const google = screen.getByTestId("source-google");
    expect(within(google).getByTestId("source-state")).toHaveTextContent("Configurée");
    expect(within(google).getByRole("button", { name: /Synchroniser/ })).toBeEnabled();
    expect(within(google).getByText(/3 ajouté\(s\), 7 mis à jour, 1 désactivé\(s\)/)).toBeInTheDocument();

    expect(within(screen.getByTestId("source-local")).getByTestId("source-state")).toHaveTextContent("Toujours disponible");
  });

  it("offers LDAP like the others, titled and described by the connector itself", async () => {
    render(<AdminDirectoryPage />);
    const ldap = await screen.findByTestId("source-ldap");
    expect(ldap).toHaveTextContent("LDAP / Active Directory");
    expect(ldap).toHaveTextContent("Lit les utilisateurs de LDAP / Active Directory.");
    expect(within(ldap).getByTestId("source-state")).toHaveTextContent("Non configurée");
    expect(within(ldap).getByRole("button", { name: /Configurer/ })).toBeInTheDocument();
  });

  it("lists the synchronised groups", async () => {
    render(<AdminDirectoryPage />);
    expect(await screen.findByText("SRE")).toBeInTheDocument();
  });

  it("names the schedules in words", () => {
    expect(scheduleLabel(null)).toBe("Manuelle");
    expect(scheduleLabel(60)).toBe("Toutes les heures");
    expect(scheduleLabel(7)).toBe("Toutes les 7 minutes");
  });
});
