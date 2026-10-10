import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { DirectoryCheck, DirectoryTestResult } from "../api/types";

/** What each step of a connection test is called. A step this build does not know is shown under
 *  its own name. */
const STEP_LABELS: Record<string, string> = {
  authentication: "Authentification",
  service_access: "Accès au service",
  users_read: "Lecture des utilisateurs",
  groups_read: "Lecture des groupes",
  memberships_read: "Lecture des appartenances",
  service_account: "Clé du compte de service",
  assertion: "Signature de l'assertion",
  token_exchange: "Jeton d'accès",
  delegation: "Délégation à l'échelle du domaine",
  network: "Réseau",
  tls: "Connexion sécurisée (TLS)",
  bind: "Connexion au compte de liaison",
  base_dn: "Base de recherche",
  users_query: "Requête des utilisateurs",
  groups_query: "Requête des groupes",
  configuration: "Configuration enregistrée",
};

const SUMMARY: Record<DirectoryTestResult["status"], string> = {
  OK: "Connexion opérationnelle.",
  WARN: "Connexion opérationnelle, avec des réserves.",
  ERROR: "La connexion n'est pas pleinement opérationnelle.",
};

function Icon({ status }: { status: DirectoryCheck["status"] }) {
  if (status === "OK") return <CheckCircle2 size={15} className="status-ok" aria-label="Réussi" />;
  if (status === "WARN") return <AlertTriangle size={15} className="status-warn" aria-label="Réserve" />;
  return <XCircle size={15} className="status-error" aria-label="Échec" />;
}

/** The result of a read-only connection test: a line per step, and for what failed the
 *  provider's own code and what to do. Only what the server decided to say is shown. */
export default function ConnectionTestResult({ result }: { result: DirectoryTestResult }) {
  return (
    <div className="connection-test" data-testid="connection-test" role="status">
      <div className="card-title" style={{ marginBottom: 6 }}>
        Test de connexion
      </div>
      <ul className="plain-list">
        {result.checks.map((check) => (
          <li key={check.name} data-testid={`check-${check.name}`} data-status={check.status}>
            <Icon status={check.status} /> <strong>{STEP_LABELS[check.name] ?? check.name}</strong>
            {check.status !== "OK" && (
              <div className="muted small" style={{ marginLeft: 22 }}>
                <div>{check.message}</div>
                {check.provider_code && (
                  <div>
                    Code fournisseur : <code>{check.provider_code}</code>
                  </div>
                )}
                {check.action && <div>Action recommandée : {check.action}</div>}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className={result.status === "OK" ? "status-ok" : "error-text"} data-testid="connection-summary">
        {SUMMARY[result.status]}
      </p>
    </div>
  );
}
