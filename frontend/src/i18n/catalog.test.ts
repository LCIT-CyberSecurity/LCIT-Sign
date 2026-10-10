// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import en from "./en.json";
import fr from "./fr.json";
import i18n, {
  DEFAULT_LOCALE,
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
const vars = (text: string) => [...new Set([...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]))].sort();
const tags = (text: string) => [...new Set([...text.matchAll(/<\/?(\w+)\s*\/?>/g)].map((m) => m[1]))].sort();

function byBase(entries: [string, string][]) {
  const map = new Map<string, string[]>();
  for (const [key, text] of entries) map.set(base(key), [...(map.get(base(key)) ?? []), text]);
  return map;
}

describe("WebUI locale contract", () => {
  it("supports French and English only, French first", () => {
    expect([...SUPPORTED_LOCALES]).toEqual(["fr", "en"]);
    expect(LOCALE_LABELS).toEqual({ fr: "Français", en: "English" });
    expect(DEFAULT_LOCALE).toBe("fr");
    expect(isLocale("fr")).toBe(true);
    expect(isLocale("en")).toBe(true);
    expect(isLocale("de")).toBe(false);
    expect(isLocale(null)).toBe(false);
  });

  it("keeps fr.json and en.json on exactly the same keys (no missing, no extra)", () => {
    const frKeys = [...new Set(frEntries.map(([k]) => base(k)))].sort();
    const enKeys = [...new Set(enEntries.map(([k]) => base(k)))].sort();
    expect(enKeys.filter((k) => !frKeys.includes(k))).toEqual([]);
    expect(frKeys.filter((k) => !enKeys.includes(k))).toEqual([]);
    expect(frKeys.length).toBeGreaterThan(900);
  });

  it("has no empty text, and English plurals always come as one + other", () => {
    for (const [key, text] of [...frEntries, ...enEntries]) expect(text.trim(), key).not.toBe("");
    const plurals = new Map<string, string[]>();
    for (const [key] of enEntries) {
      const m = PLURAL.exec(key);
      if (m) plurals.set(base(key), [...(plurals.get(base(key)) ?? []), m[1]]);
    }
    for (const [key, forms] of plurals) expect(forms.sort(), key).toEqual(["one", "other"]);
  });

  it("uses the same variables and markup tags in both languages", () => {
    const frByBase = byBase(frEntries);
    const enByBase = byBase(enEntries);
    for (const [key, frTexts] of frByBase) {
      const enTexts = enByBase.get(key) ?? [];
      const union = (texts: string[], pick: (t: string) => string[]) => [...new Set(texts.flatMap(pick))].sort();
      expect(union(enTexts, vars), `variables of ${key}`).toEqual(union(frTexts, vars));
      expect(union(enTexts, tags), `tags of ${key}`).toEqual(union(frTexts, tags));
    }
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
  it("is French when nothing is stored, and ignores the browser's language", () => {
    window.localStorage.removeItem(STORAGE_KEY);
    Object.defineProperty(window.navigator, "language", { value: "en-US", configurable: true });
    expect(readLocale()).toBe("fr");
  });

  it("is French when the stored value is unknown", () => {
    window.localStorage.setItem(STORAGE_KEY, "klingon");
    expect(readLocale()).toBe("fr");
    window.localStorage.setItem(STORAGE_KEY, "en");
    expect(readLocale()).toBe("en");
  });

  it("falls back to French and stores the preference under its own key only", () => {
    expect(i18n.options.fallbackLng).toEqual(["fr"]);
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

  it("turns an unknown locale into French", async () => {
    await setLocale("en");
    await setLocale("zz");
    expect(document.documentElement.lang).toBe("fr");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("fr");
    expect(i18n.language).toBe("fr");
  });

  it("keeps the browser's other preferences out of it (nothing but the one key is written)", async () => {
    window.localStorage.clear();
    await setLocale("en");
    expect(Object.keys(window.localStorage)).toEqual([STORAGE_KEY]);
  });
});
