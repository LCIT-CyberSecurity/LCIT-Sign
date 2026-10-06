import { useEffect, useState } from "react";
import { Mail, Send, Plug } from "lucide-react";
import { api, ApiError } from "../api/client";
import MailConnectorForm from "./MailConnectorForm";
import type { MailConnectorConfig, MailKindSpec } from "../api/types";

export default function AdminMailPage() {
  const [config, setConfig] = useState<MailConnectorConfig | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [kinds, setKinds] = useState<MailKindSpec[] | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, string> | null>(null);
  const [testEmail, setTestEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [probeMailbox, setProbeMailbox] = useState("");
  const [isolation, setIsolation] = useState<{ isolated: boolean; detail: string } | null>(null);

  useEffect(() => {
    api.get<MailKindSpec[]>("/admin/mail-connector/kinds").then(setKinds);
    api.get<MailConnectorConfig | null>("/admin/mail-connector").then((existing) => {
      setConfig(existing);
      setLoaded(true);
    });
  }, []);

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

  return (
    <div className="stack">
      <h1 className="page-title">
        <Mail size={20} aria-hidden="true" /> Configuration e-mail
      </h1>

      {message && <p className="muted">{message}</p>}
      {kinds && loaded && (
        <MailConnectorForm
          kinds={kinds}
          config={config}
          onSaved={(saved) => {
            setConfig(saved);
            setMessage("Configuration enregistrée (secret chiffré).");
          }}
        />
      )}

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
