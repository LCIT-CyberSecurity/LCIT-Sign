import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import fr from "./fr.json";

export const SUPPORTED_LOCALES = ["fr", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "fr";
export const LOCALE_LABELS: Record<Locale, string> = {
  fr: "Français",
  en: "English",
};
export const STORAGE_KEY = "lcit-sign.ui.locale";

export function isLocale(value: string | null | undefined): value is Locale {
  return Boolean(value && (SUPPORTED_LOCALES as readonly string[]).includes(value));
}

/** The browser preference only: French when nothing (or something unknown) is stored.
 *  The browser's own language is deliberately not consulted. */
export function readLocale(): Locale {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
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
  resources: { fr: { translation: fr }, en: { translation: en } },
  lng: readLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: SUPPORTED_LOCALES,
  interpolation: { escapeValue: false },
  returnNull: false,
});
applyDocumentLocale(currentLocale());

export { i18n };
export default i18n;
