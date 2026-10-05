import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignRequestPage from "./SignRequestPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const campaign = {
  id: "c1", name: "PSSI 2026", description: "", status: "DRAFT", target_mode: "", created_at: "",
  launch_at: null, deadline: null, closed_at: null, document_version_ids: [], roles_required: 1,
  roles: [], documents: [], assignment_counts: {}, policies: {}, renewal_of_campaign_id: null,
};

function open() {
  render(
    <MemoryRouter initialEntries={["/sign/c1"]}>
      <Routes>
        <Route path="/sign/:id" element={<SignRequestPage />} />
        <Route path="/campaigns/:id" element={<p>suivi</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SignRequestPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockImplementation(async (path: string) => (path === "/campaigns/c1" ? campaign : []));
    vi.mocked(api.post).mockResolvedValue({ population_count: 0 });
  });

  it("sets the deadline, reminders and renewal before sending, then goes to the follow-up", async () => {
    open();
    const card = await screen.findByTestId("policy-card");
    expect(card).toHaveTextContent("Relances automatiques");
    expect(card).toHaveTextContent("Renouvellement");

    // A reminder before the deadline needs a deadline.
    fireEvent.change(screen.getByLabelText(/Relance avant échéance/), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    expect(await screen.findByText(/indiquez l.échéance/)).toBeInTheDocument();
    expect(vi.mocked(api.post).mock.calls.some((c) => c[0] === "/campaigns/c1/launch")).toBe(false);

    fireEvent.change(screen.getByLabelText(/Échéance/), { target: { value: "2030-01-31" } });
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    await waitFor(() => expect(screen.getByText("suivi")).toBeInTheDocument());
    const call = vi.mocked(api.post).mock.calls.find((c) => c[0] === "/campaigns/c1/launch")!;
    const body = call[1] as { deadline: string; reminder_before_deadline_days: number };
    expect(body.reminder_before_deadline_days).toBe(2);
    expect(body.deadline.startsWith("2030-01-3")).toBe(true);
  });
});
