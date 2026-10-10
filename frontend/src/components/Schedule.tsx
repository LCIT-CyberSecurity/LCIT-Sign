import { useTranslation } from "react-i18next";
import i18n from "../i18n";
import { formatDate } from "../i18n/format";
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

// [value sent, catalogue key of the label]: the label is worded in the active language when drawn.
export const REMINDER_CHOICES: [string, string][] = [
  ["", "schedule.reminder.none"],
  ["1", "schedule.reminder.1"],
  ["2", "schedule.reminder.2"],
  ["7", "schedule.reminder.7"],
  ["14", "schedule.reminder.14"],
  ["30", "schedule.reminder.30"],
];

export const RENEWAL_CHOICES: [string, string][] = [
  ["", "schedule.renewal.none"],
  ["1", "schedule.renewal.1"],
  ["3", "schedule.renewal.3"],
  ["6", "schedule.renewal.6"],
  ["12", "schedule.renewal.12"],
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
  if (s.deadline && s.deadline < today()) return i18n.t("schedule.deadlinePassed");
  if (s.startDate && s.deadline && s.deadline <= s.startDate) {
    return i18n.t("schedule.deadlineAfterStart");
  }
  return null;
}

const dayLabel = (value: string) => formatDate(`${value}T12:00:00`);

/** The settings in a sentence each, for the review screen. */
export function describeSchedule(s: Schedule): string[] {
  const lines = [
    s.startDate && s.startDate > today()
      ? i18n.t("schedule.startOn", { date: dayLabel(s.startDate) })
      : i18n.t("schedule.startOnSend"),
  ];
  lines.push(s.deadline ? i18n.t("schedule.deadlineOn", { date: dayLabel(s.deadline) }) : i18n.t("schedule.noDeadline"));
  const reminder = REMINDER_CHOICES.find(([value]) => value === s.reminderDays);
  lines.push(
    s.reminderDays && reminder
      ? i18n.t("schedule.reminderLine", { choice: i18n.t(reminder[1]).toLowerCase() })
      : i18n.t("schedule.noReminder"),
  );
  const renewal = RENEWAL_CHOICES.find(([value]) => value === s.renewalMonths);
  lines.push(
    s.renewalMonths && renewal
      ? i18n.t("schedule.renewalLine", { choice: i18n.t(renewal[1]).toLowerCase() })
      : i18n.t("schedule.noRenewal"),
  );
  return lines;
}

/** The policies of a campaign already sent, as sentences (follow-up page). */
export function describePolicies(p: CampaignPolicies): string[] {
  const lines: string[] = [];
  if (p.reminder_first_days !== null) {
    const max = p.reminder_max_count !== null ? i18n.t("schedule.policyMax", { count: p.reminder_max_count }) : "";
    lines.push(
      i18n.t("schedule.policyReminder", { first: p.reminder_first_days, interval: p.reminder_interval_days, max }),
    );
  }
  if (p.reminder_before_deadline_days !== null) {
    lines.push(i18n.t("schedule.policyBeforeDeadline", { count: p.reminder_before_deadline_days }));
  }
  if (p.renewal_every !== null) {
    lines.push(
      i18n.t(p.renewal_unit === "DAYS" ? "schedule.policyRenewalDays" : "schedule.policyRenewalMonths", {
        count: p.renewal_every,
      }),
    );
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
  const { t } = useTranslation();
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
          {t("schedule.startDate")} <span className="muted small">{t("schedule.startHint")}</span>
          <input type="date" value={value.startDate} min={today()} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          {t("schedule.deadlineDate")} <span className="muted small">{t("schedule.deadlineHint")}</span>
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
          {t("schedule.reminderLabel")}
          <select value={value.reminderDays} onChange={(e) => set({ reminderDays: e.target.value })}>
            {REMINDER_CHOICES.map(([v, key]) => (
              <option key={v} value={v}>
                {t(key)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("schedule.renewalLabel")} <span className="muted small">{t("schedule.renewalHint")}</span>
          <select value={value.renewalMonths} onChange={(e) => set({ renewalMonths: e.target.value })}>
            {RENEWAL_CHOICES.map(([v, key]) => (
              <option key={v} value={v}>
                {t(key)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
