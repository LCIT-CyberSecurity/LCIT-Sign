import { useEffect, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Cloud, Database, FolderCog, Network, RefreshCw, Settings2 } from "lucide-react";
import { api } from "../api/client";
import i18n from "../i18n";
import { errorText } from "../i18n/errors";
import { connectorText } from "../i18n/connectors";
import { collator, formatDateTime } from "../i18n/format";
import { syncRunStatus } from "../i18n/enums";
import DirectoryConnectorForm from "./DirectoryConnectorForm";
import type { DirectoryGroup, DirectorySource, DirectorySyncRun } from "../api/types";

interface SourceInfo {
  source: string;
  title: string;
  description: string;
  icon: typeof Cloud;
  remote: boolean;
}

const ICONS: Record<string, typeof Cloud> = { entra: Cloud, google: Cloud, ldap: Network };
const localInfo = (): SourceInfo => ({
  source: "local",
  title: i18n.t("directory.local.title"),
  description: i18n.t("directory.local.description"),
  icon: Database,
  remote: false,
});

/** A card per connector, titled and described by the connector itself. */
function infoFor(source: DirectorySource): SourceInfo {
  if (!source.spec) return localInfo();
  return {
    source: source.source,
    title: connectorText(`dir.${source.source}`, "label", source.spec.label),
    description: connectorText(`dir.${source.source}`, "description", source.spec.description),
    icon: ICONS[source.source] ?? Cloud,
    remote: true,
  };
}

const SCHEDULES: { minutes: number | null; key: string }[] = [
  { minutes: null, key: "directory.schedule.manual" },
  { minutes: 15, key: "directory.schedule.every15" },
  { minutes: 60, key: "directory.schedule.hourly" },
  { minutes: 360, key: "directory.schedule.every6h" },
  { minutes: 1440, key: "directory.schedule.daily" },
];

export function scheduleLabel(minutes: number | null): string {
  const known = SCHEDULES.find((s) => s.minutes === minutes);
  return known ? i18n.t(known.key) : i18n.t("directory.schedule.everyMinutes", { minutes });
}

function lastRunText(run: DirectorySyncRun | undefined): string {
  if (!run) return i18n.t("directory.lastRun.never");
  const when = formatDateTime(run.started_at, { dateStyle: "short", timeStyle: "short" });
  if (run.status === "SUCCESS") {
    return i18n.t("directory.lastRun.summary", {
      when,
      added: run.users_added,
      updated: run.users_updated,
      deactivated: run.users_deactivated,
    });
  }
  // The run's status value is data from the API; only "FAILED" has a word of its own.
  return run.status === "FAILED"
    ? i18n.t("directory.lastRun.failed", { when })
    : i18n.t("directory.lastRun.other", { when, status: run.status });
}

function SourceCard({
  info,
  source,
  lastRun,
  onChanged,
}: {
  info: SourceInfo;
  source: DirectorySource;
  lastRun: DirectorySyncRun | undefined;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const Icon = info.icon;
  const ready = !info.remote || source.configured;
  const active = Boolean(source.active);

  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const run = await api.post<DirectorySyncRun>(`/admin/directory/sync?source=${info.source}`);
      if (run.status === "FAILED") setError(run.error ?? t("directory.syncFailed"));
      onChanged();
    } catch (err) {
      setError(errorText(err, "directory.syncFailed"));
    } finally {
      setSyncing(false);
    }
  };

  const activate = async () => {
    setError(null);
    try {
      await api.post(`/admin/directory/sources/${info.source}/activate`);
      onChanged();
    } catch (err) {
      setError(errorText(err, "directory.activateFailed"));
    }
  };

  const setSchedule = async (value: string) => {
    setError(null);
    try {
      await api.put(`/admin/directory/sources/${info.source}/config`, {
        fields: source.fields,
        sync_interval_minutes: value ? Number(value) : null,
      });
      onChanged();
    } catch (err) {
      setError(errorText(err, "directory.saveFailed"));
    }
  };

  return (
    <section className="card source-card" data-testid={`source-${info.source}`}>
      <div className="source-card__head">
        <span className="metric-icon" aria-hidden="true">
          <Icon size={16} />
        </span>
        <div>
          <div className="card-title" style={{ margin: 0 }}>
            {info.title}
          </div>
          <div className="muted small">{info.description}</div>
        </div>
        <span className={`badge ${ready ? "badge--signed" : "badge--draft"}`} data-testid="source-state">
          {active
            ? t("directory.state.active")
            : info.remote
              ? source.configured
                ? t("directory.state.configuredInactive")
                : t("directory.state.notConfigured")
              : t("directory.state.inactive")}
        </span>
      </div>

      <dl className="kv" style={{ marginTop: 12 }}>
        <dt>{t("directory.lastSync")}</dt>
        <dd>{lastRunText(lastRun)}</dd>
        <dt>{t("directory.schedule.title")}</dt>
        <dd>
          <select
            value={source.sync_interval_minutes ?? ""}
            disabled={!ready || !active}
            aria-label={t("directory.schedule.label", { title: info.title })}
            onChange={(e) => void setSchedule(e.target.value)}
          >
            {SCHEDULES.map((s) => (
              <option key={s.key} value={s.minutes ?? ""}>
                {t(s.key)}
              </option>
            ))}
          </select>
        </dd>
      </dl>

      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="button-row" style={{ marginTop: 14 }}>
        <button className="button button--primary button--sm" onClick={sync} disabled={!ready || !active || syncing}>
          <RefreshCw size={13} aria-hidden="true" /> {syncing ? t("directory.syncing") : t("directory.syncNow")}
        </button>
        {ready && !active && (
          <button className="button button--secondary button--sm" onClick={activate}>
            {t("directory.use")}
          </button>
        )}
        {info.remote && (
          <button className="button button--secondary button--sm" onClick={() => setOpen(!open)} aria-expanded={open}>
            <Settings2 size={13} aria-hidden="true" /> {source.configured ? t("directory.editConnection") : t("directory.configure")}
          </button>
        )}
      </div>
      {info.remote && open && (
        <div style={{ marginTop: 14 }}>
          <DirectoryConnectorForm
            source={source}
            onChanged={() => {
              onChanged();
            }}
          />
        </div>
      )}
    </section>
  );
}

