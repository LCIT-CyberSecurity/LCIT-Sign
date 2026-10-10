import i18n from "../i18n";
import type { Campaign } from "../api/types";

export interface MissingSignature {
  versionId: string;
  title: string;
  /** Who: the person's name, or "Each recipient". */
  who: string;
}

/** The signers who have elements to fill on a document but no signature placed — what
 *  produced a signed document with a date and a name and nothing to say "signed". A signature
 *  is required for each. */
export function missingSignatures(campaign: Campaign): MissingSignature[] {
  const found: MissingSignature[] = [];
  for (const doc of campaign.documents) {
    for (const role of doc.element_roles ?? []) {
      if ((doc.signature_roles ?? []).includes(role)) continue;
      const party = campaign.roles.find((r) => r.role === role);
      found.push({
        versionId: doc.version_id,
        title: doc.title,
        who:
          party?.mode === "EACH"
            ? i18n.t("signatures.everyRecipient")
            : (party?.user_display_name ?? i18n.t("signatures.theSigner", { role })),
      });
    }
  }
  return found;
}

/** "Place a signature for Alice Martin on “Test03”." (in the active language) */
export function missingSignatureText(missing: MissingSignature[]): string {
  return missing.map((m) => i18n.t("signatures.placeFor", { who: m.who, title: m.title })).join(" ");
}
