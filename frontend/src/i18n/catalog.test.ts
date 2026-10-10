// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import en from "./en.json";
import fr from "./fr.json";
import de from "./de.json";
import i18n, {
  DEFAULT_LOCALE,
  detectBrowserLocale,
  LOCALE_LABELS,
  STORAGE_KEY,
  SUPPORTED_LOCALES,
  isLocale,
  readLocale,
  setLocale,
} from "./index";

const leaves = (value: unknown, prefix = ""): [string, string][] =>
  typeof value === "object" && value !== null
    ? Object.entries(value).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key))
    : [[prefix, String(value)]];

const PLURAL = /_(zero|one|two|few|many|other)$/;
/** Plural forms differ per language (French keeps one sentence, English has one/other):
 *  what must match is the key without its plural suffix. */
const base = (key: string) => key.replace(PLURAL, "");
const frEntries = leaves(fr);
const enEntries = leaves(en);
const deEntries = leaves(de);
const vars = (text: string) => [...new Set([...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]))].sort();
const tags = (text: string) => [...new Set([...text.matchAll(/<\/?(\w+)\s*\/?>/g)].map((m) => m[1]))].sort();

function byBase(entries: [string, string][]) {
  const map = new Map<string, string[]>();
  for (const [key, text] of entries) map.set(base(key), [...(map.get(base(key)) ?? []), text]);
  return map;
}

describe("WebUI locale contract", () => {
  it("supports French, English and German", () => {
    expect([...SUPPORTED_LOCALES]).toEqual(["fr", "en", "de"]);
    expect(LOCALE_LABELS).toEqual({ fr: "Français", en: "English", de: "Deutsch" });
    expect(DEFAULT_LOCALE).toBe("en");
    expect(isLocale("de")).toBe(true);
    expect(isLocale("fr")).toBe(true);
    expect(isLocale("en")).toBe(true);
    expect(isLocale("es")).toBe(false);
    expect(isLocale(null)).toBe(false);
  });

  it("keeps fr.json, en.json and de.json on exactly the same keys (no missing, no extra)", () => {
    const frKeys = [...new Set(frEntries.map(([k]) => base(k)))].sort();
    const enKeys = [...new Set(enEntries.map(([k]) => base(k)))].sort();
    const deKeys = [...new Set(deEntries.map(([k]) => base(k)))].sort();
    expect(enKeys.filter((k) => !frKeys.includes(k))).toEqual([]);
    expect(frKeys.filter((k) => !enKeys.includes(k))).toEqual([]);
    expect(deKeys.filter((k) => !frKeys.includes(k))).toEqual([]);
    expect(frKeys.filter((k) => !deKeys.includes(k))).toEqual([]);
    expect(frKeys.length).toBeGreaterThan(900);
    // German has the same plural forms as English, key for key.
    expect(deEntries.map(([k]) => k).sort()).toEqual(enEntries.map(([k]) => k).sort());
  });

  it("has no empty text, and English plurals always come as one + other", () => {
    for (const [key, text] of [...frEntries, ...enEntries, ...deEntries]) expect(text.trim(), key).not.toBe("");
    for (const entries of [enEntries, deEntries]) {
      const plurals = new Map<string, string[]>();
      for (const [key] of entries) {
        const m = PLURAL.exec(key);
        if (m) plurals.set(base(key), [...(plurals.get(base(key)) ?? []), m[1]]);
      }
      for (const [key, forms] of plurals) expect(forms.sort(), key).toEqual(["one", "other"]);
    }
  });

  it("uses the same variables and markup tags in both languages", () => {
    const frByBase = byBase(frEntries);
    const union = (texts: string[], pick: (t: string) => string[]) => [...new Set(texts.flatMap(pick))].sort();
    for (const other of [byBase(enEntries), byBase(deEntries)]) {
      for (const [key, frTexts] of frByBase) {
        const texts = other.get(key) ?? [];
        expect(union(texts, vars), `variables of ${key}`).toEqual(union(frTexts, vars));
        expect(union(texts, tags), `tags of ${key}`).toEqual(union(frTexts, tags));
      }
    }
  });

  it("really translates German too, not leaving French or English behind", () => {
    const get = (c: unknown, path: string) =>
      path.split(".").reduce<unknown>((v, p) => (v as Record<string, unknown>)[p], c);
    for (const path of [
      "nav.documents",
      "nav.sign",
      "nav.tracking",
      "nav.users",
      "nav.identity",
      "nav.signingKeys",
      "nav.diagnostics",
      "common.save",
      "common.cancel",
      "common.delete",
      "status.PENDING",
      "status.SIGNED",
      "userMenu.signOut",
      "auth.signIn",
      "directory.title",
    ]) {
      expect(get(de, path), path).not.toBe(get(en, path));
      expect(get(de, path), path).not.toBe(get(fr, path));
    }
    expect(de.nav.sign).toBe("Zur Unterschrift senden");
    expect(de.status.PENDING).toBe("Ausstehend");
    expect(de.status.SIGNED).toBe("Unterzeichnet");
    // Only what is not worded the same everywhere may be identical to English: examples and
    // product names (Microsoft Entra ID, Google Workspace, LDAP / Active Directory).
    const words = (text: string) => text.replace(/\{\{[^}]*\}\}|<[^>]*>/g, "").replace(/[^A-Za-zÀ-ÿ ]/g, "").trim();
    const same = enEntries.filter(
      ([k, v]) => words(v).length > 20 && !k.endsWith(".example") && !/^connectors\.\w+\.\w+\.label$/.test(k) && deEntries.find(([dk]) => dk === k)?.[1] === v,
    );
    expect(same.map(([k]) => k)).toEqual([]);
  });

  it("really translates (the English text is not the French one) for the navigation and the main actions", () => {
    const get = (c: unknown, path: string) =>
      path.split(".").reduce<unknown>((v, p) => (v as Record<string, unknown>)[p], c);
    for (const path of [
      "nav.sign",
      "nav.tracking",
      "nav.signingKeys",
      "nav.identity",
      "common.cancel",
      "common.later",
      "userMenu.signOut",
      "auth.signIn",
      "status.PENDING",
      "campaign.status.CLOSED",
    ]) {
      expect(get(en, path), path).not.toBe(get(fr, path));
    }
  });
});

