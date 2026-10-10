import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, PenLine } from "lucide-react";
import { api } from "../api/client";
import i18n from "../i18n";
import { errorText } from "../i18n/errors";
import type { PublicConfig, SignAllInput, SignAllPlan } from "../api/types";

const defaultLabel = (input: SignAllInput) =>
  input.label || (input.kind === "PLACE" ? i18n.t("signAll.defaultPlace") : i18n.t("signAll.defaultText"));

/** Sign every document of a campaign in one go: one consent, an answer that several documents
 *  share typed once, one signature (with its own proof) per document. */
export default function SignAllPage() {
  const { t } = useTranslation();
  const { campaignId } = useParams<{ campaignId: string }>();
  const [plan, setPlan] = useState<SignAllPlan | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shared, setShared] = useState<Record<string, string>>({});
  const [single, setSingle] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [signed, setSigned] = useState<number | null>(null);

  useEffect(() => {
    api
      .get<SignAllPlan>(`/sign-all/${campaignId}`)
      .then(setPlan)
      .catch((err) => setError(errorText(err, "signAll.notFound")));
    api.get<PublicConfig>("/config").then(setConfig);
  }, [campaignId]);

  // An answer asked on several documents is asked once; the others stay per document.
  const groups = useMemo(() => {
    const byKey = new Map<string, { key: string; label: string; required: boolean; titles: string[] }>();
    const singles: { id: string; label: string; required: boolean; title: string }[] = [];
    for (const doc of plan?.documents ?? []) {
      for (const input of doc.inputs) {
        if (input.group_key) {
          const group = byKey.get(input.group_key) ?? {
            key: input.group_key,
            label: defaultLabel(input),
            required: false,
            titles: [],
          };
          group.required ||= input.required;
          if (!group.titles.includes(doc.title)) group.titles.push(doc.title);
          byKey.set(input.group_key, group);
        } else {
          singles.push({ id: input.id, label: defaultLabel(input), required: input.required, title: doc.title });
        }
      }
    }
    return { shared: [...byKey.values()], singles };
  }, [plan, i18n.language]);

  if (error && !plan) return <p className="error-text">{error}</p>;
  if (!plan) return <p className="muted">{t("common.loading")}</p>;

  const missing =
    groups.shared.some((g) => g.required && !(shared[g.key] ?? "").trim()) ||
    groups.singles.some((s) => s.required && !(single[s.id] ?? "").trim());

  const signAll = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await api.post<{ signed: number }>(`/sign-all/${campaignId}`, {
        consent: true,
        shared,
        values: single,
      });
      setSigned(done.signed);
    } catch (err) {
      setError(errorText(err, "signAll.failed"));
    } finally {
      setBusy(false);
    }
  };

  if (signed !== null) {
    return (
      <div className="stack">
        <div className="card" data-testid="sign-all-done">
          <div className="card-title">
            <CheckCircle2 size={16} aria-hidden="true" /> {t("signAll.signedCount", { count: signed })}
          </div>
          <p>{t("signAll.ownProof")}</p>
          <div className="row-actions">
            <Link className="button button--primary" to="/">
              {t("nav.mySignatures")}
            </Link>
            <Link className="button button--ghost" to="/">
              {t("common.back")}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="stack">
      <Link to="/" className="back-link">
        <ArrowLeft size={14} aria-hidden="true" /> {t("signAll.toSign")}
      </Link>
      <h1 className="page-title">
        <PenLine size={20} aria-hidden="true" /> {t("signAll.title", { name: plan.campaign.name })}
      </h1>

      {plan.documents.length === 0 ? (
        <p className="muted">{t("signAll.nothing")}</p>
      ) : (
        <>
          <div className="card" data-testid="sign-all-documents">
            <div className="card-title">{t("signAll.documentsToSign", { count: plan.documents.length })}</div>
            <ul className="plain-list">
              {plan.documents.map((d) => (
                <li key={d.version_id}>
                  {d.title} <span className="muted small">v{d.version_label}</span>
                </li>
              ))}
            </ul>
            {plan.waiting > 0 && (
              <p className="muted small">
                {t("signAll.othersWaiting", { count: plan.waiting })}
              </p>
            )}
          </div>

          {(groups.shared.length > 0 || groups.singles.length > 0) && (
            <div className="card form" data-testid="sign-all-inputs">
              <div className="card-title">{t("signAll.toFill")}</div>
              {groups.shared.map((g) => (
                <label key={g.key}>
                  {g.label}
                  {g.required && " *"}{" "}
                  <span className="muted small">
                    {t("signAll.oneAnswer", {
                      where: g.titles.length > 1 ? t("signAll.documentsN", { count: g.titles.length }) : g.titles[0],
                    })}
                  </span>
                  <input
                    value={shared[g.key] ?? ""}
                    onChange={(e) => setShared({ ...shared, [g.key]: e.target.value })}
                  />
                </label>
              ))}
              {groups.singles.map((s) => (
                <label key={s.id}>
                  {s.label}
                  {s.required && " *"} <span className="muted small">({s.title})</span>
                  <input
                    value={single[s.id] ?? ""}
                    onChange={(e) => setSingle({ ...single, [s.id]: e.target.value })}
                  />
                </label>
              ))}
            </div>
          )}

          <div className="card">
            <label className="consent-row">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>{config?.consent_text ?? t("signAll.consentDefault")}</span>
            </label>
            {error && <p className="error-text" role="alert">{error}</p>}
            <button
              className="button button--primary"
              onClick={() => void signAll()}
              disabled={!consent || busy || missing}
            >
              {busy ? t("signing.inProgress") : t("signAll.signAllButton", { count: plan.documents.length })}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
