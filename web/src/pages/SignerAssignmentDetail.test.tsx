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
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path === "/config"
        ? { consent_text: "J'atteste avoir pris connaissance de ce document.", consent_version: "1.0", app_version: "x" }
        : [assignment],
    );
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
    expect(api.post).toHaveBeenCalledWith("/documents/versions/v1/sign", { consent: true });
    expect(api.post).toHaveBeenCalledTimes(1);
  });
});
