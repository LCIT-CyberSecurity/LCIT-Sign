import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import OperatorDocumentsPage from "./OperatorDocumentsPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), postForm: vi.fn(), post: vi.fn(), del: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const pdf = (name: string) => new File(["%PDF-1.4"], name, { type: "application/pdf" });

function drop(...files: File[]) {
  fireEvent.change(screen.getByTestId("dropzone-input"), { target: { files } });
}

describe("OperatorDocumentsPage upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockResolvedValue([]);
    vi.mocked(api.postForm).mockResolvedValue({});
  });

  it("keeps dropped files waiting until the operator clicks Importer", async () => {
    render(<MemoryRouter><OperatorDocumentsPage /></MemoryRouter>);
    drop(pdf("charte_it-2026.pdf"));
    expect(screen.getByTestId("pending-files")).toHaveTextContent("charte_it-2026.pdf");
    expect(api.postForm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Importer le document" }));
    await waitFor(() => expect(api.postForm).toHaveBeenCalledTimes(1));
    const form = vi.mocked(api.postForm).mock.calls[0][1] as FormData;
    expect(form.get("title")).toBe("Charte it 2026");
    expect(screen.queryByTestId("pending-files")).toBeNull();
  });

  it("uses the title typed before the click, and lets a file be removed or all cancelled", async () => {
    render(<MemoryRouter><OperatorDocumentsPage /></MemoryRouter>);
    drop(pdf("a.pdf"), pdf("b.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Retirer a.pdf" }));
    expect(screen.getByTestId("pending-files")).not.toHaveTextContent("a.pdf");

    fireEvent.change(screen.getByLabelText(/Titre/), { target: { value: "Mon titre" } });
    fireEvent.click(screen.getByRole("button", { name: "Importer le document" }));
    await waitFor(() => expect(api.postForm).toHaveBeenCalledTimes(1));
    expect((vi.mocked(api.postForm).mock.calls[0][1] as FormData).get("title")).toBe("Mon titre");

    drop(pdf("c.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByTestId("pending-files")).toBeNull();
    expect(api.postForm).toHaveBeenCalledTimes(1);
  });

  it("takes Word and LibreOffice files like a PDF, and refuses other types in words", async () => {
    render(<MemoryRouter><OperatorDocumentsPage /></MemoryRouter>);
    expect(screen.getByTestId("dropzone-input")).toHaveAttribute("accept", expect.stringContaining(".docx"));
    drop(
      new File(["x"], "contrat_alpha.docx"),
      new File(["x"], "note.odt"),
      new File(["x"], "ancien.doc"),
      new File(["x"], "virus.exe"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Importer 4 documents" }));
    await waitFor(() => expect(api.postForm).toHaveBeenCalledTimes(3));
    const titles = vi.mocked(api.postForm).mock.calls.map((c) => (c[1] as FormData).get("title"));
    expect(titles).toEqual(["Contrat alpha", "Note", "Ancien"]);
    expect(await screen.findByText(/Formats acceptés : PDF, Word/)).toBeInTheDocument();
  });
});
