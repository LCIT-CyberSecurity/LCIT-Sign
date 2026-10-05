import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminSigningKeysPage from "./AdminSigningKeysPage";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

const keys = [
  {
    key_id: "abc123", public_key_hex: "00", status: "ACTIVE",
    created_at: "2026-01-01T00:00:00Z", activated_at: null, retired_at: null, revoked_at: null,
  },
  {
    key_id: "old999", public_key_hex: "11", status: "REVOKED",
    created_at: "2025-01-01T00:00:00Z", activated_at: null, retired_at: null,
    revoked_at: "2026-02-01T00:00:00Z",
  },
];

describe("AdminSigningKeysPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(keys);
    vi.mocked(api.post).mockResolvedValue({});
  });

  it("asks for confirmation before revoking, and never offers it for a revoked key", async () => {
    const user = userEvent.setup();
    render(<AdminSigningKeysPage />);
    await screen.findByText("abc123");
    expect(screen.getAllByRole("button", { name: "Révoquer" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Révoquer" }));
    expect(api.post).not.toHaveBeenCalled(); // first click only asks
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Révoquer" }));
    await user.click(screen.getByRole("button", { name: "Confirmer la révocation" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/admin/signing-keys/abc123/revoke"),
    );
  });
});
