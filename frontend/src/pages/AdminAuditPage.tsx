import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ScrollText, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { formatDateTime } from "../i18n/format";
import type { AuditEvent } from "../api/types";

export default function AdminAuditPage() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [integrity, setIntegrity] = useState<{ valid: boolean } | null>(null);

  useEffect(() => {
    api.get<AuditEvent[]>("/admin/audit").then(setEvents);
    api.get<{ valid: boolean }>("/admin/audit/integrity").then(setIntegrity);
  }, []);

  return (
    <div className="stack">
      <div className="page-title-row">
        <h1 className="page-title">
          <ScrollText size={20} aria-hidden="true" /> {t("audit.title")}
        </h1>
        {integrity && (
          <span className={`badge badge--${integrity.valid ? "signed" : "failed"}`}>
            <ShieldCheck size={12} aria-hidden="true" />{" "}
            {integrity.valid ? t("audit.chainValid") : t("audit.chainBroken")}
          </span>
        )}
      </div>

      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>{t("audit.columns.date")}</th>
              <th>{t("audit.columns.action")}</th>
              <th>{t("audit.columns.actor")}</th>
              <th>{t("audit.columns.target")}</th>
              <th>{t("audit.columns.result")}</th>
            </tr>
          </thead>
          <tbody>
            {events?.map((e) => (
              <tr key={e.event_id}>
                <td>{formatDateTime(e.timestamp_utc)}</td>
                <td>{e.action}</td>
                <td>{e.actor_identity_snapshot?.display_name ?? "—"}</td>
                <td>
                  {e.target_type ? `${e.target_type} ${e.target_id ?? ""}` : "—"}
                </td>
                <td>
                  <span className={`badge badge--${e.result === "SUCCESS" ? "signed" : "failed"}`}>
                    {e.result}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
