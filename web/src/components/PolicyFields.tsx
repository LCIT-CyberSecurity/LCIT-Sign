import type { CampaignPolicies } from "../api/types";

export interface PolicyForm {
  reminderFirstDays: string;
  reminderIntervalDays: string;
  reminderMaxCount: string;
  reminderBeforeDeadlineDays: string;
  renewalEvery: string;
  renewalUnit: "DAYS" | "MONTHS";
}

export const EMPTY_POLICY: PolicyForm = {
  reminderFirstDays: "",
  reminderIntervalDays: "",
  reminderMaxCount: "",
  reminderBeforeDeadlineDays: "",
  renewalEvery: "",
  renewalUnit: "MONTHS",
};

const num = (value: string): number | null => (value.trim() === "" ? null : Number(value));

/** The body fields the API expects (spec §50-51); empty inputs mean "no such rule". */
export function buildPolicyPayload(form: PolicyForm): CampaignPolicies {
  const renewalEvery = num(form.renewalEvery);
  return {
    reminder_first_days: num(form.reminderFirstDays),
    reminder_interval_days: num(form.reminderIntervalDays),
    reminder_max_count: num(form.reminderMaxCount),
    reminder_before_deadline_days: num(form.reminderBeforeDeadlineDays),
    renewal_every: renewalEvery,
    renewal_unit: renewalEvery === null ? null : form.renewalUnit,
  };
}

/** Client-side hint mirroring the API's coherence rules; the API still decides. */
export function policyProblem(form: PolicyForm): string | null {
  if (form.reminderFirstDays.trim() !== "" && form.reminderIntervalDays.trim() === "") {
    return "Indiquez la périodicité des relances.";
  }
  return null;
}

export function describePolicies(p: CampaignPolicies): string[] {
  const lines: string[] = [];
  if (p.reminder_first_days !== null) {
    const max = p.reminder_max_count !== null ? `, ${p.reminder_max_count} fois au maximum` : "";
    lines.push(
      `Relance à J+${p.reminder_first_days}, puis tous les ${p.reminder_interval_days} jours${max}.`,
    );
  }
  if (p.reminder_before_deadline_days !== null) {
    lines.push(`Relance ${p.reminder_before_deadline_days} jour(s) avant l'échéance.`);
  }
  if (p.renewal_every !== null) {
    const unit = p.renewal_unit === "DAYS" ? "jour(s)" : "mois";
    lines.push(`Renouvellement tous les ${p.renewal_every} ${unit}.`);
  }
  return lines;
}

export default function PolicyFields({
  value,
  onChange,
}: {
  value: PolicyForm;
  onChange: (next: PolicyForm) => void;
}) {
  const set = (patch: Partial<PolicyForm>) => onChange({ ...value, ...patch });
  return (
    <fieldset className="form">
      <legend className="field-label">Relances automatiques</legend>
      <div className="form-row">
        <label>
          Première relance après (jours)
          <input
            type="number"
            min={0}
            value={value.reminderFirstDays}
            onChange={(e) => set({ reminderFirstDays: e.target.value })}
          />
        </label>
        <label>
          Puis tous les (jours)
          <input
            type="number"
            min={1}
            value={value.reminderIntervalDays}
            onChange={(e) => set({ reminderIntervalDays: e.target.value })}
          />
        </label>
        <label>
          Maximum de relances
          <input
            type="number"
            min={0}
            value={value.reminderMaxCount}
            onChange={(e) => set({ reminderMaxCount: e.target.value })}
          />
        </label>
        <label>
          Relance avant échéance (jours)
          <input
            type="number"
            min={0}
            value={value.reminderBeforeDeadlineDays}
            onChange={(e) => set({ reminderBeforeDeadlineDays: e.target.value })}
          />
        </label>
      </div>
      <legend className="field-label">Renouvellement</legend>
      <div className="form-row">
        <label>
          Renouveler tous les
          <input
            type="number"
            min={1}
            value={value.renewalEvery}
            onChange={(e) => set({ renewalEvery: e.target.value })}
          />
        </label>
        <label>
          Unité
          <select
            value={value.renewalUnit}
            onChange={(e) => set({ renewalUnit: e.target.value as "DAYS" | "MONTHS" })}
          >
            <option value="DAYS">jours</option>
            <option value="MONTHS">mois</option>
          </select>
        </label>
      </div>
    </fieldset>
  );
}
