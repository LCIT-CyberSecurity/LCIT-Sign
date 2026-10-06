import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignAllPage from "./SignAllPage";
import SignerAssignmentsPage from "./SignerAssignmentsPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { display_name: "Rita Rssi" } }) }));

const input = (id: string, extra = {}) => ({
  id, label: "Fonction", required: true, group_key: "fonction", kind: "TEXT", ...extra,
});

const plan = {
  campaign: { id: "c1", name: "Politiques 2026" },
  documents: [
    { version_id: "v1", title: "PSSI", version_label: "1.0", inputs: [input("f1")] },
    { version_id: "v2", title: "Charte", version_label: "1.0", inputs: [input("f2"), input("f3", { label: "Lieu", group_key: null, kind: "PLACE" })] },
  ],
  waiting: 1,
};

function open() {
  render(
    <MemoryRouter initialEntries={["/sign-all/c1"]}>
      <Routes>
        <Route path="/sign-all/:campaignId" element={<SignAllPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SignAllPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/config" ? { consent_text: "J'atteste.", consent_version: "1", app_version: "x" } : plan,
    );
    vi.mocked(api.post).mockResolvedValue({ signed: 2, signatures: [] });
  });

  it("asks a shared answer once, then signs every document with one consent", async () => {
    open();
    expect(await screen.findByTestId("sign-all-documents")).toHaveTextContent("2 document(s) à signer");
    expect(screen.getByTestId("sign-all-documents")).toHaveTextContent("1 autre(s) document(s)");

    // "Fonction" is on both documents but asked once; "Lieu" is on one document only.
    const inputs = screen.getByTestId("sign-all-inputs");
    expect(inputs.querySelectorAll("input")).toHaveLength(2);
    expect(inputs).toHaveTextContent("reprise sur 2 documents");

    const button = screen.getByRole("button", { name: /Signer les 2 documents/ });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(button).toBeDisabled(); // consent given, but a required answer is missing
    fireEvent.change(screen.getByLabelText(/^Fonction/), { target: { value: "RSSI" } });
    fireEvent.change(screen.getByLabelText(/^Lieu/), { target: { value: "Paris" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/sign-all/c1", {
        consent: true,
        shared: { fonction: "RSSI" },
        values: { f3: "Paris" },
      }),
    );
    expect(await screen.findByTestId("sign-all-done")).toHaveTextContent("2 document(s) signé(s)");
  });

  it("is offered on the list of documents to sign when a campaign has several", async () => {
    const row = (id: string, campaign: string, name: string, status = "PENDING") => ({
      id, campaign_id: campaign, campaign_name: name, document_version_id: `v-${id}`, document_title: `Doc ${id}`,
      version_label: "1.0", status, assigned_at: "", deadline: null, signed_at: null, signature_id: null,
    });
    vi.mocked(api.get).mockResolvedValue([
      row("a", "c1", "Politiques 2026"),
      row("b", "c1", "Politiques 2026"),
      row("c", "c2", "Charte 2026"),
    ]);
    render(
      <MemoryRouter>
        <SignerAssignmentsPage />
      </MemoryRouter>,
    );
    const links = await screen.findAllByTestId("sign-all-link");
    // Only the campaign with two documents gets it; a single document is signed as usual.
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/sign-all/c1");
    expect(links[0]).toHaveTextContent("2 documents de « Politiques 2026 »");
  });
});
