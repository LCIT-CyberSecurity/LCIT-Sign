import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
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
  const [kind, setKind] = useState<MailKindSpec["kind"]>(config?.kind ?? "smtp");
  const [values, setValues] = useState<Record<string, string>>(valuesOf(config));
  const [secret, setSecret] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const spec = kinds.find((k) => k.kind === kind);
  if (!spec) return null;

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
      setMessage("Configuration enregistrée (secret chiffré).");
      onSaved(saved);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Échec de l'enregistrement.");
    }
  };

  return (
    <form className="card form" onSubmit={save} autoComplete="off">
      <label>
        Type de connecteur
        <select value={kind} onChange={(e) => setKind(e.target.value as MailKindSpec["kind"])}>
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <p className="muted small" data-testid="mail-kind-description">
        {spec.description}
      </p>

      {spec.fields.map((f) => (
        <div key={f.name} className="field">
          <span className="label-line">
            <label htmlFor={`mail-${f.name}`}>{f.label}</label>
            <HelpHint title={f.label} example={f.example || undefined}>
              {f.help}
            </HelpHint>
          </span>
          <ConnectorFieldControl
            id={`mail-${f.name}`}
            field={f}
            value={valueOf(f.name, f.kind === "text" || f.kind === "number" ? f.default : "")}
            onChange={(value) => setValues({ ...values, [f.name]: value })}
          />
        </div>
      ))}

      <div className="field">
        <span className="label-line">
          <label htmlFor="mail-secret">{spec.secret.label}</label>
          <HelpHint title={spec.secret.label} example={spec.secret.example || undefined}>
            {spec.secret.help}
          </HelpHint>
        </span>
        <ConnectorFieldControl
          id="mail-secret"
          field={spec.secret}
          value={secret}
          onChange={setSecret}
          secret
          stored={stored}
        />
      </div>

      {message && <p className="muted" role="status">{message}</p>}
      <button className="button button--primary" type="submit">
        Enregistrer
      </button>
    </form>
  );
}
