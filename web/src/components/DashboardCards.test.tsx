import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardCards from "./DashboardCards";
import type { OperatorDashboard } from "../api/types";

const data: OperatorDashboard = {
  campaigns: { active: 2, closed: 5, draft: 1 },
  assignments: { expected: 142, signed: 115, outstanding: 27, not_viewed: 9, overdue: 4 },
  signature_rate: 81,
  reminders_sent: 33,
};

describe("<DashboardCards />", () => {
  it("shows the overview figures and the completion rate", () => {
    render(<DashboardCards data={data} />);
    expect(screen.getByTestId("stat-Signatures attendues")).toHaveTextContent("142");
    expect(screen.getByTestId("stat-Signatures réalisées")).toHaveTextContent("115");
    expect(screen.getByTestId("stat-En retard")).toHaveTextContent("4");
    expect(screen.getByTestId("stat-Relances envoyées")).toHaveTextContent("33");
    expect(screen.getByTestId("signature-rate")).toHaveTextContent("81 %");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "81");
  });

  it("does not invent a rate when nothing is expected", () => {
    render(
      <DashboardCards
        data={{ ...data, signature_rate: null, assignments: { ...data.assignments, expected: 0 } }}
      />,
    );
    expect(screen.getByTestId("signature-rate")).toHaveTextContent("—");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});
