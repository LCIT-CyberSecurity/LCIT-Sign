/** The documents LCIT Sign accepts as input: a PDF, or a Word / LibreOffice file that the
 *  server converts to PDF (the PDF is what gets signed, the source is kept). */
export const DOCUMENT_PATTERN = /\.(pdf|docx|odt|doc)$/i;
export const DOCUMENT_ACCEPT = "application/pdf,.pdf,.docx,.odt,.doc";
export const DOCUMENT_HINT = "PDF, Word ou LibreOffice, plusieurs à la fois";
export const DOCUMENT_REFUSED = "Formats acceptés : PDF, Word (.docx, .doc) et LibreOffice (.odt).";

export const isAcceptedDocument = (name: string) => DOCUMENT_PATTERN.test(name);
