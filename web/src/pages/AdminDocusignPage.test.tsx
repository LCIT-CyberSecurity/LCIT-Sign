import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminDocusignPage from "./AdminDocusignPage";
import { api } from "../api/client";
import type { ConnectorField, DocusignAdmin } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } };
});

const field = (name: string, label: string, extra: Partial<ConnectorField> = {}): ConnectorField => ({
  name, label, help: `Ce que c'est : ${label}.`, example: "exemple", kind: "text", options: [], default: "",
  required: true, ...extra,
});

const config = (over: Partial<DocusignAdmin> = {}): DocusignAdmin => ({
  configured: false,
  values: { environment: "demo", integration_key: "", user_id: "", account_id: "" },
  has_private_key: false,
  fields: [
    field("environment", "Environnement", {
      kind: "select", default: "demo",
      options: [{ value: "demo", label: "Bac à sable (demo)" }, { value: "production", label: "Production" }],
    }),
    field("integration_key", "Clé d'intégration"),
    field("user_id", "ID utilisateur (GUID)"),
    field("account_id", "ID de compte API"),
  ],
  private_key: field("private_key", "Clé privée RSA", { kind: "textarea" }),
  guide: ["Créez un compte développeur.", "Donnez le consentement."],
  test_setup_available: true,
  mock: false,
  ...over,
});

describe("AdminDocusignPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue(config());
  });

  it("explains how to prepare DocuSign, with a bubble on each setting", async () => {
    render(<AdminDocusignPage />);
    expect(await screen.findByText("Comment préparer DocuSign, pas à pas")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Créez un compte développeur.",
      "Donnez le consentement.",
    ]);
    for (const label of ["Clé d'intégration", "ID utilisateur (GUID)", "ID de compte API", "Clé privée RSA"]) {
      expect(screen.getByRole("button", { name: `Aide : ${label}` })).toBeInTheDocument();
    }
  });

  it("sends the key once and never keeps it in the page", async () => {
    const user = userEvent.setup();
    vi.mocked(api.put).mockResolvedValue(config({ configured: true, has_private_key: true }));
    render(<AdminDocusignPage />);
    await user.type(await screen.findByLabelText("Clé d'intégration"), "ik-1");
    await user.type(screen.getByLabelText("ID utilisateur (GUID)"), "user-1");
    await user.type(screen.getByLabelText("ID de compte API"), "acc-1");
    const key = screen.getByLabelText("Clé privée RSA");
    await user.type(key, "FAKE-KEY");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/admin/docusign", {
      environment: "demo", integration_key: "ik-1", user_id: "user-1", account_id: "acc-1",
      private_key: "FAKE-KEY",
    }));
    await waitFor(() => expect(key).toHaveValue(""));
    expect(document.body.innerHTML).not.toContain("FAKE-KEY");
    expect(await screen.findByText("Connexion enregistrée (clé chiffrée).")).toBeInTheDocument();
  });

  it("tests the connection and says what DocuSign answered", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue(config({ configured: true, has_private_key: true }));
    vi.mocked(api.post).mockResolvedValue({ ok: false, message: "DocuSign attend le consentement." });
    render(<AdminDocusignPage />);
    await user.click(await screen.findByRole("button", { name: "Tester la connexion" }));
    expect(await screen.findByTestId("docusign-test-result")).toHaveTextContent("DocuSign attend le consentement.");
    expect(api.post).toHaveBeenCalledWith("/admin/docusign/test-connection");
  });

  it("cannot test before it is configured, and offers the test DocuSign on a test server", async () => {
    const user = userEvent.setup();
    render(<AdminDocusignPage />);
    expect(await screen.findByRole("button", { name: "Tester la connexion" })).toBeDisabled();
    vi.mocked(api.post).mockResolvedValue(config({ configured: true, mock: true, has_private_key: true }));
    await user.click(screen.getByRole("button", { name: /Utiliser le DocuSign de test/ }));
    expect(api.post).toHaveBeenCalledWith("/admin/docusign/test-setup");
    expect(await screen.findByTestId("docusign-mock-note")).toHaveTextContent("aucune valeur légale");
  });
});
