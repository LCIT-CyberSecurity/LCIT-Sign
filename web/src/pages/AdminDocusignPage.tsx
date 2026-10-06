import { useEffect, useState } from "react";
import { FileSignature, Plug, FlaskConical } from "lucide-react";
import { api, ApiError } from "../api/client";
import ConnectorFieldControl from "../components/ConnectorFieldControl";
import HelpHint from "../components/HelpHint";
import type { DocusignAdmin } from "../api/types";

/** The DocuSign connection: the settings with a help bubble on each, the private key (written once,
 *  never shown again), a test of the connection, and — on a test server — the mock DocuSign. */
export default function AdminDocusignPage() {
  const [config, setConfig] = useState<DocusignAdmin | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [privateKey, setPrivateKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [tested, setTested] = useState<{ ok: boolean; message: string } | null>(null);

  const show = (next: DocusignAdmin) => {
    setConfig(next);
    setValues(next.values);
  };
  useEffect(() => {
    api.get<DocusignAdmin>("/admin/docusign").then(show);
  }, []);

  if (!config) return <p className="muted">Chargement…</p>;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    setTested(null);
    try {
      show(
        await api.put<DocusignAdmin>("/admin/docusign", {
          environment: values.environment || "demo",
          integration_key: values.integration_key ?? "",
          user_id: values.user_id ?? "",
          account_id: values.account_id ?? "",
          private_key: privateKey || undefined,
        }),
      );
      // The key never stays in the page once it has been sent.
      setPrivateKey("");
      setMessage("Connexion enregistrée (clé chiffrée).");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Échec de l'enregistrement.");
    }
  };

  const test = async () => {
    setTested(null);
    try {
      setTested(await api.post<{ ok: boolean; message: string }>("/admin/docusign/test-connection"));
    } catch (err) {
      setTested({ ok: false, message: err instanceof ApiError ? err.message : "Le test a échoué." });
    }
  };

  const useMock = async () => {
    setMessage(null);
    setTested(null);
    show(await api.post<DocusignAdmin>("/admin/docusign/test-setup"));
    setMessage("DocuSign de test configuré : aucune valeur légale.");
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <FileSignature size={22} aria-hidden="true" /> DocuSign
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            Permet de faire signer avec une signature eIDAS : le signataire reçoit un e-mail de DocuSign et
            signe chez DocuSign. Le choix se fait pour chaque demande, dans « Faire signer ».
          </p>
        </div>
      </div>

      {config.mock && (
        <p className="card card--note" data-testid="docusign-mock-note">
          Vous utilisez le <strong>DocuSign de test</strong> de cette installation : les signatures n&apos;ont
          aucune valeur légale. Les e-mails de DocuSign sont remplacés par sa boîte de réception de test.
        </p>
      )}

      <form className="card form" onSubmit={save} autoComplete="off">
        <div className="card-title">
          <Plug size={14} aria-hidden="true" /> Connexion {config.configured ? "(configurée)" : "(non configurée)"}
        </div>
        <details className="connector-guide" open={!config.configured}>
          <summary>Comment préparer DocuSign, pas à pas</summary>
          <ol>
            {config.guide.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </details>
        {config.mock ? (
          <p className="muted small">
            Réglages du DocuSign de test (inutile de les modifier). Pour utiliser un vrai compte DocuSign,
            saisissez ses identifiants ci-dessous.
          </p>
        ) : null}
        {config.fields.map((f) => (
          <div key={f.name} className="field">
            <span className="label-line">
              <label htmlFor={`docusign-${f.name}`}>{f.label}</label>
              <HelpHint title={f.label} example={f.example || undefined}>
                {f.help}
              </HelpHint>
            </span>
            <ConnectorFieldControl
              id={`docusign-${f.name}`}
              field={f}
              value={values[f.name] ?? (f.kind === "select" ? f.default : "")}
              onChange={(value) => setValues({ ...values, [f.name]: value })}
            />
          </div>
        ))}
        <div className="field">
          <span className="label-line">
            <label htmlFor="docusign-private-key">{config.private_key.label}</label>
            <HelpHint title={config.private_key.label} example={config.private_key.example || undefined}>
              {config.private_key.help}
            </HelpHint>
          </span>
          <ConnectorFieldControl
            id="docusign-private-key"
            field={config.private_key}
            value={privateKey}
            onChange={setPrivateKey}
            secret
            stored={config.has_private_key}
          />
        </div>
        <div className="form-row">
          <button className="button button--primary" type="submit">
            Enregistrer
          </button>
          <button className="button" type="button" onClick={test} disabled={!config.configured}>
            Tester la connexion
          </button>
          {config.test_setup_available && (
            <button className="button" type="button" onClick={useMock}>
              <FlaskConical size={14} aria-hidden="true" /> Utiliser le DocuSign de test
            </button>
          )}
        </div>
        {message && <p role="status">{message}</p>}
        {tested && (
          <p role="status" className={tested.ok ? "" : "error-text"} data-testid="docusign-test-result">
            {tested.message}
          </p>
        )}
      </form>
    </div>
  );
}
