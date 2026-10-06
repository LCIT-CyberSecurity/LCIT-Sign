import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("goes through the four screens: signers, documents, preparing, then review and send", async () => {
    open(1);
    // Screen 1: who signs (in order), the mail merge list, deadline, reminders, renewal.
    expect(await screen.findByTestId("signers-card")).toBeInTheDocument();
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Date de début");
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Date d'échéance");
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Relance en cas de non-réponse");
    expect(screen.getByTestId("policy-card")).toHaveTextContent("Renouvellement");
    expect(screen.queryByTestId("campaign-documents")).toBeNull();

    // Screen 2: the documents only (no editing of elements here).
    fireEvent.click(screen.getByRole("button", { name: /Suivant : les documents/ }));
    const documents = await screen.findByTestId("campaign-documents");
    expect(documents).toHaveTextContent("PSSI");
    expect(within(documents).queryByRole("link", { name: /Préparer/ })).toBeNull();
    expect(screen.queryByTestId("signers-card")).toBeNull();

    // Screen 3: preparing, a page of its own.
    fireEvent.click(screen.getByRole("button", { name: /Suivant : préparer les documents/ }));
    const prepare = await screen.findByTestId("prepare-step");
    expect(screen.getByTestId("prepare-progress")).toHaveTextContent("1/1");
    expect(within(prepare).getByRole("link", { name: /Modifier/ })).toHaveAttribute(
      "href",
      "/documents/versions/v1/prepare?campaign=c1",
    );

    // Screen 4: review and send.
    fireEvent.click(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ }));
    expect(await screen.findByTestId("recap-card")).toHaveTextContent("PSSI — 2 élément(s) placé(s)");
    expect(screen.getByTestId("recap-card")).toHaveTextContent("Chaque destinataire");
  });

  it("does not leave the preparing screen while a document has no element, and says which", async () => {
    open(3, [prepared, { ...prepared, version_id: "v2", title: "Charte", elements: 0 }]);
    const step = await screen.findByTestId("prepare-step");
    expect(screen.getByTestId("prepare-progress")).toHaveTextContent("1/2");
    expect(within(step).getByRole("link", { name: /Préparer « Charte »/ })).toHaveAttribute(
      "href",
      "/documents/versions/v2/prepare?campaign=c1",
    );
    expect(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ })).toBeDisabled();
    expect(screen.getByText(/Il reste à préparer : Charte/)).toBeInTheDocument();
  });

  it("refuses an impossible calendar, then sends with the four settings", async () => {
    open(1);
    await screen.findByTestId("policy-card");
    // A deadline already gone is caught before anything is sent.
    fireEvent.change(screen.getByLabelText(/Date d.échéance/), { target: { value: "2000-01-01" } });
    fireEvent.click(stepButton(/Vérifier et envoyer/));
    await screen.findByTestId("recap-card");
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    fireEvent.click(screen.getByRole("button", { name: /Oui, envoyer maintenant/ }));
    expect(await screen.findByText(/déjà passée/)).toBeInTheDocument();
    expect(vi.mocked(api.post).mock.calls.some((c) => c[0] === "/campaigns/c1/launch")).toBe(false);

    fireEvent.click(stepButton(/Signataires et relances/));
    fireEvent.change(await screen.findByLabelText(/Date d.échéance/), { target: { value: "2099-01-31" } });
    fireEvent.change(screen.getByLabelText(/Relance en cas de non-réponse/), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText(/^Renouvellement/), { target: { value: "12" } });
    fireEvent.click(stepButton(/Vérifier et envoyer/));
    await screen.findByTestId("recap-card");
    const recap = screen.getByTestId("recap-card");
    expect(recap).toHaveTextContent("Début dès l'envoi");
    expect(recap).toHaveTextContent("Relance en cas de non-réponse : toutes les semaines");
    expect(recap).toHaveTextContent("Renouvellement : tous les ans");

    // Nothing is sent by the first click: it asks, and "Annuler" backs out.
    fireEvent.click(screen.getByRole("button", { name: /Envoyer pour signature/ }));
    expect(screen.getByTestId("send-summary")).toHaveTextContent("1 document(s) à signer par chaque destinataire");
    expect(vi.mocked(api.post).mock.calls.some((c) => c[0] === "/campaigns/c1/launch")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Oui, envoyer maintenant/ }));
    await waitFor(() => expect(screen.getByText("suivi")).toBeInTheDocument());
    const call = vi.mocked(api.post).mock.calls.find((c) => c[0] === "/campaigns/c1/launch")!;
    expect(call[1]).toMatchObject({
      reminder_first_days: 7,
      reminder_interval_days: 7,
      reminder_max_count: null,
      renewal_every: 12,
      renewal_unit: "MONTHS",
      start_at: null,
    });
    expect((call[1] as { deadline: string }).deadline.startsWith("2099-01-3")).toBe(true);
  });

  it("schedules the sending when a start date in the future is given", async () => {
    open(1);
    await screen.findByTestId("policy-card");
    fireEvent.change(screen.getByLabelText(/Date de début/), { target: { value: "2099-01-01" } });
    fireEvent.click(stepButton(/Vérifier et envoyer/));
    await screen.findByTestId("recap-card");
    expect(screen.getByTestId("send-summary")).toHaveTextContent("programmé : personne n'est prévenu avant");
    fireEvent.click(screen.getByRole("button", { name: /Programmer l.envoi/ }));
    fireEvent.click(screen.getByRole("button", { name: /Oui, programmer/ }));
    await waitFor(() => expect(screen.getByText("suivi")).toBeInTheDocument());
    const call = vi.mocked(api.post).mock.calls.find((c) => c[0] === "/campaigns/c1/launch")!;
    expect((call[1] as { start_at: string }).start_at.startsWith("2099-01-01")).toBe(true);
  });

  it("will not send before every document has its elements, and says which one", async () => {
    open(4, [prepared, { ...prepared, version_id: "v2", title: "Charte", elements: 0 }]);
    const blocker = await screen.findByTestId("launch-blocker");
    expect(blocker).toHaveTextContent("Placez les éléments");
    expect(blocker).toHaveTextContent("Charte");
    expect(blocker).not.toHaveTextContent("PSSI");
    expect(screen.getByRole("button", { name: /Envoyer pour signature/ })).toBeDisabled();
  });

  it("asks for a document when there is none", async () => {
    open(4, []);
    expect(await screen.findByTestId("launch-blocker")).toHaveTextContent("Ajoutez au moins un document");
    expect(screen.getByRole("button", { name: /Envoyer pour signature/ })).toBeDisabled();
  });

  it("asks to choose the people when the mail merge list is empty", async () => {
    vi.mocked(api.post).mockResolvedValue({ population_count: 0 });
    open(4);
    expect(await screen.findByTestId("launch-blocker")).toHaveTextContent("Choisissez les personnes");
  });
});
