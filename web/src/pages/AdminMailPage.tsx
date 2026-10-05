import { useEffect, useState, type FormEvent } from "react";
import { Mail, Send, Plug } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { MailConnectorConfig } from "../api/types";

export default function AdminMailPage() {
  const [config, setConfig] = useState<MailConnectorConfig | null>(null);
  const [form, setForm] = useState({
    kind: "smtp" as "smtp" | "graph",
    graph_tenant_id: "",
    graph_client_id: "",
    host: "",
    port: 587,
    use_tls: false,
    use_starttls: true,
    username: "",
    password: "",
    from_address: "",
    reply_to: "",
    timeout_seconds: 10,
  });
  const [diagnostics, setDiagnostics] = useState<Record<string, string> | null>(null);
  const [testEmail, setTestEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [probeMailbox, setProbeMailbox] = useState("");
  const [isolation, setIsolation] = useState<{ isolated: boolean; detail: string } | null>(null);

  useEffect(() => {
    api
      .get<MailConnectorConfig | null>("/admin/mail-connector")
      .then((existing) => {
        setConfig(existing);
        if (existing) {
          setForm((f) => ({
            ...f,
            kind: existing.kind,
            graph_tenant_id: existing.graph_tenant_id ?? "",
            graph_client_id: existing.graph_client_id ?? "",
            host: existing.host,
            port: existing.port,
            use_tls: existing.use_tls,
            use_starttls: existing.use_starttls,
            username: existing.username,
            from_address: existing.from_address,
            reply_to: existing.reply_to ?? "",
            timeout_seconds: existing.timeout_seconds,
          }));
        }
      });
  }, []);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const body = {
      ...form,
      graph_tenant_id: form.kind === "graph" ? form.graph_tenant_id : null,
      graph_client_id: form.kind === "graph" ? form.graph_client_id : null,
      password: form.password || null,
    };
    const saved = await api.put<MailConnectorConfig>("/admin/mail-connector", body);
    setConfig(saved);
    setForm((f) => ({ ...f, password: "" }));
    setMessage("Configuration enregistrée (secret chiffré).");
  };

  const testConnection = async () => {
    const result = await api.post<Record<string, string>>("/admin/mail-connector/test-connection");
    setDiagnostics(result);
  };

  const sendTest = async () => {
    try {
      await api.post("/admin/mail-connector/send-test", { to: testEmail });
      setMessage(`E-mail de test envoyé à ${testEmail}.`);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Échec de l'envoi.");
    }
  };

  const testIsolation = async () => {
    setIsolation(null);
    try {
      setIsolation(
        await api.post<{ isolated: boolean; detail: string }>("/admin/mail-connector/test-isolation", {
          other_mailbox: probeMailbox,
          to: testEmail,
        }),
      );
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Le test d'isolation a échoué.");
    }
  };

  const isGraph = form.kind === "graph";

  return (
    <div className="stack">
      <h1 className="page-title">
        <Mail size={20} aria-hidden="true" /> Configuration e-mail
      </h1>

      <form className="card form" onSubmit={save}>
        <label>
          Type de connecteur
          <select
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value as "smtp" | "graph" })}
          >
            <option value="smtp">SMTP</option>
            <option value="graph">Microsoft 365 (Graph)</option>
          </select>
        </label>
        {isGraph && (
          <div className="form-row">
            <label>
              ID du tenant
              <input
                value={form.graph_tenant_id}
                onChange={(e) => setForm({ ...form, graph_tenant_id: e.target.value })}
                required
              />
            </label>
            <label>
              ID de l&apos;application (client)
              <input
                value={form.graph_client_id}
                onChange={(e) => setForm({ ...form, graph_client_id: e.target.value })}
                required
              />
            </label>
          </div>
        )}
        {!isGraph && (
        <>
        <div className="form-row">
          <label>
            Hôte
            <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} required />
          </label>
          <label>
            Port
            <input
              type="number"
              value={form.port}
              onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
              required
            />
          </label>
        </div>
        <div className="form-row">
          <label className="consent-row">
            <input
              type="checkbox"
              checked={form.use_tls}
              onChange={(e) => setForm({ ...form, use_tls: e.target.checked })}
            />
            TLS implicite
          </label>
          <label className="consent-row">
            <input
              type="checkbox"
              checked={form.use_starttls}
              onChange={(e) => setForm({ ...form, use_starttls: e.target.checked })}
            />
            STARTTLS
          </label>
        </div>
        </>
        )}
        <div className="form-row">
          {!isGraph && (
          <label>
            Utilisateur
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </label>
          )}
          <label>
            {isGraph ? "Secret client" : "Mot de passe"}{" "}
            {config?.password_configured && <span className="muted small">(déjà configuré)</span>}
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder={config?.password_configured ? "Laisser vide pour conserver" : ""}
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            {isGraph ? "Boîte d'envoi dédiée" : "Adresse d'expédition"}
            <input
              value={form.from_address}
              onChange={(e) => setForm({ ...form, from_address: e.target.value })}
              required
            />
          </label>
          <label>
            Reply-To
            <input
              value={form.reply_to}
              onChange={(e) => setForm({ ...form, reply_to: e.target.value })}
            />
          </label>
        </div>
        {message && <p className="muted">{message}</p>}
        <button className="button button--primary" type="submit">
          Enregistrer
        </button>
      </form>

      <div className="card">
        <div className="card-title">Diagnostic</div>
        <button className="button button--secondary" onClick={testConnection}>
          <Plug size={14} aria-hidden="true" /> Tester la connexion
        </button>
        {diagnostics && (
          <ul className="plain-list">
            {Object.entries(diagnostics).map(([step, result]) => (
              <li key={step}>
                {step.toUpperCase()} : {result}
              </li>
            ))}
          </ul>
        )}
      </div>

      {config?.kind === "graph" && (
        <div className="card">
          <div className="card-title">Test d&apos;isolation (obligatoire avant mise en service)</div>
          <p className="muted small">
            Tente d&apos;envoyer en tant qu&apos;une AUTRE boîte vers l&apos;adresse de test ci-dessous. Exchange doit
            refuser : sinon l&apos;application peut envoyer au nom de n&apos;importe qui. Voir
            docs/microsoft-graph-setup.md.
          </p>
          <div className="form-row">
            <input
              placeholder="autre.boite@example.com"
              aria-label="Autre boîte à tester"
              value={probeMailbox}
              onChange={(e) => setProbeMailbox(e.target.value)}
            />
            <button className="button button--secondary" onClick={testIsolation}>
              Tester l&apos;isolation
            </button>
          </div>
          {isolation && (
            <p role="status" className={isolation.isolated ? "status-ok" : "status-error"}>
              {isolation.isolated ? "✓ " : "✕ "}
              {isolation.detail}
            </p>
          )}
        </div>
      )}

      <div className="card">
        <div className="card-title">E-mail de test</div>
        <div className="form-row">
          <input
            placeholder="destinataire@example.com"
            value={testEmail}
            onChange={(e) => setTestEmail(e.target.value)}
          />
          <button className="button button--secondary" onClick={sendTest}>
            <Send size={14} aria-hidden="true" /> Envoyer
          </button>
        </div>
      </div>
    </div>
  );
}
