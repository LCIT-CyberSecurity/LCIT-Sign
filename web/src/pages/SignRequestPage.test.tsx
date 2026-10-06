import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignRequestPage from "./SignRequestPage";
import { api } from "../api/client";

// The editor draws PDF pages (PDF.js), which jsdom cannot: a stand-in that says which document it
// was given and lets the test finish it.
vi.mock("./PrepareDocumentPage", () => ({
  DocumentEditor: ({
    versionId,
    embedded,
    onFinish,
  }: {
    versionId: string;
    embedded?: boolean;
    onFinish: (next: string | null, back: string) => void;
  }) => (
    <div data-testid={`editor-${versionId}`} data-embedded={String(Boolean(embedded))}>
      <button onClick={() => onFinish(versionId === "v1" ? "v2" : null, "/back")}>Terminer {versionId}</button>
    </div>
  ),
}));

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), postForm: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const prepared = {
  version_id: "v1", title: "PSSI", version_label: "1.0", status: "DRAFT", elements: 2,
  element_roles: [1], signature_roles: [1],
};
const everyone = { role: 1, label: "", mode: "EACH", user_id: null, user_display_name: null };

const campaign = (documents: unknown[] = [prepared], roles: unknown[] = [everyone]) => ({
  plan: null as unknown,
  id: "c1", name: "PSSI 2026", description: "", status: "DRAFT", target_mode: "", created_at: "",
  launch_at: null, deadline: null, closed_at: null, document_version_ids: [], roles_required: 1,
  roles, documents, assignment_counts: {}, policies: {}, renewal_of_campaign_id: null,
});

// What the server says once the request was sent.
const server = { status: "DRAFT" };
const NOTHING_SIGNED = { campaigns: [], signed: [], outstanding: [], totals: { signed: 0, outstanding: 0, waiting: 0 } };

