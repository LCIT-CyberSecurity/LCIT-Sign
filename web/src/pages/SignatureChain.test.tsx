import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignatureDetailPage from "./SignatureDetailPage";
import { api } from "../api/client";

const auth = { roles: ["SIGNER"] as string[] };
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "1", roles: auth.roles }, hasRole: (r: string) => auth.roles.includes(r) }),
}));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn() } };
});

const signature = {
  id: "s2", display_id: "SIG-2", campaign_id: "c1", document_id: "d1", document_version_id: "v1",
  signed_at_utc: "2026-10-06T13:03:19Z", display_name_snapshot: "Bob Dupont", email_snapshot: "bob@lcit.fr",
  document_title: "Test03", version_label: "1.0", campaign_name: "Test03",
  signed_file_sha256: "a".repeat(64), original_file_sha256: "b".repeat(64), signing_key_id: "k1",
};
const step = (name: string, extra = {}) => ({
  role: 1, role_label: "Signataire 1", name, email: `${name}@lcit.fr`, status: "SIGNED",
  signed_at: "2026-10-06T13:02:47Z", display_id: "SIG-1", mine: false, ...extra,
});

function open(chain: unknown) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/chain")) return chain;
    return signature;
  });
  render(
    <MemoryRouter initialEntries={["/signatures/s2"]}>
      <Routes>
        <Route path="/signatures/:id" element={<SignatureDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the page of a signature says who signed the document", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.roles = ["SIGNER"];
  });

  it("lists the signers in order, with the person themselves marked, and says it is their copy", async () => {
    open({
      steps: [step("Alice Martin"), step("Bob Dupont", { role: 2, mine: true, signed_at: "2026-10-06T13:03:19Z" })],
      others: null,
      complete: true,
    });
    const card = await screen.findByTestId("signature-chain");
    expect(card).toHaveTextContent("Alice Martin");
    expect(card).toHaveTextContent("Bob Dupont (vous)");
    expect(card.querySelectorAll("li")).toHaveLength(2);
    expect(card).toHaveTextContent("Tout le monde a signé.");
    expect(card).toHaveTextContent("votre exemplaire");
    // A signer follows the campaigns they run: the link is there. Someone with no role has none.
    expect(screen.getByRole("link", { name: "Suivi" })).toBeInTheDocument();
  });

  it("says who is left, and counts the other recipients without naming them", async () => {
    open({
      steps: [step("Bob Dupont", { mine: true }), step("Rita Rssi", { role: 2, status: "WAITING", signed_at: null, display_id: null })],
      others: { count: 12, signed: 9 },
      complete: false,
    });
    const card = await screen.findByTestId("signature-chain");
    expect(card).toHaveTextContent("pas encore son tour");
    expect(screen.getByTestId("chain-others")).toHaveTextContent("12 autre(s) destinataire(s), dont 9 ont signé");
    expect(card).toHaveTextContent("Il reste des signatures à recueillir.");
  });

  it("leads the staff to the follow-up of the whole campaign", async () => {
    auth.roles = ["OPERATOR"];
    open({ steps: [step("Bob Dupont", { mine: true })], others: null, complete: true });
    expect(await screen.findByRole("link", { name: "Suivi" })).toHaveAttribute("href", "/campaigns?tab=signed");
  });
});
