import i18n from "./index";

/** A connector (directory or mail) describes its own settings: label, help, example, choices,
 *  set-up steps. The catalogue (connectors.<kind>.<source>…) carries them in both languages, but
 *  it is only used for the texts it knows: when the server sends something else (another build,
 *  a new setting) its own words are shown as they came. The French catalogue entry is the server's
 *  own sentence, which is how "known" is told. */
export type ConnectorKind = "dir" | "mail";

/** `scope` is "dir.entra", "mail.smtp"…; `path` is "label", "fields.host.help", "guide.2"… */
export function connectorText(scope: string, path: string, fallback: string): string {
  const key = `connectors.${scope}.${path}`;
  if (!i18n.exists(key)) return fallback;
  return i18n.t(key, { lng: "fr" }) === fallback ? i18n.t(key) : fallback;
}
