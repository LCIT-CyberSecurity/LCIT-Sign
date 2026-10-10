import i18n, { currentLocale, type Locale } from "./index";

/** Intl locales behind the two interface languages. English uses day-first dates (10/10/2026)
 *  so a date reads the same in both. Only the display changes, never the value. */
const INTL: Record<Locale, string> = { fr: "fr-FR", en: "en-GB" };

const intl = () => INTL[currentLocale()];

/** A file size, in the language's own unit (Ko / KB). */
export function formatSize(bytes: number): string {
  return i18n.t("common.sizeKb", { count: Math.round(bytes / 1024) });
}

export function formatDate(value: string | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleDateString(intl(), options);
}

export function formatDateTime(value: string | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleString(intl(), options);
}

/** For sorting visible names in the reader's own alphabet rules. */
export function collator(): Intl.Collator {
  return new Intl.Collator(intl(), { sensitivity: "base" });
}
