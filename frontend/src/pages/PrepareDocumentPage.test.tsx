import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DocumentEditor } from "./PrepareDocumentPage";
import { api } from "../api/client";

// PDF.js cannot run in jsdom: the page drawing is replaced by a stand-in.
vi.mock("../prepare/PdfPages", () => ({ default: () => <div data-testid="pdf-pages" /> }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { get: vi.fn(), put: vi.fn() } };
});

const campaign = {
  id: "c1", name: "PSSI", status: "DRAFT",
  roles: [
    { role: 1, label: "", mode: "FIXED", user_id: "u1", user_display_name: "Erwan Petit" },
    { role: 2, label: "", mode: "EACH", user_id: null, user_display_name: null },
  ],
  documents: [],
};
const fields = { editable: true, document_title: "PSSI", version_label: "1.0", status: "DRAFT", fields: [] };

/** The editor asks for the document's elements and for the campaign's signers separately; the
 *  order of the answers must not change what is shown. */
function arrange(order: "fields first" | "campaign first") {
  const gate: Record<string, () => void> = {};
  const later = (key: string, value: unknown) =>
    new Promise((resolve) => {
      gate[key] = () => resolve(value);
    });
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path.endsWith("/fields")) return later("fields", fields) as never;
    if (path.endsWith("/pages")) return Promise.resolve([{ number: 1, width: 600, height: 800 }]) as never;
    if (path === "/campaigns/c1") return later("campaign", campaign) as never;
    return Promise.resolve([]) as never;
  });
  return () => {
    const first = order === "fields first" ? "fields" : "campaign";
    const second = first === "fields" ? "campaign" : "fields";
    gate[first]?.();
    return new Promise<void>((resolve) => setTimeout(() => (gate[second]?.(), resolve()), 20));
  };
}

describe("DocumentEditor — the signers to give elements to", () => {
  beforeEach(() => vi.clearAllMocks());

  for (const order of ["fields first", "campaign first"] as const) {
    it(`shows every signer of the campaign whichever answer arrives last (${order})`, async () => {
      const release = arrange(order);
      render(
        <MemoryRouter>
          <DocumentEditor versionId="v1" campaignId="c1" embedded onFinish={vi.fn()} />
        </MemoryRouter>,
      );
      await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
      await release();
      await waitFor(() => expect(screen.getByTestId("role-2")).toHaveTextContent("Chaque destinataire"));
      expect(screen.getByTestId("role-1")).toHaveTextContent("Erwan Petit");
    });
  }
});
