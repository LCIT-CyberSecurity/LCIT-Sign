import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import OperatorCampaignDetailPage from "./OperatorCampaignDetailPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("../components/CampaignOwnership", () => ({ default: () => null }));
vi.mock("../components/CampaignDocuments", () => ({ default: () => null }));
vi.mock("../components/SignedDocuments", () => ({ default: () => null }));
vi.mock("../components/RecipientPicker", () => ({
  default: () => null,
  NO_RECIPIENTS: { allUsers: false, groupIds: [], userIds: [] },
}));

function campaign(status: "ACTIVE" | "CANCELLED", content: boolean, withRecipients = false) {
  return {
    id: "c1",
    name: "PSSI",
    description: "",
    status,
    target_mode: "USERS",
    access: { operate: true, content },
    created_at: "2026-01-01T00:00:00Z",
    launch_at: null,
    scheduled_start: null,
    deadline: null,
    closed_at: null,
    delete_blockers: [],
    document_version_ids: [],
    plan: null,
    roles_required: withRecipients ? 2 : 0,
    roles: withRecipients
      ? [
          { role: 1, mode: "FIXED", label: "RSSI", user_id: "rssi", user_display_name: "RSSI" },
          { role: 2, mode: "EACH", label: "Collaborateur", user_id: null, user_display_name: null },
        ]
      : [],
    documents: [],
    assignment_counts: {},
    policies: {
      reminder_first_days: null,
      reminder_interval_days: null,
      reminder_max_count: null,
      reminder_before_deadline_days: null,
      renewal_every: null,
      renewal_unit: null,
    },
    renewal_of_campaign_id: null,
  };
}

function renderCampaign(value: ReturnType<typeof campaign>) {
  vi.mocked(api.get).mockImplementation(async (path) =>
    (path === "/campaigns/c1" ? value : []) as never,
  );
  return render(
    <MemoryRouter initialEntries={["/campaigns/c1"]}>
      <Routes>
        <Route path="/campaigns/:id" element={<OperatorCampaignDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("campaign follow-up actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lets an operator add recipients to a running fixed-signer plus EACH campaign", async () => {
    renderCampaign(campaign("ACTIVE", false, true));

    expect(await screen.findByText("Ajouter des personnes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter à la campagne" })).toBeInTheDocument();
  });

  it("does not show campaign deletion to an operator without content rights", async () => {
    renderCampaign(campaign("CANCELLED", false));

    await screen.findByText("PSSI");
    expect(screen.queryByRole("button", { name: "Supprimer la campagne" })).toBeNull();
  });

  it("shows deletion to the signer who owns a campaign with no signatures", async () => {
    renderCampaign(campaign("CANCELLED", true));

    expect(await screen.findByRole("button", { name: "Supprimer la campagne" })).toBeInTheDocument();
  });
});
