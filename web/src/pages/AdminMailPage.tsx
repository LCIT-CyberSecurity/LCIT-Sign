import { useEffect, useState, type FormEvent } from "react";
import { Mail, Send, Plug } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { MailConnectorConfig } from "../api/types";

export default function AdminMailPage() {
  const [config, setConfig] = useState<MailConnectorConfig | null>(null);
  const [form, setForm] = useState({
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

  useEffect(() => {
    api
      .get<MailConnectorConfig | null>("/admin/mail-connector")
      .then((existing) => {
        setConfig(existing);
        if (existing) {
          setForm((f) => ({
            ...f,
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
    const body = { ...form, password: form.password || null };
    const saved = await api.put<MailConnectorConfig>("/admin/mail-connector", body);
    setConfig(saved);
    setMessage("Configuration enregistrée.");
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

  return (
    <div className="stack">
      <h1 className="page-title">
        <Mail size={20} aria-hidden="true" /> Configuration SMTP
      </h1>

      <form className="card form" onSubmit={save}>
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
        <div className="form-row">
          <label>
            Utilisateur
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </label>
          <label>
            Mot de passe {config?.password_configured && <span className="muted small">(déjà configuré)</span>}
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
            Adresse d&apos;expédition
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
