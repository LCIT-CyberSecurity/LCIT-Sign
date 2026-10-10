import i18n from "../i18n";

/** The documents LCIT Sign accepts as input: a PDF, or a Word / LibreOffice file that the
 *  server converts to PDF (the PDF is what gets signed, the source is kept). */
export const DOCUMENT_PATTERN = /\.(pdf|docx|odt|doc)$/i;
export const DOCUMENT_ACCEPT = "application/pdf,.pdf,.docx,.odt,.doc";
export const documentHint = () => i18n.t("uploads.hint");
export const documentRefused = () => i18n.t("uploads.refused");

export const isAcceptedDocument = (name: string) => DOCUMENT_PATTERN.test(name);
