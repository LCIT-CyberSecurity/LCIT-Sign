import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LoginPage from "./LoginPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { get: vi.fn() } }));

beforeEach(() => {
  vi.mocked(api.get).mockResolvedValue({ has_logo: false, logo_sha256: null });
});

describe("<LoginPage />", () => {
  it("offers SSO as the only way in — no password field", () => {
    render(<LoginPage />);
    const sso = screen.getByRole("link", { name: /Se connecter avec le SSO/ });
    expect(sso).toHaveAttribute("href", "/api/auth/login");
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Connexion" })).toBeInTheDocument();
  });

  it("explains the product and its three steps", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/Facilitez la signature\s*de vos documents/);
    for (const step of ["Consulter", "Signer", "Prouver"]) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
  });

  it("shows the LCIT logo, as EARE's sign-in does", () => {
    render(<LoginPage />);
    expect(screen.getByAltText("LCIT")).toHaveAttribute("src", "/lcit-logo.png");
  });

  it("shows the company's own logo, and no LCIT name beside it, when an administrator set one", async () => {
    vi.mocked(api.get).mockResolvedValue({ has_logo: true, logo_sha256: "b".repeat(64) });
    render(<LoginPage />);
    expect(await screen.findByAltText("Logo")).toHaveAttribute("src", `/api/branding/logo?v=${"b".repeat(64)}`);
    expect(screen.queryByAltText("LCIT")).toBeNull();
    // The vendor line in the footer stays; the company block no longer carries the LCIT name.
    expect(document.querySelector(".auth-company")?.textContent).not.toContain("LCIT Cybersecurity");
  });
});
