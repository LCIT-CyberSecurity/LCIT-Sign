import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ExternalPersonForm from "./ExternalPersonForm";
import CampaignSigners from "./CampaignSigners";
import RecipientPicker, { NO_RECIPIENTS } from "./RecipientPicker";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { post: vi.fn(), put: vi.fn() } };
});

const jean = { id: "x1", email: "jean@partenaire.com", display_name: "Jean Client", external: true };

describe("people from outside the company", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.post).mockResolvedValue(jean);
    vi.mocked(api.put).mockResolvedValue({});
  });

  it("is added by e-mail address and handed back", async () => {
    const onCreated = vi.fn();
    render(<ExternalPersonForm onCreated={onCreated} onCancel={vi.fn()} />);
    const add = screen.getByRole("button", { name: "Ajouter" });
    expect(add).toBeDisabled(); // an address is needed
    fireEvent.change(screen.getByLabelText("Prénom"), { target: { value: "Jean" } });
    fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Client" } });
    fireEvent.change(screen.getByLabelText("Adresse e-mail"), { target: { value: "jean@partenaire.com" } });
    fireEvent.click(add);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(jean));
    expect(api.post).toHaveBeenCalledWith("/campaigns/_meta/externals", {
      email: "jean@partenaire.com",
      given_name: "Jean",
      family_name: "Client",
    });
  });

  it("says why when the server refuses", async () => {
    vi.mocked(api.post).mockRejectedValue(
      Object.assign(new Error("Adresse e-mail invalide"), { status: 422 }),
    );
    render(<ExternalPersonForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Adresse e-mail"), { target: { value: "x@y.fr" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalide|échoué/);
  });

  it("joins the signers right away, before the list of recipients", async () => {
    const onUserAdded = vi.fn();
    const campaign = {
      id: "c1",
      roles: [{ role: 1, label: "", mode: "EACH", user_id: null, user_display_name: null }],
    } as never;
    render(<CampaignSigners campaign={campaign} users={[]} onSaved={vi.fn()} onUserAdded={onUserAdded} />);
    fireEvent.click(screen.getByRole("button", { name: /Ajouter une personne extérieure/ }));
    fireEvent.change(screen.getByLabelText("Adresse e-mail"), { target: { value: "jean@partenaire.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith("/campaigns/c1/signers", {
        signers: [
          { role: 1, mode: "FIXED", user_id: "x1" },
          { role: 2, mode: "EACH", user_id: null },
        ],
      }),
    );
    expect(onUserAdded).toHaveBeenCalledWith(jean);
  });

  it("can be picked as a recipient, and is marked as outside the company", async () => {
    const onChange = vi.fn();
    const onAddExternal = vi.fn();
    render(
      <RecipientPicker
        value={NO_RECIPIENTS}
        onChange={onChange}
        groups={[]}
        users={[{ id: "e1", display_name: "Estelle", external: true }]}
        onAddExternal={onAddExternal}
      />,
    );
    expect(screen.getByText("Estelle").closest("button")).toHaveTextContent("externe");
    fireEvent.click(screen.getByRole("button", { name: /Ajouter une personne extérieure/ }));
    fireEvent.change(screen.getByLabelText("Adresse e-mail"), { target: { value: "jean@partenaire.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    await waitFor(() => expect(onAddExternal).toHaveBeenCalledWith(jean));
    expect(onChange).toHaveBeenCalledWith({ allUsers: false, groupIds: [], userIds: ["x1"] });
  });
});
