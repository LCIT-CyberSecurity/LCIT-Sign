import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Activity, CheckCircle2, AlertTriangle, XCircle, MinusCircle, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import i18n from "../i18n";
import { diagnosticText } from "../i18n/errors";
import { formatDateTime } from "../i18n/format";
import type { DiagnosticCheck, DiagnosticsReport } from "../api/types";

const KNOWN_COMPONENTS = ["application", "database", "filesystem", "signing_key", "oidc", "directory", "smtp", "worker", "builtin_admin"];
const componentLabel = (name: string) =>
  KNOWN_COMPONENTS.includes(name) ? i18n.t(`diagnostics.component.${name}`) : name;

function StatusIcon({ status }: { status: DiagnosticCheck["status"] }) {
  const common = { size: 16, "aria-hidden": true } as const;
  if (status === "OK") return <CheckCircle2 {...common} className="status-ok" />;
  if (status === "WARN") return <AlertTriangle {...common} className="status-warn" />;
  if (status === "ERROR") return <XCircle {...common} className="status-error" />;
  return <MinusCircle {...common} className="muted" />;
}

export default function AdminDiagnosticsPage() {
  const { t } = useTranslation();
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
        <Activity size={20} aria-hidden="true" /> {t("diagnostics.title")}
      </h1>
      <div className="card">
        <button className="button button--secondary" onClick={load} disabled={loading}>
          <RefreshCw size={14} aria-hidden="true" /> {loading ? t("diagnostics.checking") : t("diagnostics.recheck")}
        </button>
        {report && (
          <p className="muted small">
            {t("diagnostics.lastCheck", { date: formatDateTime(report.checked_at) })}
          </p>
        )}
        <table className="simple-table">
          <tbody>
            {report?.checks.map((check) => (
              <tr key={check.name}>
                <td>
                  <StatusIcon status={check.status} />{" "}
                  <span data-testid={`check-${check.name}`}>{componentLabel(check.name)}</span>
                </td>
                <td>{check.status}</td>
                <td className="muted">{diagnosticText(check.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
