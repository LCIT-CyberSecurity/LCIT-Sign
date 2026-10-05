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

  it("does not sign without consent, and signs on one click once consent is given", async () => {
    const user = userEvent.setup();
    renderPage();
    const sign = await screen.findByRole("button", { name: "Signer" });
    expect(sign).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(sign).toBeEnabled();
    await user.click(sign);
    expect(api.post).toHaveBeenCalledWith("/documents/versions/v1/sign", { consent: true, values: {} });
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
      values: { t1: "LCIT", t2: "LCIT", t3: "" },
    });
  });
});
