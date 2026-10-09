import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import AdminIdentityPage from "./AdminIdentityPage";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } };
});

const providers = [
  { provider: "entra", configured: true, active: true, client_id: "c", tenant_id: "t", redirect_uri: "https://x/api/auth/callback" },
  { provider: "google", configured: true, active: false, client_id: "g.apps.googleusercontent.com", tenant_id: "", redirect_uri: "https://x/api/auth/callback" },
];
const spec = (label: string) => ({
  label, description: label, fields: [],
  secret: { name: "s", label: "Secret", help: "", example: "", kind: "password", options: [], default: "", required: true },
});
const sources = [
  { source: "local", active: false, configured: true, fields: {}, sync_interval_minutes: null },
  { source: "entra", active: true, configured: true, fields: {}, sync_interval_minutes: null, spec: spec("Microsoft Entra ID") },
];

describe("AdminIdentityPage — Identités & accès", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/admin/login-providers") return providers;
      if (path.endsWith("/status")) return { managed_by_environment: false };
      if (path.endsWith("/sources")) return sources;
      return [];
    });
  });

  it("puts Connexion and Annuaire on one page, each with a single active entry", async () => {
    render(<AdminIdentityPage />);
    expect(await screen.findByRole("heading", { level: 1, name: /Identités & accès/ })).toBeInTheDocument();
    const login = await screen.findByTestId("identity-login");
    expect(within(login).getByRole("heading", { name: /Connexion/ })).toBeInTheDocument();
    expect(within(login).getAllByText(/\(actif\)/)).toHaveLength(1);
    expect(within(login).getByTestId("login-provider-google")).toHaveTextContent("(configuré, inactif)");
    expect(await screen.findByRole("heading", { name: /Annuaire/ })).toBeInTheDocument();
    expect(within(await screen.findByTestId("source-entra")).getByTestId("source-state")).toHaveTextContent("Actif");
    expect(within(screen.getByTestId("source-local")).getByTestId("source-state")).toHaveTextContent("Inactif");
  });

  it("never shows a stored secret", async () => {
    render(<AdminIdentityPage />);
    await screen.findByTestId("login-provider-entra");
    for (const input of screen.getAllByLabelText(/Secret client/)) {
      expect((input as HTMLInputElement).value).toBe("");
    }
  });
});
