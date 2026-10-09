import { useEffect, useState } from "react";
import { Activity, CheckCircle2, AlertTriangle, XCircle, MinusCircle, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { DiagnosticCheck, DiagnosticsReport } from "../api/types";

const LABELS: Record<string, string> = {
  application: "Application",
  database: "PostgreSQL",
  filesystem: "Système de fichiers",
  signing_key: "Clé de signature",
  oidc: "SSO (OIDC)",
  directory: "Annuaire",
  smtp: "E-mail",
  worker: "Tâches de fond",
};

function StatusIcon({ status }: { status: DiagnosticCheck["status"] }) {
  const common = { size: 16, "aria-hidden": true } as const;
  if (status === "OK") return <CheckCircle2 {...common} className="status-ok" />;
  if (status === "WARN") return <AlertTriangle {...common} className="status-warn" />;
  if (status === "ERROR") return <XCircle {...common} className="status-error" />;
  return <MinusCircle {...common} className="muted" />;
}

export default function AdminDiagnosticsPage() {
  const [report, setReport] = useState<DiagnosticsReport | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setReport(await api.get<DiagnosticsReport>("/admin/diagnostics"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="stack">
      <h1 className="page-title">
        <Activity size={20} aria-hidden="true" /> Diagnostic
      </h1>
      <div className="card">
        <button className="button button--secondary" onClick={load} disabled={loading}>
          <RefreshCw size={14} aria-hidden="true" /> {loading ? "Vérification…" : "Revérifier"}
        </button>
        {report && (
          <p className="muted small">
            Dernière vérification : {new Date(report.checked_at).toLocaleString("fr-FR")}
          </p>
        )}
        <table className="simple-table">
          <tbody>
            {report?.checks.map((check) => (
              <tr key={check.name}>
                <td>
                  <StatusIcon status={check.status} />{" "}
                  <span data-testid={`check-${check.name}`}>{LABELS[check.name] ?? check.name}</span>
                </td>
                <td>{check.status}</td>
                <td className="muted">{check.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
