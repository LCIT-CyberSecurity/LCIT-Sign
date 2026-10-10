import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, RotateCcw } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { formatDateTime } from "../i18n/format";
import { enumLabel } from "../i18n/enums";
import type { SigningKeyInfo } from "../api/types";

export default function AdminSigningKeysPage() {
  const { t } = useTranslation();
  const [keys, setKeys] = useState<SigningKeyInfo[] | null>(null);
  const [rotating, setRotating] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.get<SigningKeyInfo[]>("/admin/signing-keys").then(setKeys);
  };

  useEffect(load, []);

  const rotate = async () => {
    setRotating(true);
    try {
      await api.post("/admin/signing-keys/rotate");
      load();
    } finally {
      setRotating(false);
    }
  };

  const revoke = async (keyId: string) => {
    setError(null);
    try {
      await api.post(`/admin/signing-keys/${keyId}/revoke`);
      setConfirming(null);
      load();
    } catch (err) {
      setError(errorText(err, "keys.revokeFailed"));
    }
  };

  return (
    <div className="stack">
      <h1 className="page-title">
        <KeyRound size={20} aria-hidden="true" /> {t("keys.title")}
      </h1>

      <div className="card">
        <button className="button button--primary" onClick={rotate} disabled={rotating}>
          <RotateCcw size={14} aria-hidden="true" /> {rotating ? t("keys.rotating") : t("keys.rotate")}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}
      <p className="muted small">
        {t("keys.revokeHelp")}
      </p>
      <div className="card">
        <table className="simple-table">
          <thead>
            <tr>
              <th>{t("keys.columns.id")}</th>
              <th>{t("keys.columns.status")}</th>
              <th>{t("keys.columns.created")}</th>
              <th>{t("keys.columns.retired")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {keys?.map((k) => (
              <tr key={k.key_id}>
                <td className="mono small">{k.key_id}</td>
                <td>
                  <span className={`badge badge--${k.status.toLowerCase()}`}>{enumLabel("keys.status", k.status)}</span>
                </td>
                <td>{formatDateTime(k.created_at)}</td>
                <td>{k.retired_at ? formatDateTime(k.retired_at) : "—"}</td>
                <td>
                  {k.status !== "REVOKED" &&
                    (confirming === k.key_id ? (
                      <>
                        <button className="button button--secondary button--sm" onClick={() => revoke(k.key_id)}>
                          {t("keys.confirmRevoke")}
                        </button>{" "}
                        <button className="button button--ghost button--sm" onClick={() => setConfirming(null)}>
                          {t("common.cancel")}
                        </button>
                      </>
                    ) : (
                      <button className="button button--ghost button--sm" onClick={() => setConfirming(k.key_id)}>
                        {t("keys.revoke")}
                      </button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
