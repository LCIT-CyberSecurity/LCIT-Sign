import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DirectoryConnectorForm from "./DirectoryConnectorForm";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { put: vi.fn(), del: vi.fn() } };
});

const entra = {
  source: "entra",
  configured: false,
  fields: {},
  sync_interval_minutes: 60,
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
      fields: { tenant_id: "tenant-1", client_id: "client-1" },
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
