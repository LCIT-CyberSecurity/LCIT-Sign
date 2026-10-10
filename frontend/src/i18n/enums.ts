import i18n from "./index";

/** What is displayed for a stable API value (PENDING, ACTIVE…). The value itself is never
 *  changed; a value this build has no word for is shown as the API sent it. */
export function enumLabel(group: string, value: string): string {
  const key = `${group}.${value}`;
  return i18n.exists(key) ? i18n.t(key) : value;
}

export const assignmentStatus = (value: string) => enumLabel("status", value);
export const campaignStatus = (value: string) => enumLabel("campaign.status", value);
export const syncRunStatus = (value: string) => enumLabel("directory.runStatus", value);
export const versionStatus = (value: string) => enumLabel("version.status", value);
