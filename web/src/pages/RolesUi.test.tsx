import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import OperatorCampaignDetailPage from "./OperatorCampaignDetailPage";
import SignerAssignmentsPage from "./SignerAssignmentsPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), del: vi.fn(), put: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { display_name: "Erwan Petit" } }) }));

const campaign = {
  id: "c1", name: "PSSI 2026", description: "", status: "DRAFT", target_mode: "", created_at: "",
  launch_at: null, deadline: null, closed_at: null, document_version_ids: ["v1"],
  roles_required: 2,
  roles: [
    { role: 1, label: "RSSI", mode: null, user_id: null, user_display_name: null },
    { role: 2, label: "Collaborateur", mode: null, user_id: null, user_display_name: null },
  ],
  assignment_counts: {}, policies: {}, renewal_of_campaign_id: null,
};

describe("signer roles at launch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/campaigns/c1") return campaign;
      if (path === "/campaigns/_meta/users")
        return [{ id: "u1", email: "rssi@lcit.fr", display_name: "Rita Rssi" }];
      return [];
    });
    vi.mocked(api.post).mockResolvedValue({});
  });

  it("asks who each named role is and sends the answer with the launch", async () => {
    render(
      <MemoryRouter initialEntries={["/campaigns/c1"]}>
        <Routes>
          <Route path="/campaigns/:id" element={<OperatorCampaignDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const card = await screen.findByTestId("roles-card");
    expect(card).toHaveTextContent("1. RSSI");
    expect(card).toHaveTextContent("2. Collaborateur");

    // Launching without naming the RSSI is refused on the spot.
    fireEvent.click(screen.getByRole("button", { name: /Lancer la campagne/ }));
    expect(await screen.findByText(/Choisissez une personne pour le signataire 1 \(RSSI\)/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalledWith("/campaigns/c1/launch", expect.anything());

    fireEvent.change(screen.getByLabelText("Qui est RSSI ?"), { target: { value: "u1" } });
    fireEvent.click(screen.getByRole("button", { name: /Lancer la campagne/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/campaigns/c1/launch", expect.anything()));
    const body = vi.mocked(api.post).mock.calls.find((c) => c[0] === "/campaigns/c1/launch")![1] as {
      roles: unknown[];
    };
    expect(body.roles).toEqual([
      { role: 1, label: "RSSI", mode: "FIXED", user_id: "u1" },
      { role: 2, label: "Collaborateur", mode: "EACH", user_id: null },
    ]);
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
