import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import UploadDropzone from "./UploadDropzone";
import { deriveTitle } from "../pages/OperatorDocumentsPage";

const pdf = (name: string) => new File(["%PDF-1.4"], name, { type: "application/pdf" });

describe("<UploadDropzone />", () => {
  it("hands over every dropped file", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} />);
    const zone = screen.getByTestId("dropzone");
    fireEvent.dragOver(zone);
    expect(zone.className).toContain("dropzone--over");
    fireEvent.drop(zone, { dataTransfer: { files: [pdf("a.pdf"), pdf("b.pdf")] } });
    expect(zone.className).not.toContain("dropzone--over");
    expect(onFiles).toHaveBeenCalledWith([expect.objectContaining({ name: "a.pdf" }), expect.objectContaining({ name: "b.pdf" })]);
  });

  it("also works through the file picker", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} />);
    fireEvent.change(screen.getByTestId("dropzone-input"), { target: { files: [pdf("c.pdf")] } });
    expect(onFiles).toHaveBeenCalledOnce();
  });

  it("ignores a drop while it is busy", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone onFiles={onFiles} disabled />);
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [pdf("a.pdf")] } });
    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe("deriveTitle", () => {
  it("makes a readable title from a file name", () => {
    expect(deriveTitle("charte_informatique-2026.pdf")).toBe("Charte informatique 2026");
    expect(deriveTitle("  politique   BYOD.PDF")).toBe("Politique BYOD");
    expect(deriveTitle(".pdf")).toBe("Document");
  });
});
