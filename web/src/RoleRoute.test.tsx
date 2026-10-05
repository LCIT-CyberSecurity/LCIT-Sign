import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

const auth = vi.hoisted(() => ({
  current: {
    user: null as null | { display_name: string; email: string; roles: string[] },
    roles: [] as string[],
  },
}));

vi.mock("./auth/AuthContext", () => ({
  useAuth: () => ({
    user: auth.current.user,
    loading: false,
    hasRole: (role: string) => auth.current.roles.includes(role),
    refresh: vi.fn(),
  }),
}));
vi.mock("./api/client", () => ({
  api: { get: vi.fn().mockResolvedValue([]), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  ApiError: class extends Error {},
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("role-based navigation (the UI only hides; the API enforces)", () => {
  it("shows the login page to an anonymous visitor", () => {
    auth.current = { user: null, roles: [] };
    renderAt("/");
    expect(screen.getByText(/Se connecter avec le SSO/)).toBeInTheDocument();
  });

  it("does not offer operator or admin sections to a plain signer", () => {
    auth.current = { user: { display_name: "Erwan", email: "x@lcit-test.local", roles: ["SIGNER"] }, roles: ["SIGNER"] };
    renderAt("/");
    expect(screen.queryByText("Suivi")).not.toBeInTheDocument();
    expect(screen.queryByText("Diagnostic")).not.toBeInTheDocument();
  });

  it("redirects a signer away from an admin URL", () => {
    auth.current = { user: { display_name: "Erwan", email: "x@lcit-test.local", roles: ["SIGNER"] }, roles: ["SIGNER"] };
    renderAt("/admin/diagnostics");
    expect(screen.queryByRole("heading", { name: /Diagnostic/ })).not.toBeInTheDocument();
  });

  it("offers the admin section, including Diagnostic, to an administrator", () => {
    auth.current = { user: { display_name: "Alice", email: "x@lcit-test.local", roles: ["ADMIN"] }, roles: ["ADMIN"] };
    renderAt("/");
    expect(screen.getByText("Diagnostic")).toBeInTheDocument();
    expect(screen.getByText("Annuaire")).toBeInTheDocument();
  });

  it("offers operators campaigns but not administration", () => {
    auth.current = { user: { display_name: "Diane", email: "x@lcit-test.local", roles: ["OPERATOR"] }, roles: ["OPERATOR"] };
    renderAt("/");
    expect(screen.getByText("Suivi")).toBeInTheDocument();
    expect(screen.queryByText("Administration")).not.toBeInTheDocument();
  });
});
