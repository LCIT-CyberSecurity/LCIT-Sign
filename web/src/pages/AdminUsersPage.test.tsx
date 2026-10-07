import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import AdminUsersPage from "./AdminUsersPage";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminUsersPage />
    </MemoryRouter>,
  );
}

describe("AdminUsersPage — adding someone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue([]);
    vi.mocked(api.post).mockResolvedValue({});
  });

  it("adds a person for the SSO by default: no password asked, and the roles chosen", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Adresse e-mail"), "ann@corp.test");
    expect(screen.queryByLabelText("Mot de passe initial")).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Préparateur" }));
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/admin/users", {
        email: "ann@corp.test", given_name: "", family_name: "", roles: ["SIGNER", "PREPARER"],
        auth_method: "sso", password: undefined,
      }),
    );
  });

  it("asks for a password for a local account, sends it once and clears it", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Adresse e-mail"), "bob@corp.test");
    await user.click(screen.getByRole("radio", { name: /Compte local/ }));
    const password = screen.getByLabelText("Mot de passe initial");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toBeRequired();
    await user.type(password, "FAKE-INITIAL-PW");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/admin/users", expect.objectContaining({
        auth_method: "local", password: "FAKE-INITIAL-PW",
      })),
    );
    expect(document.body.innerHTML).not.toContain("FAKE-INITIAL-PW");
    expect(await screen.findByRole("status")).toHaveTextContent("changera son mot de passe");
  });
});
