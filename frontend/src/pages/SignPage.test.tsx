import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SignPage from "./SignPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), del: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const draft = (id: string, name: string) => ({
  id, name, status: "DRAFT", created_at: id, documents: [], roles: [],
});

describe("SignPage — requests being prepared", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue([draft("c1", "PSSI 2026"), draft("c2", "Charte")]);
    vi.mocked(api.del).mockResolvedValue({});
  });

  it("deletes one of them after a second click, and keeps the other", async () => {
    render(<MemoryRouter><SignPage /></MemoryRouter>);
    const row = await screen.findByTestId("draft-c1");
    fireEvent.click(within(row).getByRole("button", { name: "Supprimer" }));
    expect(api.del).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByRole("button", { name: "Oui, supprimer cette demande" }));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith("/campaigns/c1"));
    await waitFor(() => expect(screen.queryByTestId("draft-c1")).toBeNull());
    expect(screen.getByTestId("draft-c2")).toBeInTheDocument();
  });
});
