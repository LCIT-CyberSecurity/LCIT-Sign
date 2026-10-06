import { describe, expect, it } from "vitest";
import { isAcceptedDocument } from "./uploads";

describe("isAcceptedDocument", () => {
  it("accepts a PDF, Word and LibreOffice file, whatever the case", () => {
    for (const name of ["a.pdf", "A.PDF", "b.docx", "c.odt", "d.doc", "mon rapport v2.Docx"]) {
      expect(isAcceptedDocument(name)).toBe(true);
    }
  });

  it("refuses anything else, and a name that only contains the extension", () => {
    for (const name of ["a.exe", "b.docm", "c.xlsx", "d.txt", "pdf", "e.pdf.exe", "f.doc.zip"]) {
      expect(isAcceptedDocument(name)).toBe(false);
    }
  });
});
