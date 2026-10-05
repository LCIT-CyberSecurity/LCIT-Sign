import type { OperatorDashboard } from "../api/types";

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="card stat">
      <div className="muted small">{label}</div>
      <div className={`stat__value${tone ? ` ${tone}` : ""}`} data-testid={`stat-${label}`}>
        {value}
      </div>
    </div>
  );
}

/** Overview figures for operators (spec §65), with a completion bar. */
export default function DashboardCards({ data }: { data: OperatorDashboard }) {
  const rate = data.signature_rate;
  return (
    <section aria-label="Tableau de bord" className="stack">
      <div className="stat-grid">
        <Stat label="Campagnes actives" value={data.campaigns.active} />
        <Stat label="Campagnes terminées" value={data.campaigns.closed} />
        <Stat label="Signatures attendues" value={data.assignments.expected} />
        <Stat label="Signatures réalisées" value={data.assignments.signed} tone="status-ok" />
        <Stat label="En attente" value={data.assignments.outstanding} />
        <Stat label="Non consultés" value={data.assignments.not_viewed} />
        <Stat
          label="En retard"
          value={data.assignments.overdue}
          tone={data.assignments.overdue > 0 ? "status-error" : undefined}
        />
        <Stat label="Relances envoyées" value={data.reminders_sent} />
      </div>
      <div className="card">
        <div className="muted small">Taux de signature</div>
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={rate ?? 0}
          className="progress"
        >
          <div className="progress__bar" style={{ width: `${rate ?? 0}%` }} />
        </div>
        <div data-testid="signature-rate">{rate === null ? "—" : `${rate} %`}</div>
      </div>
    </section>
  );
}
