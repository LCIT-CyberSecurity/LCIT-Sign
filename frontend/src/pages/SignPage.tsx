import { useEffect, useState, type FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { PenLine, Plus } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import ConfirmButton from "../components/ConfirmButton";
import type { Campaign } from "../api/types";

/** Where a request for signature starts: choose who signs, what, for whom — then send.
 *  Requests still being prepared are listed to be picked up again; once sent, they are
 *  followed in Campagnes. */
export default function SignPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    api.get<Campaign[]>("/campaigns").then(setCampaigns);
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const created = await api.post<Campaign>("/campaigns", { name: name.trim() });
      navigate(`/sign/${created.id}`);
    } finally {
      setCreating(false);
    }
  };

  const remove = async (id: string) => {
    setProblem(null);
    try {
      await api.del(`/campaigns/${id}`);
      setCampaigns((all) => (all ?? []).filter((c) => c.id !== id));
    } catch (err) {
      setProblem(errorText(err, "signPage.deleteFailed"));
    }
  };

  const drafts = (campaigns ?? [])
    .filter((c) => c.status === "DRAFT")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>
            <PenLine size={22} aria-hidden="true" /> {t("nav.sign")}
          </h1>
          <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
            {t("signPage.subtitle")}
          </p>
        </div>
      </div>

      <form className="card form" onSubmit={create} aria-label={t("signPage.newRequest")}>
        <div className="card-title">{t("signPage.newRequest")}</div>
        <div className="inline-create">
          <input
            placeholder={t("signPage.namePlaceholder")}
            aria-label={t("signPage.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <button className="button button--primary" type="submit" disabled={creating}>
            <Plus size={14} aria-hidden="true" /> {t("signPage.start")}
          </button>
        </div>
      </form>

      <section>
        <h2 className="card-title">{t("signPage.inPreparation")}</h2>
        {drafts.length === 0 ? (
          <p className="muted">{t("signPage.noDrafts")}</p>
        ) : (
          <div className="card-list">
            {drafts.map((c) => (
              <div key={c.id} className="draft-row" data-testid={`draft-${c.id}`}>
                <Link to={`/sign/${c.id}`} className="card card--link">
                  <div>
                    <div className="card-title">{c.name}</div>
                    <div className="muted small">
                      {t("signPage.draftSummary", { count: c.documents.length, documents: c.documents.length, signers: c.roles.length })}
                    </div>
                  </div>
                  <div className="card-meta">{t("signPage.resume")}</div>
                </Link>
                <ConfirmButton
                  confirmLabel={t("signPage.confirmDelete")}
                  onConfirm={() => remove(c.id)}
                >
                  {t("common.delete")}
                </ConfirmButton>
              </div>
            ))}
          </div>
        )}
        {problem && <p className="error-text">{problem}</p>}
        <p className="muted small">
          <Trans i18nKey="signPage.followedIn" components={{ view: <Link to="/campaigns" /> }} />
        </p>
      </section>
    </div>
  );
}
