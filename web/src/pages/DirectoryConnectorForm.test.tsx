import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DirectoryConnectorForm from "./DirectoryConnectorForm";
import { api } from "../api/client";
import type { ConnectorField, DirectorySource } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { put: vi.fn(), del: vi.fn() } };
});

const field = (
  name: string,
  label: string,
  example: string,
  extra: Partial<ConnectorField> = {},
): ConnectorField => ({
  name, label, help: `Ce que c'est : ${label}.`, example, kind: "text", options: [], default: "", required: true, ...extra,
});

const entra: DirectorySource = {
  source: "entra",
  configured: false,
  fields: {},
  sync_interval_minutes: 60,
  spec: {
    label: "Microsoft Entra ID",
    description: "…",
    fields: [
      field("tenant_id", "ID du tenant", "1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d"),
      field("client_id", "ID de l'application (client)", "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b"),
      field("team_selector", "D'où vient le nom de l'équipe ?", "Les groupes", {
        kind: "select",
        default: "groups",
        options: [
          { value: "groups", label: "Les groupes" },
          { value: "attribute", label: "Un attribut" },
        ],
      }),
      field("team_attribute", "Attribut qui donne l'équipe", "department", {
        kind: "select",
        default: "department",
        required: false,
        options: [{ value: "department", label: "Service" }],
      }),
    ],
    secret: field("client_secret", "Secret client", "abC8Q~xYz", { kind: "password" }),
  },
};

describe("DirectoryConnectorForm — credentials are write-only", () => {
  beforeEach(() => {
    vi.mocked(api.put).mockResolvedValue({});
  });

  it("masks the secret field and clears it once sent", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(<DirectoryConnectorForm source={entra} onChanged={onChanged} />);

    const secret = screen.getByLabelText("Secret client");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");

    await user.type(screen.getByLabelText("ID du tenant"), "tenant-1");
    await user.type(screen.getByLabelText("ID de l'application (client)"), "client-1");
    await user.type(secret, "FAKE-UI-SECRET");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    await waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith("/admin/directory/sources/entra/config", {
      // "Where does the team name come from" keeps its default; the attribute only
      // applies when teams are read from an attribute, so it is not sent.
      fields: { tenant_id: "tenant-1", client_id: "client-1", team_selector: "groups" },
      secret: "FAKE-UI-SECRET",
      sync_interval_minutes: 60,
    });
    await waitFor(() => expect(secret).toHaveValue(""));
    expect(document.body.innerHTML).not.toContain("FAKE-UI-SECRET");
    expect(onChanged).toHaveBeenCalled();
  });

  it("keeps the stored secret when the field is left empty", async () => {
    const user = userEvent.setup();
    render(
      <DirectoryConnectorForm
        source={{ ...entra, configured: true, fields: { tenant_id: "t", client_id: "c" } }}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Secret client")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("laisser vide"),
    );
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    expect(vi.mocked(api.put).mock.calls[0][1]).toMatchObject({ secret: undefined });
  });
});

describe("DirectoryConnectorForm — every setting explains itself", () => {
  it("offers a bubble with a description and an example for each field", () => {
    render(<DirectoryConnectorForm source={entra} onChanged={vi.fn()} />);
    for (const field of ["ID du tenant", "ID de l'application (client)", "Secret client"]) {
      const hint = screen.getByRole("button", { name: `Aide : ${field}` });
      const tooltip = document.getElementById(hint.getAttribute("aria-describedby") ?? "");
      expect(tooltip).toHaveAttribute("role", "tooltip");
      expect(tooltip).toHaveTextContent("Exemple");
    }
    expect(screen.getByRole("button", { name: "Aide : ID du tenant" }).getAttribute("aria-describedby")).toBeTruthy();
    expect(document.body.textContent).toContain("1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d");
  });

  it("shows the attribute only when the team name is read from an attribute", async () => {
    const user = userEvent.setup();
    render(<DirectoryConnectorForm source={entra} onChanged={vi.fn()} />);
    expect(screen.queryByLabelText("Attribut qui donne l'équipe")).toBeNull();
    await user.selectOptions(screen.getByLabelText("D'où vient le nom de l'équipe ?"), "attribute");
    expect(screen.getByLabelText("Attribut qui donne l'équipe")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aide : Attribut qui donne l'équipe" })).toBeInTheDocument();
  });
});
