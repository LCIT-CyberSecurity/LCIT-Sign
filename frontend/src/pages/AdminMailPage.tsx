import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Mail, Send, Plug } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import MailConnectorForm from "./MailConnectorForm";
import type { MailConnectorConfig, MailKindSpec } from "../api/types";

export default function AdminMailPage() {
  const { t } = useTranslation();
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
      setMessage(t("mail.testSent", { to: testEmail }));
    } catch (err) {
      setMessage(errorText(err, "mail.sendFailed"));
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
      setMessage(errorText(err, "mail.isolationFailed"));
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <Mail size={20} aria-hidden="true" /> {t("mail.title")}
      </h1>

      {message && <p className="muted">{message}</p>}
      {kinds && loaded && (
        <MailConnectorForm
          kinds={kinds}
          config={config}
          onSaved={(saved) => {
            setConfig(saved);
            setMessage(t("directory.form.saved"));
          }}
        />
      )}

      <div className="card">
        <div className="card-title">{t("mail.diagnostic")}</div>
        <button className="button button--secondary" onClick={testConnection}>
          <Plug size={14} aria-hidden="true" /> {t("mail.testConnection")}
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
          <div className="card-title">{t("mail.isolationTitle")}</div>
          <p className="muted small">
            {t("mail.isolationHelp")}
          </p>
          <div className="form-row">
            <input
              placeholder={t("mail.otherMailboxPlaceholder")}
              aria-label={t("mail.otherMailbox")}
              value={probeMailbox}
              onChange={(e) => setProbeMailbox(e.target.value)}
            />
            <button className="button button--secondary" onClick={testIsolation}>
              {t("mail.testIsolation")}
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
        <div className="card-title">{t("mail.testTitle")}</div>
        <div className="form-row">
          <input
            placeholder={t("mail.recipientPlaceholder")}
            value={testEmail}
            onChange={(e) => setTestEmail(e.target.value)}
          />
          <button className="button button--secondary" onClick={sendTest}>
            <Send size={14} aria-hidden="true" /> {t("mail.send")}
          </button>
        </div>
      </div>
    </div>
  );
}
