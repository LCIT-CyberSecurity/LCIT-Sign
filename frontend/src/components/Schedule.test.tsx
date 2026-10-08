import { describe, expect, it } from "vitest";
import {
  DEFAULT_DEADLINE_DAYS,
  EMPTY_SCHEDULE,
  addDays,
  defaultSchedule,
  describePolicies,
  describeSchedule,
  scheduleBody,
  scheduleFromPlan,
  scheduleProblem,
} from "./Schedule";

const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

describe("schedule", () => {
  it("sends nothing special when nothing is set", () => {
    expect(scheduleBody(EMPTY_SCHEDULE)).toEqual({
      reminder_first_days: null,
      reminder_interval_days: null,
      reminder_max_count: null,
      reminder_before_deadline_days: null,
      renewal_every: null,
      renewal_unit: null,
      start_at: null,
      deadline: null,
    });
  });

  it("turns everyday choices into the API's settings", () => {
    const body = scheduleBody({ startDate: day(5), deadline: day(30), reminderDays: "7", renewalMonths: "12" });
    // Reminded every week after the request reached them, until they sign: no cap.
    expect(body).toMatchObject({
      reminder_first_days: 7,
      reminder_interval_days: 7,
      reminder_max_count: null,
      renewal_every: 12,
      renewal_unit: "MONTHS",
    });
    expect(body.start_at).not.toBeNull();
    expect(body.deadline).not.toBeNull();
  });

  it("treats a start date of today (or earlier) as 'now'", () => {
    expect(scheduleBody({ ...EMPTY_SCHEDULE, startDate: day(0) }).start_at).toBeNull();
    expect(scheduleBody({ ...EMPTY_SCHEDULE, startDate: day(-3) }).start_at).toBeNull();
  });

  it("refuses an impossible calendar before sending", () => {
    expect(scheduleProblem({ ...EMPTY_SCHEDULE, deadline: day(-1) })).toMatch(/déjà passée/);
    expect(scheduleProblem({ ...EMPTY_SCHEDULE, startDate: day(10), deadline: day(5) })).toMatch(/après la date/);
    expect(scheduleProblem({ ...EMPTY_SCHEDULE, startDate: day(5), deadline: day(10) })).toBeNull();
    expect(scheduleProblem(EMPTY_SCHEDULE)).toBeNull();
  });

  it("describes the settings for the review screen", () => {
    expect(describeSchedule(EMPTY_SCHEDULE)).toEqual([
      "Début dès l'envoi",
      "Sans échéance",
      "Pas de relance automatique",
      "Pas de renouvellement",
    ]);
    const lines = describeSchedule({ startDate: day(5), deadline: day(30), reminderDays: "7", renewalMonths: "3" });
    expect(lines[0]).toMatch(/^Début le /);
    expect(lines).toContain("Relance en cas de non-réponse : toutes les semaines");
    expect(lines).toContain("Renouvellement : tous les 3 mois");
  });

  it("still describes the policies of a campaign already sent", () => {
    expect(
      describePolicies({
        reminder_first_days: 7,
        reminder_interval_days: 7,
        reminder_max_count: null,
        reminder_before_deadline_days: null,
        renewal_every: 12,
        renewal_unit: "MONTHS",
      }),
    ).toEqual(["Relance à J+7, puis tous les 7 jours.", "Renouvellement tous les 12 mois."]);
  });

  it("starts a new request from today, due in 30 days, with no reminder and no renewal", () => {
    const fresh = defaultSchedule();
    expect(fresh.startDate).toBe(day(0));
    expect(fresh.deadline).toBe(day(DEFAULT_DEADLINE_DAYS));
    expect(fresh.reminderDays).toBe("");
    expect(fresh.renewalMonths).toBe("");
    // Starting today is "as soon as it is sent": nothing is scheduled, nothing is refused.
    const body = scheduleBody(fresh);
    expect(body.start_at).toBeNull();
    expect(body.deadline).not.toBeNull();
    expect(body.reminder_first_days).toBeNull();
    expect(body.renewal_every).toBeNull();
    expect(scheduleProblem(fresh)).toBeNull();
    expect(describeSchedule(fresh)).toEqual([
      "Début dès l'envoi",
      expect.stringMatching(/^Échéance le /),
      "Pas de relance automatique",
      "Pas de renouvellement",
    ]);
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-01-15", 30)).toBe("2026-02-14");
    expect(addDays("2026-12-20", 30)).toBe("2027-01-19");
  });

  it("puts a saved plan back: no start saved is today, no deadline saved stays none", () => {
    const back = scheduleFromPlan({ deadline: null, reminder_first_days: 7, reminder_interval_days: 7 });
    expect(back.startDate).toBe(day(0));
    expect(back.deadline).toBe("");
    expect(back.reminderDays).toBe("7");
  });
});