describe("locale selection", () => {
  const browser = (language: string) =>
    Object.defineProperty(window.navigator, "language", { value: language, configurable: true });
  const original = window.navigator.language;
  afterEach(() => browser(original));

  it.each([
    ["fr-FR", "fr"],
    ["fr", "fr"],
    ["fr-CA", "fr"],
    ["en-US", "en"],
    ["en-GB", "en"],
    ["de", "de"],
    ["de-DE", "de"],
    ["de-AT", "de"],
    ["de-CH", "de"],
    ["de-LU", "de"],
    ["DE-de", "de"],
    ["es-ES", "en"],
    ["it-IT", "en"],
    ["ja-JP", "en"],
    ["", "en"],
    ["xx", "en"],
  ])("takes the browser's language %s as %s when nothing is stored", (language, expected) => {
    window.localStorage.removeItem(STORAGE_KEY);
    browser(language);
    expect(detectBrowserLocale()).toBe(expected);
    expect(readLocale()).toBe(expected);
  });

  it.each([
    ["en", "de-DE", "en"],
    ["fr", "de-DE", "fr"],
    ["de", "fr-FR", "de"],
    ["de", "en-US", "de"],
    ["fr", "es-ES", "fr"],
  ])("keeps the person's own choice (%s) over the browser's language (%s)", (stored, language, expected) => {
    window.localStorage.setItem(STORAGE_KEY, stored);
    browser(language);
    expect(readLocale()).toBe(expected);
  });

  it("falls back on the browser's language when the stored value is unknown", () => {
    window.localStorage.setItem(STORAGE_KEY, "klingon");
    browser("de-AT");
    expect(readLocale()).toBe("de");
    browser("pt-BR");
    expect(readLocale()).toBe("en");
  });

  it("falls back to English and keeps its preference under its own key only", () => {
    expect(i18n.options.fallbackLng).toEqual(["en"]);
    expect(STORAGE_KEY).toBe("lcit-sign.ui.locale");
  });

  it("switches to English at once: document language, stored preference, texts", async () => {
    await setLocale("en");
    expect(document.documentElement.lang).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("en");
    expect(i18n.t("nav.sign")).toBe("Send for signature");
    await setLocale("fr");
    expect(document.documentElement.lang).toBe("fr");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("fr");
    expect(i18n.t("nav.sign")).toBe("Faire signer");
  });

  it("switches to German at once, left to right, and remembers it", async () => {
    await setLocale("de");
    expect(document.documentElement.lang).toBe("de");
    expect(document.documentElement.dir).toBe("ltr");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("de");
    expect(i18n.language).toBe("de");
    expect(i18n.t("nav.sign")).toBe("Zur Unterschrift senden");
    expect(i18n.t("campaign.status.ACTIVE")).toBe("Aktiv");
    // Plurals follow German: one / other.
    expect(i18n.t("counts.documents", { count: 1 })).toBe("1 Dokument");
    expect(i18n.t("counts.documents", { count: 3 })).toBe("3 Dokumente");
    // The manual choice then wins over a browser that says otherwise.
    browser("fr-FR");
    expect(readLocale()).toBe("de");
  });

  it("turns an unknown locale into the English fallback", async () => {
    await setLocale("de");
    await setLocale("zz");
    expect(document.documentElement.lang).toBe("en");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("en");
    expect(i18n.language).toBe("en");
  });

  it("keeps the browser's other preferences out of it (nothing but the one key is written)", async () => {
    window.localStorage.clear();
    await setLocale("de");
    expect(Object.keys(window.localStorage)).toEqual([STORAGE_KEY]);
  });
});