export default function AdminDirectoryPage() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<DirectorySource[]>([]);
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null);
  const [runs, setRuns] = useState<DirectorySyncRun[] | null>(null);
  const [query, setQuery] = useState("");

  const load = () => {
    api.get<DirectorySource[]>("/admin/directory/sources").then(setSources);
    api.get<DirectoryGroup[]>("/admin/directory/groups").then(setGroups);
    api.get<DirectorySyncRun[]>("/admin/directory/sync-runs").then(setRuns);
  };

  useEffect(load, []);

  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (groups ?? [])
      .filter((g) => !q || `${g.name} ${g.source}`.toLowerCase().includes(q))
      .sort((a, b) => collator().compare(a.name, b.name));
  }, [groups, query, i18n.language]);

  return (
    <div className="stack">
      <div>
        <h2 className="page-title" style={{ fontSize: 18, marginBottom: 6 }}>
          <FolderCog size={18} aria-hidden="true" /> {t("directory.title")}
        </h2>
        <p className="page-subtitle">
          <Trans i18nKey="directory.intro" components={{ strong: <strong /> }} />
        </p>
      </div>

      {sources.length > 0 && !sources.some((s) => s.active) && (
        <p className="muted" data-testid="no-directory">
          {t("directory.none")}
        </p>
      )}

      <div className="source-grid">
        {[...sources]
          .sort((x, y) => Number(x.source === "local") - Number(y.source === "local"))
          .map((source) => {
            const info = infoFor(source);
            return (
              <SourceCard
                key={info.source}
                info={info}
                source={source}
                lastRun={runs?.find((r) => r.source === info.source)}
                onChanged={load}
              />
            );
          })}
      </div>

      <div className="section-panel">
        <div className="page-title-row" style={{ marginBottom: 12 }}>
          <h2 className="page-title" style={{ margin: 0, fontSize: 18 }}>
            {t("directory.groups")} <span className="count-badge">{groups?.length ?? 0}</span>
          </h2>
          <input
            type="search"
            placeholder={t("directory.searchGroupPlaceholder")}
            aria-label={t("directory.searchGroup")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="table-wrap">
          <table className="simple-table">
            <thead>
              <tr>
                <th>{t("directory.columns.name")}</th>
                <th>{t("directory.columns.source")}</th>
                <th>{t("directory.columns.members")}</th>
              </tr>
            </thead>
            <tbody>
              {visibleGroups.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    {groups ? t("directory.noGroups") : t("common.loading")}
                  </td>
                </tr>
              )}
              {visibleGroups.map((g) => (
                <tr key={g.id}>
                  <td>{g.name}</td>
                  <td>{g.source}</td>
                  <td>{g.member_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-panel">
        <h2 className="page-title" style={{ margin: "0 0 12px", fontSize: 18 }}>
          {t("directory.history")}
        </h2>
        <div className="table-wrap">
          <table className="simple-table">
            <thead>
              <tr>
                <th>{t("directory.columns.date")}</th>
                <th>{t("directory.columns.source")}</th>
                <th>{t("directory.columns.status")}</th>
                <th>{t("directory.columns.users")}</th>
                <th>{t("directory.columns.groups")}</th>
                <th>{t("directory.columns.memberships")}</th>
              </tr>
            </thead>
            <tbody>
              {runs?.map((r) => (
                <tr key={r.id}>
                  <td>{formatDateTime(r.started_at)}</td>
                  <td>{r.source}</td>
                  <td>
                    <span className={`badge badge--${r.status === "SUCCESS" ? "signed" : "failed"}`}>{syncRunStatus(r.status)}</span>
                  </td>
                  <td>
                    {r.users_added}/{r.users_updated}/{r.users_deactivated}
                  </td>
                  <td>
                    {r.groups_added}/{r.groups_updated}
                  </td>
                  <td>
                    {r.memberships_added}/{r.memberships_removed}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
