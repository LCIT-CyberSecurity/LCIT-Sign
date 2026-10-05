import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import LoginPage from "./LoginPage";

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
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/signé et prouvé/);
    for (const step of ["Consulter", "Signer", "Prouver"]) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
  });

  it("shows the LCIT logo, as EARE's sign-in does", () => {
    render(<LoginPage />);
    expect(screen.getByAltText("LCIT")).toHaveAttribute("src", "/lcit-logo.png");
  });
});
