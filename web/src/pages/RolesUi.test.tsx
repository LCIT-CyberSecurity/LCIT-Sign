import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CampaignSigners from "../components/CampaignSigners";
import SignerAssignmentsPage from "./SignerAssignmentsPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), del: vi.fn(), put: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { display_name: "Erwan Petit" } }) }));

const users = [
  { id: "u1", email: "rssi@lcit.fr", display_name: "Rita Rssi" },
  { id: "u2", email: "bob@lcit.fr", display_name: "Bob Dupont" },
];

const draft = (roles: unknown[]) =>
  ({
    id: "c1", name: "PSSI 2026", status: "DRAFT", roles, documents: [], roles_required: 1,
  }) as never;

describe("choosing who signs, among the users", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.put).mockResolvedValue({});
  });

  it("proposes 'every recipient' at once, then saves the people in order as each is chosen", async () => {
    const onSaved = vi.fn();
    render(<CampaignSigners campaign={draft([])} users={users} onSaved={onSaved} />);

    // Nothing chosen yet: everyone signs their own copy, saved so documents can be prepared.
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith("/campaigns/c1/signers", {
        signers: [{ role: 1, mode: "EACH", user_id: null }],
      }),
    );

    // A named person goes before the list of recipients, which always signs last.
    fireEvent.click(screen.getByRole("button", { name: /^Ajouter une personne$/ }));
    expect(api.put).toHaveBeenCalledTimes(1); // a row with nobody chosen is not saved
    fireEvent.change(screen.getByLabelText("Qui signe en position 1 ?"), { target: { value: "u1" } });
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith("/campaigns/c1/signers", {
        signers: [
          { role: 1, mode: "FIXED", user_id: "u1" },
          { role: 2, mode: "EACH", user_id: null },
        ],
      }),
    );
    // The list of recipients cannot be added a second time.
    expect(screen.queryByRole("button", { name: /Ajouter « Chaque destinataire »/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^Ajouter une personne$/ }));
    fireEvent.change(screen.getByLabelText("Qui signe en position 2 ?"), { target: { value: "u2" } });
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith("/campaigns/c1/signers", {
        signers: [
          { role: 1, mode: "FIXED", user_id: "u1" },
          { role: 2, mode: "FIXED", user_id: "u2" },
          { role: 3, mode: "EACH", user_id: null },
        ],
      }),
    );
  });

  it("does not offer the same person twice", () => {
    render(
      <CampaignSigners
        campaign={draft([
          { role: 1, label: "", mode: "FIXED", user_id: "u1", user_display_name: "Rita Rssi" },
          { role: 2, label: "", mode: "EACH", user_id: null, user_display_name: null },
        ])}
        users={users}
        onSaved={vi.fn()}
      />,
    );
    const second = screen.getByLabelText("Qui signe en position 2 ?");
    expect(second.querySelector('option[value="u1"]')).toBeDisabled();
    expect(second.querySelector('option[value="u2"]')).not.toBeDisabled();
  });
});

describe("a signer whose turn has not come", () => {
  it("sees the document under 'À venir', with who must sign first", async () => {
    vi.mocked(api.get).mockResolvedValue([
      {
        id: "a1", campaign_id: "c1", campaign_name: "PSSI 2026", document_version_id: "v1",
        document_title: "PSSI", version_label: "1.0", status: "WAITING", assigned_at: "",
        deadline: null, signed_at: null, signature_id: null, waiting_on: ["Rita Rssi"],
      },
    ]);
    render(
      <MemoryRouter>
        <SignerAssignmentsPage />
      </MemoryRouter>,
    );
    const upcoming = await screen.findByTestId("upcoming");
    expect(upcoming).toHaveTextContent("PSSI");
    expect(upcoming).toHaveTextContent("Rita Rssi");
    expect(screen.getByTestId("count-pending")).toHaveTextContent("0");
  });
});
