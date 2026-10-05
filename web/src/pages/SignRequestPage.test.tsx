import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignRequestPage from "./SignRequestPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const prepared = { version_id: "v1", title: "PSSI", version_label: "1.0", status: "DRAFT", elements: 2 };
const everyone = { role: 1, label: "", mode: "EACH", user_id: null, user_display_name: null };

const campaign = (documents: unknown[] = [prepared], roles: unknown[] = [everyone]) => ({
  id: "c1", name: "PSSI 2026", description: "", status: "DRAFT", target_mode: "", created_at: "",
  launch_at: null, deadline: null, closed_at: null, document_version_ids: [], roles_required: 1,
  roles, documents, assignment_counts: {}, policies: {}, renewal_of_campaign_id: null,
});

function open(step = 1, documents?: unknown[]) {
  vi.mocked(api.get).mockImplementation(async (path: string) =>
    path === "/campaigns/c1" ? campaign(documents) : [],
  );
  render(
    <MemoryRouter initialEntries={[`/sign/c1?step=${step}`]}>
      <Routes>
        <Route path="/sign/:id" element={<SignRequestPage />} />
        <Route path="/campaigns/:id" element={<p>suivi</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const stepButton = (name: RegExp) => screen.getByRole("button", { name });

describe("SignRequestPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.post).mockResolvedValue({ population_count: 3 });
    vi.mocked(api.put).mockResolvedValue({});
  });

  it("goes through the three screens: signers and reminders, documents, then sending", async () => {
    open(1);
    // Screen 1: who signs (in order), the mail merge list, deadline, reminders, renewal.
    expect(await screen.findByTestId("signers-card")).toBeInTheDocument();
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Relances automatiques");
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Renouvellement");
    expect(screen.queryByTestId("campaign-documents")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Suivant : les documents/ }));
    expect(await screen.findByTestId("campaign-documents")).toBeInTheDocument();
    expect(screen.queryByTestId("signers-card")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ }));
    expect(await screen.findByTestId("recap-card")).toHaveTextContent("PSSI — 2 élément(s) placé(s)");
    expect(screen.getByTestId("recap-card")).toHaveTextContent("Chaque destinataire");
  });

  it("sets the deadline and reminders, then sends and goes to the follow-up", async () => {
    open(1);
    await screen.findByTestId("policy-card");
    // A reminder before the deadline needs a deadline.
    fireEvent.change(screen.getByLabelText(/Relance avant échéance/), { target: { value: "2" } });
    fireEvent.click(stepButton(/Vérifier et envoyer/));
    await screen.findByTestId("recap-card");
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    expect(await screen.findByText(/indiquez l.échéance/)).toBeInTheDocument();
    expect(vi.mocked(api.post).mock.calls.some((c) => c[0] === "/campaigns/c1/launch")).toBe(false);

    fireEvent.click(stepButton(/Signataires et relances/));
    fireEvent.change(await screen.findByLabelText(/Échéance/), { target: { value: "2030-01-31" } });
    fireEvent.click(stepButton(/Vérifier et envoyer/));
    await screen.findByTestId("recap-card");
    expect(screen.getByTestId("recap-card")).toHaveTextContent("Relance 2 jour(s) avant l'échéance");
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    await waitFor(() => expect(screen.getByText("suivi")).toBeInTheDocument());
    const call = vi.mocked(api.post).mock.calls.find((c) => c[0] === "/campaigns/c1/launch")!;
    const body = call[1] as { deadline: string; reminder_before_deadline_days: number };
    expect(body.reminder_before_deadline_days).toBe(2);
    expect(body.deadline.startsWith("2030-01-3")).toBe(true);
  });

  it("will not send before every document has its elements, and says which one", async () => {
    open(3, [prepared, { ...prepared, version_id: "v2", title: "Charte", elements: 0 }]);
    const blocker = await screen.findByTestId("launch-blocker");
    expect(blocker).toHaveTextContent("Placez les éléments");
    expect(blocker).toHaveTextContent("Charte");
    expect(blocker).not.toHaveTextContent("PSSI");
    expect(screen.getByRole("button", { name: /Envoyer pour signature/ })).toBeDisabled();
  });

  it("asks for a document when there is none", async () => {
    open(3, []);
    expect(await screen.findByTestId("launch-blocker")).toHaveTextContent("Ajoutez au moins un document");
    expect(screen.getByRole("button", { name: /Envoyer pour signature/ })).toBeDisabled();
  });

  it("asks to choose the people when the mail merge list is empty", async () => {
    vi.mocked(api.post).mockResolvedValue({ population_count: 0 });
    open(3);
    expect(await screen.findByTestId("launch-blocker")).toHaveTextContent("Choisissez les personnes");
  });
});
