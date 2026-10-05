import { AlertTriangle, CheckCircle2, Clock, FileSignature, Megaphone } from "lucide-react";
import type { ReactNode } from "react";
import type { OperatorDashboard } from "../api/types";

function Metric({
  label,
  value,
  icon,
  tone,
  hint,
}: {
  label: string;
  value: string | number;
  icon: ReactNode;
  tone?: "green" | "red" | "amber";
  hint?: string;
}) {
  return (
    <div className={`metric${tone === "red" && Number(value) > 0 ? " metric-alert" : ""}`}>
      <div className="metric-label">
        {label}
        <span className={`metric-icon${tone ? ` ${tone}` : ""}`} aria-hidden="true">
          {icon}
        </span>
      </div>
      <strong data-testid={`stat-${label}`}>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

/** Overview figures for operators (spec §65), in EARE's metric-tile style, with
 *  a stacked bar splitting the expected signatures. */
export default function DashboardCards({ data }: { data: OperatorDashboard }) {
  const { expected, signed, outstanding, not_viewed, overdue } = data.assignments;
  const rate = data.signature_rate;
  const late = Math.min(overdue, outstanding);
  const waiting = Math.max(outstanding - late, 0);
  const pct = (n: number) => (expected ? `${(100 * n) / expected}%` : "0%");

  return (
    <section aria-label="Tableau de bord" className="stack">
      <div className="metrics">
        <Metric
          label="Campagnes actives"
          value={data.campaigns.active}
          icon={<Megaphone size={15} />}
          hint={`${data.campaigns.closed} terminée(s)`}
        />
        <Metric
          label="Signatures attendues"
          value={expected}
          icon={<FileSignature size={15} />}
          hint={`${not_viewed} non consultée(s)`}
        />
        <Metric
          label="Signatures réalisées"
          value={signed}
          icon={<CheckCircle2 size={15} />}
          tone="green"
          hint={rate === null ? undefined : `${rate} % des attendues`}
        />
        <Metric
          label="En retard"
          value={overdue}
          icon={<AlertTriangle size={15} />}
          tone="red"
          hint={`${data.reminders_sent} relance(s) envoyée(s)`}
        />
      </div>
      <div className="panel panel--quiet">
        <div className="panel-title">
          <h3>Taux de signature</h3>
          <strong data-testid="signature-rate">{rate === null ? "—" : `${rate} %`}</strong>
        </div>
        <div
          className="stacked-track"
          role="progressbar"
          aria-label="Répartition des signatures attendues"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={rate ?? 0}
        >
          <span className="stacked-part ok" style={{ width: pct(signed) }} />
          <span className="stacked-part warn" style={{ width: pct(waiting) }} />
          <span className="stacked-part bad" style={{ width: pct(late) }} />
        </div>
        <div className="stacked-legend" style={{ marginTop: 10 }}>
          <span>
            <i className="stacked-dot ok" /> Signées <strong>{signed}</strong>
          </span>
          <span>
            <i className="stacked-dot warn" /> En attente <strong data-testid="stat-En attente">{waiting}</strong>
          </span>
          <span>
            <i className="stacked-dot bad" /> En retard <strong>{late}</strong>
          </span>
          <span>
            <Clock size={13} aria-hidden="true" /> Non consultées <strong data-testid="stat-Non consultés">{not_viewed}</strong>
          </span>
        </div>
      </div>
    </section>
  );
}
