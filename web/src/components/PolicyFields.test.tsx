import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PolicyFields, {
  EMPTY_POLICY,
  buildPolicyPayload,
  describePolicies,
  policyProblem,
  type PolicyForm,
} from "./PolicyFields";

describe("buildPolicyPayload", () => {
  it("sends nothing when no rule is set", () => {
    expect(buildPolicyPayload(EMPTY_POLICY)).toEqual({
      reminder_first_days: null,
      reminder_interval_days: null,
      reminder_max_count: null,
      reminder_before_deadline_days: null,
      renewal_every: null,
      renewal_unit: null,
    });
  });

  it("converts filled inputs to numbers and keeps the renewal unit only with a value", () => {
    const form: PolicyForm = {
      ...EMPTY_POLICY,
      reminderFirstDays: "7",
      reminderIntervalDays: "7",
      reminderMaxCount: "3",
      renewalEvery: "6",
      renewalUnit: "MONTHS",
    };
    expect(buildPolicyPayload(form)).toMatchObject({
      reminder_first_days: 7,
      reminder_interval_days: 7,
      reminder_max_count: 3,
      renewal_every: 6,
      renewal_unit: "MONTHS",
    });
  });
});

describe("policyProblem", () => {
  it("requires an interval with a first reminder", () => {
    expect(policyProblem({ ...EMPTY_POLICY, reminderFirstDays: "7" })).toMatch(/périodicité/);
    expect(
      policyProblem({ ...EMPTY_POLICY, reminderFirstDays: "7", reminderIntervalDays: "7" }),
    ).toBeNull();
    expect(policyProblem(EMPTY_POLICY)).toBeNull();
  });
});

describe("describePolicies", () => {
  it("writes the rules in French", () => {
    const lines = describePolicies({
      reminder_first_days: 7,
      reminder_interval_days: 7,
      reminder_max_count: 3,
      reminder_before_deadline_days: 2,
      renewal_every: 12,
      renewal_unit: "MONTHS",
    });
    expect(lines).toEqual([
      "Relance à J+7, puis tous les 7 jours, 3 fois au maximum.",
      "Relance 2 jour(s) avant l'échéance.",
      "Renouvellement tous les 12 mois.",
    ]);
  });

  it("is empty without policies", () => {
    expect(
      describePolicies({
        reminder_first_days: null,
        reminder_interval_days: null,
        reminder_max_count: null,
        reminder_before_deadline_days: null,
        renewal_every: null,
        renewal_unit: null,
      }),
    ).toEqual([]);
  });
});

describe("<PolicyFields />", () => {
  function Harness() {
    const [value, setValue] = useState<PolicyForm>(EMPTY_POLICY);
    return (
      <>
        <PolicyFields value={value} onChange={setValue} />
        <output data-testid="payload">{JSON.stringify(buildPolicyPayload(value))}</output>
      </>
    );
  }

  it("feeds the payload as the user types", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Première relance après (jours)"), "5");
    await user.type(screen.getByLabelText("Puis tous les (jours)"), "2");
    await user.selectOptions(screen.getByLabelText("Unité"), "DAYS");
    await user.type(screen.getByLabelText("Renouveler tous les"), "90");
    const payload = JSON.parse(screen.getByTestId("payload").textContent ?? "{}");
    expect(payload).toMatchObject({
      reminder_first_days: 5,
      reminder_interval_days: 2,
      renewal_every: 90,
      renewal_unit: "DAYS",
    });
  });
});
