import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SignedDocuments from "./SignedDocuments";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { get: vi.fn() } }));

const response = {
  campaigns: [
    { id: "c1", name: "PSSI 2026", status: "ACTIVE" },
    { id: "c2", name: "Charte", status: "CLOSED" },
  ],
  signed: [
    {
      id: "s1", display_id: "SIG-1", signed_at: "2026-10-05T10:00:00Z", document_title: "PSSI",
      version_label: "1.0", campaign_id: "c1", campaign_name: "PSSI 2026", signer_name: "Rita Rssi",
      signer_email: "rita@lcit.fr", signed_file_sha256: "a".repeat(64),
    },
  ],
  outstanding: [
    {
      id: "a1", status: "WAITING", document_title: "PSSI", version_label: "1.0", campaign_id: "c1",
      campaign_name: "PSSI 2026", signer_name: "Bob Dupont", signer_email: "bob@lcit.fr", deadline: null,
    },
  ],
  totals: { signed: 1, outstanding: 1, waiting: 1 },
};

const lastUrl = () => String(vi.mocked(api.get).mock.calls.at(-1)?.[0]);

describe("<SignedDocuments />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue(response);
  });

  it("lists who signed (with the PDF and the proof) and who still has to", async () => {
    render(<MemoryRouter><SignedDocuments /></MemoryRouter>);
    await screen.findByText("Rita Rssi");
    const signed = screen.getByTestId("signed-table");
    expect(within(signed).getByRole("link", { name: /Ouvrir/ })).toHaveAttribute(
      "href", "/api/signatures/s1/signed-pdf?inline=true",
    );
    expect(within(signed).getByRole("link", { name: /Preuve/ })).toHaveAttribute("href", "/signatures/s1");
    const outstanding = screen.getByTestId("outstanding-table");
    expect(outstanding).toHaveTextContent("Bob Dupont");
    expect(outstanding).toHaveTextContent("Pas encore son tour");
    expect(screen.getByTestId("total-signed")).toHaveTextContent("1");
    expect(screen.getByTestId("total-waiting")).toHaveTextContent("1");
  });

  it("narrows to one or several campaigns and to a search, and exports exactly that", async () => {
    render(<MemoryRouter><SignedDocuments /></MemoryRouter>);
    await screen.findByText("Rita Rssi");
    expect(screen.getByRole("link", { name: /ZIP/ })).toHaveAttribute("href", "/api/signed/export.zip?");

    fireEvent.click(screen.getByRole("button", { name: "PSSI 2026" }));
    fireEvent.click(screen.getByRole("button", { name: "Charte" }));
    await waitFor(() => expect(lastUrl()).toContain("campaign_ids=c1&campaign_ids=c2"));
    expect(screen.getByRole("link", { name: /ZIP/ })).toHaveAttribute(
      "href", "/api/signed/export.zip?campaign_ids=c1&campaign_ids=c2",
    );

    fireEvent.change(screen.getByLabelText("Rechercher"), { target: { value: "rita" } });
    await waitFor(() => expect(lastUrl()).toContain("q=rita"));
    expect(screen.getByRole("link", { name: /ZIP/ }).getAttribute("href")).toContain("q=rita");
  });

  it("says so when nothing was signed, and offers no export", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...response, signed: [], outstanding: [], totals: { signed: 0, outstanding: 0, waiting: 0 } });
    render(<MemoryRouter><SignedDocuments /></MemoryRouter>);
    expect(await screen.findByText("Aucun document signé pour cette sélection.")).toBeInTheDocument();
    // Nothing to export: the button is not a link any more.
    expect(screen.queryByRole("link", { name: /ZIP/ })).toBeNull();
    expect(screen.getByText(/ZIP/).closest("a")).toHaveAttribute("aria-disabled", "true");
  });

  it("is about the campaign it is given: no campaign picker, and that campaign only", async () => {
    render(<MemoryRouter><SignedDocuments campaignIds={["c1"]} /></MemoryRouter>);
    await screen.findByText("Rita Rssi");
    expect(lastUrl()).toContain("campaign_ids=c1");
    expect(screen.queryByTestId("signed-filters")).toBeNull();
    expect(screen.getByRole("link", { name: /ZIP/ })).toHaveAttribute(
      "href", "/api/signed/export.zip?campaign_ids=c1",
    );
  });
});
