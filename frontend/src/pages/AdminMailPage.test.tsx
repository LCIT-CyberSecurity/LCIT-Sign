import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminMailPage from "./AdminMailPage";
import { api } from "../api/client";
import type { ConnectorField, MailKindSpec } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } };
});

const field = (name: string, label: string, extra: Partial<ConnectorField> = {}): ConnectorField => ({
  name,
  label,
  help: `Ce que c'est : ${label}.`,
  example: `exemple de ${label}`,
  kind: "text",
  options: [],
  default: "",
  required: true,
  ...extra,
});

const kinds: MailKindSpec[] = [
  {
    kind: "smtp",
    label: "SMTP",
    description: "Envoie par un serveur SMTP.",
    fields: [
      field("host", "Serveur SMTP"),
      field("port", "Port", { kind: "number", default: "587" }),
      field("use_starttls", "STARTTLS", { kind: "checkbox", default: "true", required: false }),
      field("from_address", "Adresse d'expédition"),
    ],
    secret: field("password", "Mot de passe SMTP", { kind: "password", required: false }),
  },
  {
    kind: "gmail",
    label: "Google Workspace (Gmail)",
    description: "Envoie depuis une boîte Google Workspace.",
    fields: [field("from_address", "Boîte d'envoi")],
    secret: field("password", "Clé du compte de service (JSON)", { kind: "textarea" }),
  },
];

describe("AdminMailPage — one form per connector, every field explained", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.endsWith("/kinds") ? kinds : null,
    );
    vi.mocked(api.put).mockResolvedValue({ kind: "gmail", password_configured: true });
  });

  it("shows the fields of the chosen connector, each with a help bubble and an example", async () => {
    const user = userEvent.setup();
    render(<AdminMailPage />);
    expect(await screen.findByLabelText("Serveur SMTP")).toBeInTheDocument();
    expect(screen.getByTestId("mail-kind-description")).toHaveTextContent("serveur SMTP");
    for (const label of ["Serveur SMTP", "Port", "STARTTLS", "Adresse d'expédition", "Mot de passe SMTP"]) {
      const hint = screen.getByRole("button", { name: `Aide : ${label}` });
      const bubble = document.getElementById(hint.getAttribute("aria-describedby") ?? "");
      expect(bubble).toHaveAttribute("role", "tooltip");
      expect(bubble).toHaveTextContent("Exemple");
    }

    // Another connector, another form: nothing of the SMTP one is left.
    await user.selectOptions(screen.getByLabelText("Type de connecteur"), "gmail");
    expect(screen.queryByLabelText("Serveur SMTP")).toBeNull();
    expect(screen.getByLabelText("Boîte d'envoi")).toBeInTheDocument();
    expect(screen.getByLabelText("Clé du compte de service (JSON)").tagName).toBe("TEXTAREA");
    expect(screen.getByTestId("mail-kind-description")).toHaveTextContent("Google Workspace");
  });

  it("sends the chosen connector's settings and forgets the secret once sent", async () => {
    const user = userEvent.setup();
    render(<AdminMailPage />);
    await screen.findByLabelText("Type de connecteur");
    await user.selectOptions(screen.getByLabelText("Type de connecteur"), "gmail");
    await user.type(screen.getByLabelText("Boîte d'envoi"), "signature@corp.test");
    const secret = screen.getByLabelText("Clé du compte de service (JSON)");
    await user.click(secret);
    await user.paste('{"client_email": "x"}');
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith(
      "/admin/mail-connector",
      expect.objectContaining({
        kind: "gmail",
        from_address: "signature@corp.test",
        graph_tenant_id: null,
        password: '{"client_email": "x"}',
      }),
    );
    await waitFor(() => expect(secret).toHaveValue(""));
    expect(document.body.innerHTML).not.toContain("client_email");
  });
});
