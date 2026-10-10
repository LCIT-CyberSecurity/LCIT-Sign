import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignatureDetailPage from "../pages/SignatureDetailPage";
import { api } from "../api/client";
import { assignmentStatus, campaignStatus, versionStatus } from "./enums";
import { blockerText, errorText } from "./errors";
import { ApiError } from "../api/client";
import { setLocale } from "./index";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "1", roles: ["SIGNER"] }, hasRole: (r: string) => r === "SIGNER" }),
}));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn() } };
});

const deepFreeze = <T,>(value: T): T => {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
};

/** What the API sends: none of it may change with the language. */
const signature = deepFreeze({
  id: "0b9a6c52-5a3e-4d52-9f55-0c6f6a1d7e11", display_id: "SIG-000042", campaign_id: "c1", document_id: "d1",
  document_version_id: "v1", signed_at_utc: "2026-10-06T13:03:19Z", display_name_snapshot: "Jean Dupont",
  email_snapshot: "jean.dupont@entreprise.fr", document_title: "Charte informatique — NDA", version_label: "1.0",
  campaign_name: "Signature NDA France 2026", signed_file_sha256: "ab".repeat(32), original_file_sha256: "cd".repeat(32),
  signing_key_id: "key-2026-01",
});
const chain = deepFreeze({
  steps: [
    { role: 1, role_label: "Signataire 1", name: "Jean Dupont", email: "jean.dupont@entreprise.fr", status: "SIGNED",
      signed_at: "2026-10-06T13:03:19Z", display_id: "SIG-000042", mine: true },
  ],
  others: null,
  complete: true,
});

function open() {
  vi.mocked(api.get).mockImplementation(async (path: string) => (path.endsWith("/chain") ? chain : signature));
  return render(
    <MemoryRouter initialEntries={["/signatures/s1"]}>
      <Routes>
        <Route path="/signatures/:id" element={<SignatureDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("changing the language never changes the data", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps every business value identical in French and in English", async () => {
    const values = [
      "Charte informatique — NDA",
      "Signature NDA France 2026",
      "Jean Dupont",
      "SIG-000042",
      "ab".repeat(32),
      "key-2026-01",
    ];
    const first = open();
    await screen.findByTestId("signature-chain");
    const french = values.map((v) => first.container.textContent?.includes(v));
    expect(french).toEqual(values.map(() => true));
    expect(first.container).toHaveTextContent("jean.dupont@entreprise.fr");
    first.unmount();

    await setLocale("en");
    const second = open();
    await screen.findByTestId("signature-chain");
    const english = values.map((v) => second.container.textContent?.includes(v));
    expect(english).toEqual(values.map(() => true));
    expect(second.container).toHaveTextContent("jean.dupont@entreprise.fr");
    // What is around the data did change.
    expect(second.container).toHaveTextContent("Who signed this document?");
    expect(second.container).not.toHaveTextContent("Qui a signé");
    // The objects the API gave were frozen: any attempt to rewrite them would have thrown.
    expect(signature.campaign_name).toBe("Signature NDA France 2026");
    expect(JSON.parse(JSON.stringify(chain)).steps[0].status).toBe("SIGNED");
  });

  it("shows an enum's label in the active language while the value stays the API's", async () => {
    const pending = deepFreeze({ id: "a1", status: "PENDING" });
    expect(pending.status).toBe("PENDING");
    expect(assignmentStatus(pending.status)).toBe("À signer");
    expect(assignmentStatus("SIGNED")).toBe("Signé");
    expect(campaignStatus("ACTIVE")).toBe("Active");
    expect(campaignStatus("CLOSED")).toBe("Clôturée");
    expect(versionStatus("SUPERSEDED")).toBe("Remplacée");
    await setLocale("en");
    expect(pending.status).toBe("PENDING");
    expect(assignmentStatus(pending.status)).toBe("Pending");
    expect(assignmentStatus("SIGNED")).toBe("Signed");
    expect(campaignStatus("CLOSED")).toBe("Closed");
    expect(versionStatus("SUPERSEDED")).toBe("Superseded");
    // A value this build has no word for is shown as the API sent it.
    expect(assignmentStatus("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("words the server's known sentences, and shows anything else as it came", async () => {
    const wrong = new ApiError(401, "Identifiant ou mot de passe incorrect");
    expect(errorText(wrong)).toBe("Identifiant ou mot de passe incorrect");
    await setLocale("en");
    expect(errorText(wrong)).toBe("Incorrect username or password");
    expect(errorText(new ApiError(409, "Target population is empty"))).toBe("No recipients are targeted.");
    // A provider's own message, or what a person typed, is never rewritten.
    expect(errorText(new ApiError(502, "AADSTS7000215: Invalid client secret provided."))).toBe(
      "AADSTS7000215: Invalid client secret provided.",
    );
    expect(errorText(new ApiError(409, "Alice Martin est déjà propriétaire ou préparateur"))).toBe(
      "Alice Martin is already the owner or a preparer",
    );
    expect(errorText(new Error("boom"), "errors.generic")).toBe("Something went wrong.");
    expect(blockerText("1 signature(s)")).toBe("1 signature");
    expect(blockerText("4 signature(s)")).toBe("4 signatures");
    expect(blockerText("a free text reason")).toBe("a free text reason");
  });
});
