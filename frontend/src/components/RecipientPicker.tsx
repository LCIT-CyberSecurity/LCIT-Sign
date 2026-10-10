import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { UserPlus } from "lucide-react";
import i18n from "../i18n";
import { collator } from "../i18n/format";
import ExternalPersonForm, { type ExternalPerson } from "./ExternalPersonForm";
import type { DirectoryGroup } from "../api/types";

export interface Recipients {
  allUsers: boolean;
  groupIds: string[];
  userIds: string[];
}

export const NO_RECIPIENTS: Recipients = { allUsers: false, groupIds: [], userIds: [] };

interface PickableUser {
  id: string;
  display_name: string;
  external?: boolean;
}

/** Choose people: everyone, directory groups (a team, a department…), and single users.
 *  Used to pick who is asked, before sending and when adding people afterwards. */
export default function RecipientPicker({
  value,
  onChange,
  groups,
  users,
  count,
  onAddExternal,
}: {
  value: Recipients;
  onChange: (next: Recipients) => void;
  groups: DirectoryGroup[] | null;
  users: PickableUser[] | null;
  count?: number | null;
  /** When given, a person from outside the company can be added from here; the page is told. */
  onAddExternal?: (person: ExternalPerson) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (groups ?? [])
      .filter((g) => g.active && (!q || g.name.toLowerCase().includes(q)))
      .sort((a, b) => b.member_count - a.member_count || collator().compare(a.name, b.name));
  }, [groups, query, i18n.language]);

  const toggle = (list: string[], id: string) =>
    list.includes(id) ? list.filter((v) => v !== id) : [...list, id];

  return (
    <div className="stack" style={{ gap: 10 }}>
      <label className="consent-row">
        <input
          type="checkbox"
          checked={value.allUsers}
          onChange={(e) => onChange({ ...value, allUsers: e.target.checked })}
        />
        <span>{t("recipients.all")}</span>
      </label>

      {!value.allUsers && (
        <>
          <div className="field-label">
            {t("recipients.groups")}
            {value.groupIds.length > 0 && (
              <span className="muted small"> {t("recipients.selected", { count: value.groupIds.length })}</span>
            )}
          </div>
          <input
            type="search"
            placeholder={t("recipients.searchPlaceholder")}
            aria-label={t("recipients.searchGroup")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {visibleGroups.length === 0 && <p className="muted small">{t("recipients.noGroup")}</p>}
          <div className="chip-list">
            {visibleGroups.map((g) => (
              <button
                key={g.id}
                type="button"
                className={`chip${value.groupIds.includes(g.id) ? " chip--active" : ""}`}
                onClick={() => onChange({ ...value, groupIds: toggle(value.groupIds, g.id) })}
              >
                {g.name} · {g.member_count}
                <span className="muted small"> {g.source}</span>
              </button>
            ))}
          </div>

          <div className="field-label">{t("recipients.extraUsers")}</div>
          <div className="chip-list">
            {users?.map((u) => (
              <button
                key={u.id}
                type="button"
                className={`chip${value.userIds.includes(u.id) ? " chip--active" : ""}`}
                onClick={() => onChange({ ...value, userIds: toggle(value.userIds, u.id) })}
              >
                {u.display_name}
                {u.external ? <span className="muted small"> {t("recipients.external")}</span> : null}
              </button>
            ))}
          </div>
          {onAddExternal && (
            <>
              <button
                type="button"
                className="button button--ghost button--sm"
                onClick={() => setAdding(!adding)}
              >
                <UserPlus size={13} aria-hidden="true" /> {t("recipients.addExternal")}
              </button>
              {adding && (
                <ExternalPersonForm
                  onCancel={() => setAdding(false)}
                  onCreated={(person) => {
                    onAddExternal(person);
                    onChange({ ...value, userIds: [...new Set([...value.userIds, person.id])] });
                    setAdding(false);
                  }}
                />
              )}
            </>
          )}
        </>
      )}

      {count !== undefined && (
        <p className="muted" data-testid="recipient-count">
          {count === null ? "" : t("recipients.count", { count })}
        </p>
      )}
    </div>
  );
}
