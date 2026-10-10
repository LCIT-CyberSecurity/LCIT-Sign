import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminLoginPage from "./AdminLoginPage";

const items = [
  { provider: "entra", configured: false, active: false, client_id: "", tenant_id: "", redirect_uri: "https://x/api/auth/callback" },
  { provider: "google", configured: true, active: true, client_id: "1.apps.googleusercontent.com", tenant_id: "", redirect_uri: "https://x/api/auth/callback" },
];

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } };
});
import { api } from "../api/client";

describe("AdminLoginPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.endsWith("/status") ? { managed_by_environment: false } : items,
    );
    vi.mocked(api.post).mockResolvedValue({});
    vi.mocked(api.put).mockResolvedValue({});
    vi.mocked(api.del).mockResolvedValue(undefined);
  });

  it("shows the redirect address, which providers are on, and never a stored secret", async () => {
    render(<AdminLoginPage />);
    const google = await screen.findByTestId("login-provider-google");
    expect(google).toHaveTextContent("(actif)");
    expect(screen.getByTestId("login-provider-entra")).toHaveTextContent("(non configuré)");
    expect(screen.getAllByText("https://x/api/auth/callback")).toHaveLength(2);
    expect(screen.getAllByLabelText(/Secret client/).every((i) => (i as HTMLInputElement).value === "")).toBe(true);
  });

  it("sends the identifiers and the secret once, then empties the secret", async () => {
    render(<AdminLoginPage />);
    await screen.findByTestId("login-provider-entra");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("ID du tenant (annuaire)"), "73405479-f042-45d7-8149-c90341261b65");
    await user.type(screen.getByLabelText("ID de l'application (client)"), "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3");
    const secret = screen.getAllByLabelText(/Secret client/)[0] as HTMLInputElement;
    await user.type(secret, "la-valeur");
    await user.click(screen.getAllByRole("button", { name: "Enregistrer" })[0]);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/admin/login-providers/entra", {
        client_id: "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3",
        tenant_id: "73405479-f042-45d7-8149-c90341261b65",
        client_secret: "la-valeur",
      }),
    );
  });

  it("can remove a provider", async () => {
    render(<AdminLoginPage />);
    await screen.findByTestId("login-provider-google");
    await userEvent.setup().click(screen.getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith("/admin/login-providers/google"));
  });

  it("only one provider is active: a configured one that is not can be made the one in use", async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.endsWith("/status")
        ? { managed_by_environment: false }
        : [
            { ...items[0], configured: true, active: false, client_id: "c", tenant_id: "t" },
            { ...items[1], active: true },
          ],
    );
    render(<AdminLoginPage />);
    expect(await screen.findByTestId("login-provider-entra")).toHaveTextContent("(configuré, inactif)");
    expect(screen.getByTestId("login-provider-google")).toHaveTextContent("(actif)");
    await userEvent.setup().click(screen.getByRole("button", { name: "Utiliser ce fournisseur" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/admin/login-providers/entra/activate"));
  });

  it("says when the server's variables decide the SSO", async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.endsWith("/status") ? { managed_by_environment: true } : items,
    );
    render(<AdminLoginPage />);
    expect(await screen.findByTestId("sso-fixed-by-server")).toHaveTextContent("imposé par la configuration du serveur");
  });

  it("tests the saved provider, read-only, and shows each step with the provider's code", async () => {
    vi.mocked(api.post).mockResolvedValue({
      source: "google",
      status: "ERROR",
      checks: [
        { name: "discovery", status: "OK", code: null, provider_code: null, message: "ok", action: null },
        {
          name: "credentials", status: "ERROR", code: "INVALID_CREDENTIALS", provider_code: "invalid_client",
          message: "Google refuse l'ID client ou le secret.", action: "Copiez l'ID client et le secret.",
        },
      ],
      access_token: "never-shown",
    });
    render(<AdminLoginPage />);
    const google = await screen.findByTestId("login-provider-google");
    // Only a configured provider can be tested.
    expect(screen.getByTestId("login-provider-entra")).not.toHaveTextContent("Tester la connexion");
    const user = userEvent.setup();
    await user.click(within(google).getByRole("button", { name: "Tester la connexion" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/admin/login-providers/google/test"));
    expect(await within(google).findByTestId("check-credentials")).toHaveTextContent("invalid_client");
    expect(within(google).getByTestId("check-credentials")).toHaveTextContent("Action recommandée");
    expect(within(google).getByTestId("check-discovery")).toHaveTextContent("Accès au fournisseur");
    expect(document.body.innerHTML).not.toContain("never-shown");
  });
});
