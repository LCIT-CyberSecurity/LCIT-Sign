import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AdminUsersPage from "./AdminUsersPage";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } };
});

describe("AdminUsersPage — people come from the directory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue([]);
  });

  it("offers no way to add someone by e-mail, only the import from the directory", async () => {
    render(
      <MemoryRouter>
        <AdminUsersPage />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /Importer depuis l'annuaire/ })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Ajouter un utilisateur" })).toBeNull();
    expect(screen.queryByLabelText("Adresse e-mail")).toBeNull();
    expect(screen.queryByLabelText("Mot de passe initial")).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
