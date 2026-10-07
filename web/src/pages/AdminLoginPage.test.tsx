import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminLoginPage from "./AdminLoginPage";

const items = [
  { provider: "entra", configured: false, client_id: "", tenant_id: "", redirect_uri: "https://x/api/auth/callback" },
  { provider: "google", configured: true, client_id: "1.apps.googleusercontent.com", tenant_id: "", redirect_uri: "https://x/api/auth/callback" },
];

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), put: vi.fn(), del: vi.fn() } };
});
import { api } from "../api/client";

describe("AdminLoginPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(items);
    vi.mocked(api.put).mockResolvedValue({});
    vi.mocked(api.del).mockResolvedValue(undefined);
  });

  it("shows the redirect address, which providers are on, and never a stored secret", async () => {
    render(<AdminLoginPage />);
    const google = await screen.findByTestId("login-provider-google");
    expect(google).toHaveTextContent("(activé)");
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

  it("can switch a provider off", async () => {
    render(<AdminLoginPage />);
    await screen.findByTestId("login-provider-google");
    await userEvent.setup().click(screen.getByRole("button", { name: "Désactiver" }));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith("/admin/login-providers/google"));
  });
});
