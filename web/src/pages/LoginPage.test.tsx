import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "./LoginPage";
import { api } from "../api/client";

const refresh = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ refresh }) }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

let options: unknown = { sso: true, provider: "generic", local: true };
let branding: unknown = { has_logo: false, logo_sha256: null };

beforeEach(() => {
  vi.clearAllMocks();
  options = { sso: true, provider: "generic", local: true };
  branding = { has_logo: false, logo_sha256: null };
  vi.mocked(api.get).mockImplementation(async (path: string) =>
    path === "/auth/options" ? options : branding,
  );
});

describe("<LoginPage />", () => {
  it.each([
    ["entra", "Continuer avec Microsoft"],
    ["google", "Continuer avec Google"],
    ["generic", "Continuer avec le SSO"],
  ])("offers the %s button first, and the local form only behind \"Connexion locale\"", async (provider, label) => {
    options = { sso: true, provider, local: true };
    render(<LoginPage />);
    const sso = await screen.findByRole("link", { name: new RegExp(label) });
    expect(sso).toHaveAttribute("href", "/api/auth/login");
    expect(sso.querySelector("svg")).not.toBeNull();
    const local = screen.getByTestId("local-login");
    expect(local.tagName).toBe("DETAILS");
    expect(local).not.toHaveAttribute("open");
    expect(local).toHaveTextContent("Connexion locale");
    expect(screen.getByRole("heading", { level: 1, name: "Connexion" })).toBeInTheDocument();
  });

  it("says it is the CrashTest stack, with the convention of its accounts, and only there", async () => {
    options = { sso: true, provider: "generic", local: true, crashtest: true };
    const { unmount } = render(<LoginPage />);
    expect(await screen.findByTestId("crashtest-note")).toHaveTextContent("mot de passe = prénom en minuscules");
    unmount();
    options = { sso: true, provider: "generic", local: true, crashtest: false };
    render(<LoginPage />);
    await screen.findByTestId("sso-button");
    expect(screen.queryByTestId("crashtest-note")).toBeNull();
  });

  it("offers the CrashTest mock SSO next to the real one", async () => {
    options = { sso: true, provider: "entra", local: true, crashtest: true, test_sso: true };
    render(<LoginPage />);
    expect(await screen.findByTestId("sso-button")).toHaveTextContent("Continuer avec Microsoft");
    expect(screen.getByTestId("test-sso-button")).toHaveAttribute("href", "/api/auth/login?test_sso=true");
  });

  it("shows only the local form when no SSO is configured", async () => {
    options = { sso: false, provider: null, local: true };
    render(<LoginPage />);
    expect(await screen.findByLabelText("Mot de passe")).toBeInTheDocument();
    expect(screen.queryByTestId("sso-button")).toBeNull();
    expect(screen.getByTestId("local-login").tagName).toBe("DIV");
  });

  it("says so when there is no way in at all", async () => {
    options = { sso: false, provider: null, local: false };
    render(<LoginPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Aucune méthode de connexion");
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });

  it("signs in with an identifier or an e-mail and a password", async () => {
    const user = userEvent.setup();
    options = { sso: false, provider: null, local: true };
    vi.mocked(api.post).mockResolvedValue(undefined);
    render(<LoginPage />);
    await user.type(await screen.findByLabelText("Identifiant ou e-mail"), "bob.dupont@lcit-test.local");
    await user.type(screen.getByLabelText("Mot de passe"), "bob");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/auth/local-login", {
        username: "bob.dupont@lcit-test.local",
        password: "bob",
      }),
    );
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("says one thing, plainly, and nothing more", async () => {
    render(<LoginPage />);
    await screen.findByTestId("sso-button");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Signez facilement vos documents !");
    // No pitch, no eyebrow, no three-step explainer next to it.
    expect(screen.queryByText(/Diffusez vos chartes/)).toBeNull();
    expect(screen.queryByText("SIGNATURE INTERNE")).toBeNull();
    for (const step of ["Consulter", "Prouver"]) {
      expect(screen.queryByText(step)).toBeNull();
    }
  });

  it("shows the LCIT logo, as EARE's sign-in does", () => {
    render(<LoginPage />);
    expect(screen.getByAltText("LCIT")).toHaveAttribute("src", "/lcit-logo.png");
  });

  it("shows the company's own logo, and no LCIT name beside it, when an administrator set one", async () => {
    branding = { has_logo: true, logo_sha256: "b".repeat(64) };
    render(<LoginPage />);
    expect(await screen.findByAltText("Logo")).toHaveAttribute("src", `/api/branding/logo?v=${"b".repeat(64)}`);
    expect(screen.queryByAltText("LCIT")).toBeNull();
    // The vendor line in the footer stays; the company block no longer carries the LCIT name.
    expect(document.querySelector(".auth-company")?.textContent).not.toContain("LCIT Cybersecurity");
  });
});
