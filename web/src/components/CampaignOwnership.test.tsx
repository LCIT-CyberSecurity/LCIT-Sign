import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CampaignOwnership from "./CampaignOwnership";
import { api } from "../api/client";
import type { Campaign } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } };
});

const alice = { id: "u-alice", display_name: "Alice Martin", email: "alice@x" };
const sophie = { id: "u-sophie", display_name: "Sophie Bernard", email: "sophie@x" };
const paul = { id: "u-paul", display_name: "Paul Muller", email: "paul@x" };

const campaign = (over: Partial<Campaign> = {}) =>
  ({
    id: "c1", name: "RH", owner: alice, created_by: alice, preparers: [],
    access: { operate: true, content: true }, ...over,
  }) as unknown as Campaign;

describe("CampaignOwnership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue([alice, sophie, paul]);
  });

  it("names the owner, and who started it only when that is someone else", () => {
    const { rerender } = render(<CampaignOwnership campaign={campaign()} onChanged={vi.fn()} />);
    expect(screen.getByTestId("owner")).toHaveTextContent("Alice Martin");
    expect(screen.queryByTestId("created-by")).toBeNull();
    rerender(<CampaignOwnership campaign={campaign({ owner: sophie })} onChanged={vi.fn()} />);
    expect(screen.getByTestId("owner")).toHaveTextContent("Sophie Bernard");
    expect(screen.getByTestId("created-by")).toHaveTextContent("Alice Martin");
  });

  it("tells an operator who is not on the campaign that its content is confidential", async () => {
    render(
      <CampaignOwnership campaign={campaign({ access: { operate: true, content: false } })} onChanged={vi.fn()} />,
    );
    expect(screen.getByTestId("confidential-note")).toHaveTextContent("confidentiel");
    // …and offers to add a preparer (themselves, for instance): the way in, with a trace.
    expect(await screen.findByRole("button", { name: "Ajouter" })).toBeInTheDocument();
  });

  it("offers nothing to change to someone who cannot operate the campaign", () => {
    render(
      <CampaignOwnership campaign={campaign({ access: { operate: false, content: true } })} onChanged={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Ajouter" })).toBeNull();
    expect(screen.queryByText("Changer le propriétaire")).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("adds a preparer among those who are not on it yet, and hands the campaign over", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    vi.mocked(api.post).mockResolvedValue(campaign({ preparers: [sophie] }));
    vi.mocked(api.put).mockResolvedValue(campaign({ owner: sophie }));
    render(<CampaignOwnership campaign={campaign()} onChanged={onChanged} />);
    const adding = await screen.findByLabelText("Ajouter un préparateur");
    // The owner is not offered again.
    expect(Array.from(adding.querySelectorAll("option")).map((o) => o.textContent)).not.toContain("Alice Martin");
    await user.selectOptions(adding, "u-sophie");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/campaigns/c1/preparers", { user_id: "u-sophie" }),
    );
    expect(onChanged).toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Changer le propriétaire"), "u-paul");
    await user.click(screen.getByRole("button", { name: "Changer" }));
    await user.click(screen.getByRole("button", { name: "Oui, changer de propriétaire" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/campaigns/c1/owner", { user_id: "u-paul" }));
  });

  it("says why when the server refuses", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("../api/client");
    vi.mocked(api.post).mockRejectedValue(new ApiError(422, "Sophie n'a pas le rôle Préparateur"));
    render(<CampaignOwnership campaign={campaign()} onChanged={vi.fn()} />);
    await user.selectOptions(await screen.findByLabelText("Ajouter un préparateur"), "u-sophie");
    await user.click(screen.getByRole("button", { name: "Ajouter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("n'a pas le rôle Préparateur");
  });
});