function open(step = 1, documents?: unknown[], plan: unknown = null) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === "/campaigns/c1") return { ...campaign(documents), status: server.status, plan };
    if (path.startsWith("/signed/documents")) return NOTHING_SIGNED;
    return [];
  });
  render(
    <MemoryRouter initialEntries={[`/sign/c1?step=${step}`]}>
      <Routes>
        <Route path="/sign/:id" element={<SignRequestPage />} />
        <Route path="/campaigns/:id" element={<p>suivi</p>} />
        <Route path="/sign" element={<p>liste des demandes</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const stepButton = (name: RegExp) => screen.getByRole("button", { name });

describe("SignRequestPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.status = "DRAFT";
    vi.mocked(api.post).mockImplementation(async (path: string, body?: unknown) => {
      if (path.endsWith("/launch")) {
        server.status = (body as { start_at: string | null }).start_at ? "SCHEDULED" : "ACTIVE";
        return {};
      }
      return { population_count: 3 };
    });
    vi.mocked(api.put).mockResolvedValue({});
  });

  it("goes through the screens: signers, documents, preparing, then review and send", async () => {
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

    // Screen 3: preparing, with the editor in the flow (not on a page apart).
    fireEvent.click(screen.getByRole("button", { name: /Suivant : préparer les documents/ }));
    const prepare = await screen.findByTestId("prepare-step");
    expect(screen.getByTestId("prepare-progress")).toHaveTextContent("1/1");
    expect(within(prepare).getByTestId("editor-v1")).toHaveAttribute("data-embedded", "true");

    // Screen 4: review and send.
    fireEvent.click(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ }));
    expect(await screen.findByTestId("recap-card")).toHaveTextContent("PSSI — 2 élément(s) placé(s)");
    expect(screen.getByTestId("recap-card")).toHaveTextContent("Chaque destinataire");
    // Nothing is signed before it is sent: the last step is not reachable yet.
    expect(screen.getByRole("button", { name: /Documents signés/ })).toBeDisabled();
  });

  it("prepares the documents one after the other, in the flow, and says which are done", async () => {
    open(3, [prepared, { ...prepared, version_id: "v2", title: "Charte", elements: 0 }]);
    const step = await screen.findByTestId("prepare-step");
    expect(screen.getByTestId("prepare-progress")).toHaveTextContent("1/2");
    // The first document still to prepare is the one open; the other can be chosen from the strip.
    expect(within(step).getByTestId("editor-v2")).toBeInTheDocument();
    expect(within(step).getByRole("tab", { name: /Charte/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(step).getByRole("tab", { name: /PSSI/ }));
    expect(await within(step).findByTestId("editor-v1")).toBeInTheDocument();
    // Finishing one opens the next; finishing the last moves on to the review.
    fireEvent.click(within(step).getByRole("button", { name: "Terminer v1" }));
    expect(await within(step).findByTestId("editor-v2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ })).toBeDisabled();
    expect(screen.getByText(/Il reste à préparer : Charte/)).toBeInTheDocument();
    fireEvent.click(within(step).getByRole("button", { name: "Terminer v2" }));
    expect(await screen.findByTestId("recap-card")).toBeInTheDocument();
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
    // Sent: the last step shows what comes back, and the earlier ones are closed.
    expect(await screen.findByTestId("signed-step")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Signataires et relances/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Ouvrir le suivi complet/ })).toHaveAttribute("href", "/campaigns/c1");
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
    expect(await screen.findByTestId("signed-step")).toHaveTextContent("démarre à la date prévue");
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

  it("finds again what was chosen, and keeps what is chosen as it goes", async () => {
    // Saved earlier (a reload, or back the next day): the recipients and the planning are there.
    const deadline = new Date("2099-01-31T12:00:00").toISOString();
    open(1, undefined, {
      user_ids: ["u7"],
      deadline,
      reminder_first_days: 7,
      reminder_interval_days: 7,
      renewal_every: 12,
      renewal_unit: "MONTHS",
    });
    // The screen is there before the saved choices are put back: wait for them.
    await screen.findByLabelText(/Date d.échéance/);
    await waitFor(() => expect(screen.getByLabelText(/Date d.échéance/)).toHaveValue("2099-01-31"));
    expect(screen.getByLabelText(/Relance en cas de non-réponse/)).toHaveValue("7");
    expect(screen.getByLabelText(/^Renouvellement/)).toHaveValue("12");

    // A change is saved by itself, shortly after.
    fireEvent.change(screen.getByLabelText(/Date d.échéance/), { target: { value: "2099-03-15" } });
    await waitFor(
      () => {
        const saved = vi.mocked(api.put).mock.calls.filter((c) => c[0] === "/campaigns/c1/plan");
        expect(saved.length).toBeGreaterThan(0);
        const last = saved[saved.length - 1][1] as { user_ids: string[]; deadline: string };
        expect(last.user_ids).toEqual(["u7"]);
        expect(last.deadline.startsWith("2099-03-1")).toBe(true);
      },
      { timeout: 3000 },
    );
  });

  it("deletes a request still being prepared, after a second click; a sent one has no such button", async () => {
    vi.mocked(api.del).mockResolvedValue({});
    open(1);
    await screen.findByRole("heading", { name: "PSSI 2026" });
    fireEvent.click(screen.getByRole("button", { name: "Supprimer cette demande" }));
    expect(api.del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Oui, supprimer cette demande" }));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith("/campaigns/c1"));
    expect(await screen.findByText("liste des demandes")).toBeInTheDocument();
  });

  it("offers no deletion once the request was sent", async () => {
    server.status = "ACTIVE";
    open(5);
    await screen.findByTestId("signed-step");
    expect(screen.queryByRole("button", { name: "Supprimer cette demande" })).toBeNull();
  });

  it("does not write anything for a request that was already sent", async () => {
    server.status = "ACTIVE";
    open(5);
    await screen.findByTestId("signed-step");
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(vi.mocked(api.put).mock.calls.some((c) => c[0] === "/campaigns/c1/plan")).toBe(false);
  });

  it("proposes to start today, due in 30 days, with no reminder; moving the start moves the deadline", async () => {
    open(1);
    const plusDays = (n: number) => {
      const d = new Date();
      d.setDate(d.getDate() + n);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    };
    await waitFor(() => expect(screen.getByLabelText(/Date de début/)).toHaveValue(plusDays(0)));
    expect(screen.getByLabelText(/Date d.échéance/)).toHaveValue(plusDays(30));
    expect(screen.getByLabelText(/Relance en cas de non-réponse/)).toHaveValue("");
    expect(screen.getByLabelText(/^Renouvellement/)).toHaveValue("");

    // A start date after the deadline carries the deadline with it, 30 days later.
    fireEvent.change(screen.getByLabelText(/Date de début/), { target: { value: "2099-06-01" } });
    expect(screen.getByLabelText(/Date d.échéance/)).toHaveValue("2099-07-01");
  });

  it("will not go on while a signer has a date and a name but no signature placed", async () => {
    // The case that got through: Alice has elements, but the only signature is Bob's.
    const roles = [
      { role: 1, label: "", mode: "FIXED", user_id: "u1", user_display_name: "Alice Martin" },
      { role: 2, label: "", mode: "EACH", user_id: null, user_display_name: null },
    ];
    const attestation = { ...prepared, title: "Test03", elements: 4, element_roles: [1, 2], signature_roles: [2] };
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/campaigns/c1" ? { ...campaign([attestation], roles), plan: null } : [],
    );
    render(
      <MemoryRouter initialEntries={["/sign/c1?step=3"]}>
        <Routes>
          <Route path="/sign/:id" element={<SignRequestPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const step = await screen.findByTestId("prepare-step");
    expect(within(step).getByTestId("missing-signature")).toHaveTextContent(
      "Placez une signature pour Alice Martin sur « Test03 ».",
    );
    // The document is marked as needing attention in the strip.
    expect(within(within(step).getByRole("tab", { name: /Test03/ })).getByLabelText("signature manquante")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Suivant : vérifier et envoyer/ })).toBeDisabled();
  });

  it("and says so on the review screen too, so it cannot be sent", async () => {
    const roles = [{ role: 1, label: "", mode: "EACH", user_id: null, user_display_name: null }];
    const nameOnly = { ...prepared, title: "Test03", element_roles: [1], signature_roles: [] };
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/campaigns/c1" ? { ...campaign([nameOnly], roles), plan: null } : [],
    );
    render(
      <MemoryRouter initialEntries={["/sign/c1?step=4"]}>
        <Routes>
          <Route path="/sign/:id" element={<SignRequestPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("launch-blocker")).toHaveTextContent(
      "Placez une signature pour Chaque destinataire sur « Test03 ».",
    );
    expect(screen.getByRole("button", { name: /Envoyer pour signature/ })).toBeDisabled();
  });
});
