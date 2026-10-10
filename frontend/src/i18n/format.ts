import i18n, { currentLocale, type Locale } from "./index";

/** Intl locales behind the two interface languages. English uses day-first dates (10/10/2026)
 *  so a date reads the same in both. Only the display changes, never the value. */
const INTL: Record<Locale, string> = { fr: "fr-FR", en: "en-GB", de: "de-DE" };

const intl = () => INTL[currentLocale()];

/** A file size, in the language's own unit (Ko / KB). */
export function formatSize(bytes: number): string {
  return i18n.t("common.sizeKb", { count: Math.round(bytes / 1024) });
}

// Two digits for day and month in every language (02/10/2026, 02.10.2026): never ambiguous.
const DATE: Intl.DateTimeFormatOptions = { day: "2-digit", month: "2-digit", year: "numeric" };
const DATE_TIME: Intl.DateTimeFormatOptions = { ...DATE, hour: "2-digit", minute: "2-digit", second: "2-digit" };

export function formatDate(value: string | Date, options: Intl.DateTimeFormatOptions = DATE): string {
  return new Date(value).toLocaleDateString(intl(), options);
}

export function formatDateTime(value: string | Date, options: Intl.DateTimeFormatOptions = DATE_TIME): string {
  return new Date(value).toLocaleString(intl(), options);
}

/** For sorting visible names in the reader's own alphabet rules. */
export function collator(): Intl.Collator {
  return new Intl.Collator(intl(), { sensitivity: "base" });
}
