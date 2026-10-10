import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import fr from "./fr.json";
import de from "./de.json";

export const SUPPORTED_LOCALES = ["fr", "en", "de"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
/** What anyone whose language is not supported gets, and the fallback of missing texts. */
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_LABELS: Record<Locale, string> = {
  fr: "Français",
  en: "English",
  de: "Deutsch",
};
export const STORAGE_KEY = "lcit-sign.ui.locale";

export function isLocale(value: string | null | undefined): value is Locale {
  return Boolean(value && (SUPPORTED_LOCALES as readonly string[]).includes(value));
}

/** The browser's own language, reduced to a supported locale: "de-AT" and "de-CH" are German,
 *  "fr-FR" French, "en-US" English; any other language is English. */
export function detectBrowserLocale(): Locale {
  const tag = typeof navigator === "undefined" ? "" : (navigator.language ?? "");
  const primary = tag.toLowerCase().split(/[-_]/)[0];
  return isLocale(primary) ? primary : DEFAULT_LOCALE;
}

/** The person's own choice first (kept in the browser only), then the browser's language,
 *  then English. */
export function readLocale(): Locale {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (isLocale(value)) return value;
  } catch {
    // Storage unavailable: the browser's language decides.
  }
  return detectBrowserLocale();
}

function applyDocumentLocale(locale: Locale) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  document.documentElement.dir = "ltr";
}

/** Switch the interface language at once — no reload, no server call. */
export async function setLocale(value: string): Promise<Locale> {
  const locale: Locale = isLocale(value) ? value : DEFAULT_LOCALE;
  await i18n.changeLanguage(locale);
  applyDocumentLocale(locale);
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // The choice still applies for this session when storage is unavailable.
  }
  return locale;
}

/** The active locale, always one of the supported ones (what Intl formatting is given). */
export function currentLocale(): Locale {
  return isLocale(i18n.language) ? i18n.language : DEFAULT_LOCALE;
}

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, en: { translation: en }, de: { translation: de } },
  lng: readLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: SUPPORTED_LOCALES,
  interpolation: { escapeValue: false },
  returnNull: false,
});
applyDocumentLocale(currentLocale());

export { i18n };
export default i18n;
