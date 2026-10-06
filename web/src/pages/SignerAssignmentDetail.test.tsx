import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SignerAssignmentDetailPage from "./SignerAssignmentDetailPage";
import { api } from "../api/client";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "1", display_name: "Cédric Di Cesare", email: "cedric@lcit-test.local", roles: ["SIGNER"] },
  }),
}));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

const assignment = {
  id: "a1",
  campaign_id: "c1",
  document_version_id: "v1",
  document_title: "Charte informatique",
  version_label: "2.1",
  campaign_name: "Campagne 2026",
  status: "PENDING",
  deadline: null,
  signed_at: null,
  signature_id: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/assignments/a1"]}>
      <Routes>
        <Route path="/assignments/:id" element={<SignerAssignmentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("signing: preview, consent, then one deliberate click", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/config") {
        return { consent_text: "J'atteste avoir pris connaissance de ce document.", consent_version: "1.0", app_version: "x" };
      }
      if (path.endsWith("/signing-form")) return { inputs: [], automatic: [] };
      return [assignment];
    });
    vi.mocked(api.post).mockResolvedValue({ id: "s1", display_id: "SIG-ABC123ABC123" });
  });

  it("previews the signer's identity from the SSO account, not from anything typed", async () => {
    renderPage();
    expect(await screen.findByTestId("signature-preview-name")).toHaveTextContent("Cédric Di Cesare");
    expect(screen.getByText("cedric@lcit-test.local")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull(); // no way to type another identity
  });

  it("shows the document as it will be signed, and the signed copy once it is", async () => {
    const user = userEvent.setup();
    renderPage();
    const frame = () => document.querySelector("iframe") as HTMLIFrameElement;
    // Before: the document with what the signers before already put on it, not the bare original.
    await screen.findByRole("button", { name: "Signer" });
    expect(frame().getAttribute("src")).toBe("/api/assignments/a1/preview?v=pending");

    // After: the signed copy (the address changes, so the frame is loaded again).
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/config"
        ? { consent_text: "J'atteste.", consent_version: "1.0", app_version: "x" }
        : [{ ...assignment, status: "SIGNED", signature_id: "s1" }],
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Signer" }));
    await screen.findByText("Document signé");
    expect(frame().getAttribute("src")).toBe("/api/assignments/a1/preview?v=s1");
  });

  it("does not sign without consent, and signs on one click once consent is given", async () => {
    const user = userEvent.setup();
    renderPage();
    const sign = await screen.findByRole("button", { name: "Signer" });
    expect(sign).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(sign).toBeEnabled();
    await user.click(sign);
    expect(api.post).toHaveBeenCalledWith("/documents/versions/v1/sign", {
      consent: true,
      campaign_id: "c1",
      values: {},
    });
    expect(api.post).toHaveBeenCalledTimes(1);
  });
});

describe("signing a document with elements to fill in", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/config") {
        return { consent_text: "J'atteste.", consent_version: "1.0", app_version: "x" };
      }
      if (path.endsWith("/signing-form")) {
        return {
          inputs: [
            { id: "t1", kind: "TEXT", label: "Société", required: true, group_key: "societe", page: 1 },
            { id: "t2", kind: "TEXT", label: "Société", required: true, group_key: "societe", page: 2 },
            { id: "t3", kind: "TEXT", label: "Remarque", required: false, group_key: null, page: 2 },
          ],
          automatic: [
            { id: "a1", kind: "DATE", label: "", required: true, group_key: null, page: 1 },
            { id: "a2", kind: "SIGNATURE", label: "", required: true, group_key: null, page: 1 },
          ],
        };
      }
      return [assignment];
    });
    vi.mocked(api.post).mockResolvedValue({ id: "s1", display_id: "SIG-ABC123ABC123" });
  });

  it("asks once for a shared field, and says what will be filled in automatically", async () => {
    renderPage();
    await screen.findByTestId("signing-inputs");
    expect(screen.getAllByRole("textbox")).toHaveLength(2); // Société (shared), Remarque
    expect(screen.getByText(/votre signature, la date de signature/)).toBeInTheDocument();
  });

  it("will not sign until the required text is given, then sends it for every element", async () => {
    const user = userEvent.setup();
    renderPage();
    const sign = await screen.findByRole("button", { name: "Signer" });
    await user.click(screen.getByRole("checkbox"));
    expect(sign).toBeDisabled(); // consent given, but "Société" is still empty
    await user.type(screen.getByLabelText(/Société/), "LCIT");
    expect(sign).toBeEnabled();
    await user.click(sign);
    expect(api.post).toHaveBeenCalledWith("/documents/versions/v1/sign", {
      consent: true,
      campaign_id: "c1",
      values: { t1: "LCIT", t2: "LCIT", t3: "" },
    });
  });
});


describe("signing through DocuSign: the page follows the envelope instead of asking for a signature", () => {
  const through = (docusign: unknown) =>
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/config") return { consent_text: "x", consent_version: "1.0", app_version: "x" };
      if (path.endsWith("/signing-form")) return { inputs: [], automatic: [] };
      return [{ ...assignment, signature_method: "DOCUSIGN", docusign }];
    });

  it("says DocuSign mails the signer, and offers no signing here", async () => {
    through({ status: "SENT", error: null, inbox_url: null });
    renderPage();
    expect(await screen.findByTestId("docusign-status")).toHaveTextContent("DocuSign vous a envoyé un e-mail");
    expect(screen.queryByRole("button", { name: /^Signer/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("link", { name: /boîte DocuSign de test/ })).toBeNull();
  });

  it("points to the mailbox of the test DocuSign when there is one", async () => {
    through({ status: "SENT", error: null, inbox_url: "/mock-docusign/" });
    renderPage();
    expect(await screen.findByRole("link", { name: /Ouvrir la boîte DocuSign de test/ })).toHaveAttribute(
      "href",
      "/mock-docusign/",
    );
  });

  it("says what went wrong when the envelope could not be sent", async () => {
    through({ status: "FAILED", error: "DocuSign a refusé la demande (test).", inbox_url: null });
    renderPage();
    expect(await screen.findByTestId("docusign-status")).toHaveTextContent("L'envoi à DocuSign a échoué");
    expect(screen.getByText("DocuSign a refusé la demande (test).")).toBeInTheDocument();
  });
});
