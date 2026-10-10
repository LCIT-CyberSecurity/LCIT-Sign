import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { connectorText } from "../i18n/connectors";
import ConnectorFieldControl from "../components/ConnectorFieldControl";
import HelpHint from "../components/HelpHint";
import type { MailConnectorConfig, MailKindSpec } from "../api/types";

/** What each setting holds today, as text, whichever kind of connector is saved. */
function valuesOf(config: MailConnectorConfig | null): Record<string, string> {
  if (!config) return {};
  return {
    host: config.host,
    port: String(config.port),
    use_tls: String(config.use_tls),
    use_starttls: String(config.use_starttls),
    username: config.username,
    graph_tenant_id: config.graph_tenant_id ?? "",
    graph_client_id: config.graph_client_id ?? "",
    from_address: config.from_address,
    reply_to: config.reply_to ?? "",
  };
}

/** The form of the chosen mail connector, drawn from the description the server gives of it:
 *  a help bubble with an example on every setting, and its one write-only secret. */
export default function MailConnectorForm({
  kinds,
  config,
  onSaved,
}: {
  kinds: MailKindSpec[];
  config: MailConnectorConfig | null;
  onSaved: (saved: MailConnectorConfig) => void;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<MailKindSpec["kind"]>(config?.kind ?? "smtp");
  const [values, setValues] = useState<Record<string, string>>(valuesOf(config));
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const spec = kinds.find((k) => k.kind === kind);
  if (!spec) return null;

  const scope = `mail.${kind}`;
  const fieldText = (f: MailKindSpec["fields"][number], part: "label" | "help" | "example") =>
    connectorText(scope, `fields.${f.name}.${part}`, f[part]);
  const secretText = (part: "label" | "help" | "example") => connectorText(scope, `secret.${part}`, spec.secret[part]);
  const valueOf = (name: string, fallback: string) => values[name] ?? fallback;
  // The secret saved belongs to the kind saved: another kind needs its own.
  const stored = Boolean(config?.password_configured) && config?.kind === kind;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setMessage(null);
    const field = (name: string) => spec.fields.find((f) => f.name === name);
    const text = (name: string) => (field(name) ? valueOf(name, field(name)!.default).trim() : "");
    const body = {
      kind,
      host: text("host"),
      port: Number(text("port") || 587),
      use_tls: text("use_tls") === "true",
      use_starttls: field("use_starttls") ? text("use_starttls") === "true" : true,
      username: text("username"),
      graph_tenant_id: kind === "graph" ? text("graph_tenant_id") : null,
      graph_client_id: kind === "graph" ? text("graph_client_id") : null,
      from_address: text("from_address"),
      reply_to: text("reply_to") || null,
      password: secret || null,
    };
    try {
      const saved = await api.put<MailConnectorConfig>("/admin/mail-connector", body);
      // The secret never stays in the page once it has been sent.
      setSecret("");
      setMessage(t("directory.form.saved"));
      onSaved(saved);
    } catch (err) {
      setMessage(errorText(err, "directory.form.saveFailed"));
    }
  };

  return (
    <form className="card form" onSubmit={save} autoComplete="off">
      <label>
        {t("mail.connectorType")}
        <select value={kind} onChange={(e) => setKind(e.target.value as MailKindSpec["kind"])}>
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind}>
              {connectorText(`mail.${k.kind}`, "label", k.label)}
            </option>
          ))}
        </select>
      </label>
      <p className="muted small" data-testid="mail-kind-description">
        {connectorText(scope, "description", spec.description)}
      </p>

      {spec.fields.map((f) => (
        <div key={f.name} className="field">
          <span className="label-line">
            <label htmlFor={`mail-${f.name}`}>{fieldText(f, "label")}</label>
            <HelpHint title={fieldText(f, "label")} example={fieldText(f, "example") || undefined}>
              {fieldText(f, "help")}
            </HelpHint>
          </span>
          <ConnectorFieldControl
            id={`mail-${f.name}`}
            scope={scope}
            field={f}
            value={valueOf(f.name, f.kind === "text" || f.kind === "number" ? f.default : "")}
            onChange={(value) => setValues({ ...values, [f.name]: value })}
          />
        </div>
      ))}

      <div className="field">
        <span className="label-line">
          <label htmlFor="mail-secret">{secretText("label")}</label>
          <HelpHint title={secretText("label")} example={secretText("example") || undefined}>
            {secretText("help")}
          </HelpHint>
        </span>
        <ConnectorFieldControl
          id="mail-secret"
          scope={scope}
          field={spec.secret}
          value={secret}
          onChange={setSecret}
          secret
          stored={stored}
        />
      </div>

      {message && <p className="muted" role="status">{message}</p>}
      <button className="button button--primary" type="submit">
        {t("common.save")}
      </button>
    </form>
  );
}
