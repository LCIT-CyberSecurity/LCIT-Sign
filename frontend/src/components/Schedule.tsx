import type { CampaignPlan, CampaignPolicies } from "../api/types";

/** When a request starts and ends, how often to remind those who have not answered, and
 *  how often it is asked again — four settings, in everyday terms. */
export interface Schedule {
  startDate: string; // yyyy-mm-dd, empty = as soon as it is sent
  deadline: string; // yyyy-mm-dd, empty = no deadline
  reminderDays: string; // "" = never, else every N days until signed
  renewalMonths: string; // "" = never, else every N months
}

export const EMPTY_SCHEDULE: Schedule = { startDate: "", deadline: "", reminderDays: "", renewalMonths: "" };

export const REMINDER_CHOICES: [string, string][] = [
  ["", "Aucune relance"],
  ["1", "Tous les jours"],
  ["2", "Tous les 2 jours"],
  ["7", "Toutes les semaines"],
  ["14", "Toutes les 2 semaines"],
  ["30", "Tous les mois"],
];

export const RENEWAL_CHOICES: [string, string][] = [
  ["", "Jamais"],
  ["1", "Tous les mois"],
  ["3", "Tous les 3 mois"],
  ["6", "Tous les 6 mois"],
  ["12", "Tous les ans"],
];

const two = (n: number) => String(n).padStart(2, "0");
const dayOf = (date: Date) => `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`;
// The company's day is the person's local one, not UTC's (just after midnight it is already tomorrow).
const today = () => dayOf(new Date());

/** `day` (yyyy-mm-dd) moved by `n` days. */
export function addDays(day: string, n: number): string {
  const date = new Date(`${day}T12:00:00`);
  date.setDate(date.getDate() + n);
  return dayOf(date);
}

export const DEFAULT_DEADLINE_DAYS = 30;

/** What a new request starts with: from today, due in 30 days, no reminder, no renewal. */
export function defaultSchedule(): Schedule {
  return {
    startDate: today(),
    deadline: addDays(today(), DEFAULT_DEADLINE_DAYS),
    reminderDays: "",
    renewalMonths: "",
  };
}

/** The fields the API expects for the launch. A start date today or earlier means "now". */
export function scheduleBody(s: Schedule): CampaignPolicies & {
  start_at: string | null;
  deadline: string | null;
} {
  const days = s.reminderDays ? Number(s.reminderDays) : null;
  const months = s.renewalMonths ? Number(s.renewalMonths) : null;
  return {
    // Reminded every N days after the request reached them, until they sign.
    reminder_first_days: days,
    reminder_interval_days: days,
    reminder_max_count: null,
    reminder_before_deadline_days: null,
    renewal_every: months,
    renewal_unit: months === null ? null : "MONTHS",
    start_at: s.startDate && s.startDate > today() ? new Date(`${s.startDate}T08:00:00`).toISOString() : null,
    deadline: s.deadline ? new Date(`${s.deadline}T23:59:59`).toISOString() : null,
  };
}

const localDate = (iso: string) => dayOf(new Date(iso));

/** The form as it was when saved: the reverse of `scheduleBody`. No start date saved means "as
 *  soon as it is sent", which is today; no deadline saved means the person chose none. */
export function scheduleFromPlan(plan: CampaignPlan): Schedule {
  return {
    startDate: plan.start_at ? localDate(plan.start_at) : today(),
    deadline: plan.deadline ? localDate(plan.deadline) : "",
    reminderDays: plan.reminder_first_days ? String(plan.reminder_first_days) : "",
    renewalMonths:
      plan.renewal_every && plan.renewal_unit === "MONTHS" ? String(plan.renewal_every) : "",
  };
}

/** What would make the API refuse, said before sending. */
export function scheduleProblem(s: Schedule): string | null {
  if (s.deadline && s.deadline < today()) return "L'échéance est déjà passée.";
  if (s.startDate && s.deadline && s.deadline <= s.startDate) {
    return "L'échéance doit être après la date de début.";
  }
  return null;
}

const frDate = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("fr-FR");

/** The settings in a sentence each, for the review screen. */
export function describeSchedule(s: Schedule): string[] {
  const lines = [s.startDate && s.startDate > today() ? `Début le ${frDate(s.startDate)}` : "Début dès l'envoi"];
  lines.push(s.deadline ? `Échéance le ${frDate(s.deadline)}` : "Sans échéance");
  const reminder = REMINDER_CHOICES.find(([value]) => value === s.reminderDays);
  lines.push(
    s.reminderDays && reminder
      ? `Relance en cas de non-réponse : ${reminder[1].toLowerCase()}`
      : "Pas de relance automatique",
  );
  const renewal = RENEWAL_CHOICES.find(([value]) => value === s.renewalMonths);
  lines.push(s.renewalMonths && renewal ? `Renouvellement : ${renewal[1].toLowerCase()}` : "Pas de renouvellement");
  return lines;
}

/** The policies of a campaign already sent, as sentences (follow-up page). */
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

export default function ScheduleFields({
  value,
  onChange,
}: {
  value: Schedule;
  onChange: (next: Schedule) => void;
}) {
  const set = (patch: Partial<Schedule>) => onChange({ ...value, ...patch });
  // Starting after the deadline makes no sense: the deadline follows, keeping the same time to sign.
  const setStart = (startDate: string) =>
    onChange({
      ...value,
      startDate,
      deadline:
        startDate && value.deadline && value.deadline <= startDate
          ? addDays(startDate, DEFAULT_DEADLINE_DAYS)
          : value.deadline,
    });
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="form-row">
        <label>
          Date de début <span className="muted small">(aujourd&apos;hui : dès l&apos;envoi)</span>
          <input type="date" value={value.startDate} min={today()} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          Date d&apos;échéance <span className="muted small">(dernier jour pour signer, 30 jours par défaut)</span>
          <input
            type="date"
            value={value.deadline}
            min={value.startDate || today()}
            onChange={(e) => set({ deadline: e.target.value })}
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Relance en cas de non-réponse
          <select value={value.reminderDays} onChange={(e) => set({ reminderDays: e.target.value })}>
            {REMINDER_CHOICES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Renouvellement <span className="muted small">(redemander la signature)</span>
          <select value={value.renewalMonths} onChange={(e) => set({ renewalMonths: e.target.value })}>
            {RENEWAL_CHOICES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
