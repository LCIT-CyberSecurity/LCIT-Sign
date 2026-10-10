import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, KeyRound, Languages, LogOut, Monitor, Moon, Palette, Sun } from "lucide-react";
import {
  APPEARANCES,
  THEMES,
  applyAppearance,
  applyTheme,
  readAppearance,
  readTheme,
  storeAppearance,
  storeTheme,
  watchSystemAppearance,
  type Appearance,
  type ThemeId,
} from "../theme";
import { LOCALE_LABELS, SUPPORTED_LOCALES, currentLocale, setLocale } from "../i18n";
import type { Me } from "../api/types";

/** The API role values stay as they are; only what is displayed is translated. */
const ROLE_KEYS: Record<string, string> = {
  SIGNER: "roles.signer",
  OPERATOR: "roles.operator",
  ADMIN: "roles.admin",
};

export function initials(name: string | undefined): string {
  return (name ?? "?")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/** The account menu: who you are and which profiles (roles) you hold, the
 *  interface appearance (day / night / system), the interface style, and
 *  sign-out. Laid out like EARE's. */
export default function UserMenu({
  user,
  onSignOut,
  onChangePassword,
}: {
  user: Me;
  onSignOut: () => void;
  onChangePassword?: () => void;
}) {
  const { t } = useTranslation();
  const menu = useRef<HTMLDetailsElement>(null);
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);

  const roles = user.roles.map((role) => (ROLE_KEYS[role] ? t(ROLE_KEYS[role]) : role));
  const primaryRole = roles.length ? roles[roles.length - 1] : t("roles.user");
  const locale = currentLocale();

  const pickTheme = (next: ThemeId) => {
    setTheme(next);
    applyTheme(next);
    storeTheme(next);
  };
  const pickAppearance = (next: Appearance) => {
    setAppearance(next);
    applyAppearance(next);
    storeAppearance(next);
  };

  const appearanceRef = useRef(appearance);
  appearanceRef.current = appearance;
  useEffect(() => watchSystemAppearance(() => appearanceRef.current), []);

  // Close on outside click and on Escape, like a native menu.
  useEffect(() => {
    const onPointer = (event: MouseEvent) => {
      if (menu.current?.open && !menu.current.contains(event.target as Node)) {
        menu.current.removeAttribute("open");
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") menu.current?.removeAttribute("open");
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <details className="user-menu" ref={menu}>
      <summary aria-label={t("userMenu.account")}>
        <span className="avatar">{initials(user.display_name)}</span>
        <span className="user-name">
          {user.display_name}
          <span>{primaryRole}</span>
        </span>
        <ChevronDown size={15} aria-hidden="true" />
      </summary>
      <div className="user-menu-panel">
        <div className="user-menu-head">
          <span className="avatar">{initials(user.display_name)}</span>
          <span>
            <strong>{user.display_name}</strong>
            <small>{user.email}</small>
          </span>
        </div>

        <div className="user-menu-section">
          <span className="user-menu-label">{t("userMenu.profiles")}</span>
          <div className="badge-list" style={{ padding: "2px 10px 6px" }}>
            {roles.map((role) => (
              <span key={role} className="badge badge--viewed">
                {role}
              </span>
            ))}
          </div>
        </div>

        <div className="user-menu-section">
          <span className="user-menu-label">
            <Palette size={13} aria-hidden="true" /> {t("userMenu.settings")}
          </span>
          <div className="appearance-row" role="group" aria-label={t("userMenu.appearance")}>
            {APPEARANCES.map((option) => {
              const Icon = option.id === "light" ? Sun : option.id === "dark" ? Moon : Monitor;
              return (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={appearance === option.id}
                  className={"appearance-option" + (appearance === option.id ? " active" : "")}
                  onClick={() => pickAppearance(option.id)}
                >
                  <Icon aria-hidden="true" size={14} /> {t(`appearance.${option.id}`)}
                </button>
              );
            })}
          </div>
          {THEMES.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={theme === option.id}
              className={"style-option" + (theme === option.id ? " active" : "")}
              onClick={() => pickTheme(option.id)}
            >
              <span className={"style-swatch " + option.id} />
              <span className="style-option-text">
                <strong>{t(`theme.${option.id}.name`)}</strong>
                <small>{t(`theme.${option.id}.summary`)}</small>
              </span>
              {theme === option.id ? <Check size={15} aria-hidden="true" /> : null}
            </button>
          ))}
        </div>

        <div className="user-menu-section">
          <span className="user-menu-label">
            <Languages size={13} aria-hidden="true" /> {t("userMenu.language")}
          </span>
          {SUPPORTED_LOCALES.map((code) => (
            <button
              key={code}
              type="button"
              lang={code}
              aria-pressed={locale === code}
              className={"style-option" + (locale === code ? " active" : "")}
              onClick={() => void setLocale(code)}
            >
              <span className="style-option-text">
                <strong>{LOCALE_LABELS[code]}</strong>
              </span>
              {locale === code ? <Check size={15} aria-hidden="true" /> : null}
            </button>
          ))}
        </div>

        <div className="user-menu-foot">
          {(user.source === "builtin" || user.source === "local") && onChangePassword && (
            <button
              type="button"
              onClick={() => {
                menu.current?.removeAttribute("open");
                onChangePassword();
              }}
            >
              <KeyRound size={15} aria-hidden="true" /> {t("userMenu.changePassword")}
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              menu.current?.removeAttribute("open");
              onSignOut();
            }}
          >
            <LogOut size={15} aria-hidden="true" /> {t("userMenu.signOut")}
          </button>
        </div>
      </div>
    </details>
  );
}
