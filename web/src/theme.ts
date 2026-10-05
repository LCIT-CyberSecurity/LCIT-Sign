// Two independent settings, both stored per browser and invisible to the
// server (same model as EARE): an *appearance* (light, dark, or whatever the
// system asks for) and a *style* (which palette the product wears). Keeping
// them apart means every style works in both appearances.

export type ThemeId = "violet" | "blue" | "aurora" | "azure" | "studio";
export type Appearance = "light" | "dark" | "system";

export const THEMES: { id: ThemeId; name: string; summary: string }[] = [
  { id: "violet", name: "Violet", summary: "La palette LCIT" },
  { id: "blue", name: "Bleu", summary: "Sobre, accent bleu" },
  { id: "aurora", name: "Aurora", summary: "Indigo, voile aurore" },
  { id: "azure", name: "Azur", summary: "Bleu clair, surfaces blanches" },
  { id: "studio", name: "Studio", summary: "Précis, presque monochrome" },
];

export const APPEARANCES: { id: Appearance; label: string }[] = [
  { id: "light", label: "Jour" },
  { id: "dark", label: "Nuit" },
  { id: "system", label: "Système" },
];

const THEME_KEY = "lcit-sign.theme";
const APPEARANCE_KEY = "lcit-sign.appearance";
export const DEFAULT_THEME: ThemeId = "violet";
const DEFAULT_APPEARANCE: Appearance = "light";

const isTheme = (value: unknown): value is ThemeId => THEMES.some((t) => t.id === value);
const isAppearance = (value: unknown): value is Appearance =>
  value === "light" || value === "dark" || value === "system";

/** Storage can be unavailable (private windows) and may throw instead of returning null. */
function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A browser that refuses storage still gets the choice for this session.
  }
}

export function readTheme(): ThemeId {
  const stored = read(THEME_KEY);
  return isTheme(stored) ? stored : DEFAULT_THEME;
}

/** "blue" is the base token set and needs no attribute; every other style does. */
export function applyTheme(theme: ThemeId): void {
  const root = document.documentElement;
  if (theme === "blue") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function storeTheme(theme: ThemeId): void {
  write(THEME_KEY, theme);
}

export function readAppearance(): Appearance {
  const stored = read(APPEARANCE_KEY);
  return isAppearance(stored) ? stored : DEFAULT_APPEARANCE;
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** The attribute carries the *resolved* appearance, so CSS never has to ask twice. */
export function applyAppearance(appearance: Appearance): void {
  const dark = appearance === "dark" || (appearance === "system" && systemPrefersDark());
  const root = document.documentElement;
  if (dark) root.setAttribute("data-appearance", "dark");
  else root.removeAttribute("data-appearance");
}

export function storeAppearance(appearance: Appearance): void {
  write(APPEARANCE_KEY, appearance);
}

/** Follows the operating system live while the viewer has chosen "Système". */
export function watchSystemAppearance(current: () => Appearance): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const react = () => {
    if (current() === "system") applyAppearance("system");
  };
  query.addEventListener("change", react);
  return () => query.removeEventListener("change", react);
}

/** Applied once, before React renders, so there is no flash of the wrong style. */
export function applyStoredPreferences(): void {
  applyTheme(readTheme());
  applyAppearance(readAppearance());
}
