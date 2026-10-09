import { useEffect, useState } from "react";
import { ScrollText, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { AuditEvent } from "../api/types";

export default function AdminAuditPage() {
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
          <ScrollText size={20} aria-hidden="true" /> Audit
        </h1>
        {integrity && (
          <span className={`badge badge--${integrity.valid ? "signed" : "failed"}`}>
            <ShieldCheck size={12} aria-hidden="true" />{" "}
            {integrity.valid ? "Chaîne intègre" : "Chaîne corrompue"}
          </span>
        )}
      </div>

      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Action</th>
              <th>Acteur</th>
              <th>Cible</th>
              <th>Résultat</th>
            </tr>
          </thead>
          <tbody>
            {events?.map((e) => (
              <tr key={e.event_id}>
                <td>{new Date(e.timestamp_utc).toLocaleString("fr-FR")}</td>
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
