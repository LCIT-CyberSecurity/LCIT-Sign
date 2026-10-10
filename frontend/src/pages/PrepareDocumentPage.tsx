import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { ArrowLeft, CheckCircle2, Lock, Save, Trash2, UserRound } from "lucide-react";
import { api } from "../api/client";
import { errorText } from "../i18n/errors";
import { versionStatus } from "../i18n/enums";
import PdfPages, { type PageSize } from "../prepare/PdfPages";
import { clampRect, moveRect, placeCentered, pointToFraction, resizeRect, tidy, type Rect } from "../prepare/geometry";
import { KIND_BY_ID, KINDS, kindHint, kindLabel, roleColor, type FieldKind } from "../prepare/kinds";
import type { Campaign } from "../api/types";

export interface EditorField extends Rect {
  id: string;
  page: number;
  kind: FieldKind;
  label: string;
  required: boolean;
  role: number;
  group_key: string | null;
}

interface FieldsResponse {
  editable: boolean;
  document_title: string;
  version_label: string;
  status: string;
  fields: EditorField[];
}

const DRAG_TYPE = "application/x-lcit-element";

type Gesture =
  | { id: string; mode: "move" | "resize"; startX: number; startY: number; origin: Rect; bounds: DOMRect }
  | null;

function FieldBox({
  field,
  selected,
  editable,
  onSelect,
  onChange,
  overlay,
}: {
  field: EditorField;
  selected: boolean;
  editable: boolean;
  onSelect: () => void;
  onChange: (rect: Rect) => void;
  overlay: HTMLDivElement | null;
}) {
  const gesture = useRef<Gesture>(null);
  const meta = KIND_BY_ID[field.kind];
  const Icon = meta.icon;
  const color = roleColor(field.role);

  const begin = (mode: "move" | "resize") => (e: PointerEvent<HTMLElement>) => {
    onSelect();
    if (!editable || !overlay) return;
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    gesture.current = {
      id: field.id,
      mode,
      startX: e.clientX,
      startY: e.clientY,
      origin: { x: field.x, y: field.y, width: field.width, height: field.height },
      bounds: overlay.getBoundingClientRect(),
    };
  };

  const track = (e: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g) return;
    const dx = (e.clientX - g.startX) / g.bounds.width;
    const dy = (e.clientY - g.startY) / g.bounds.height;
    onChange(g.mode === "move" ? moveRect(g.origin, dx, dy) : resizeRect(g.origin, dx, dy));
  };

  const end = (e: PointerEvent<HTMLElement>) => {
    if (gesture.current) e.currentTarget.releasePointerCapture(e.pointerId);
    gesture.current = null;
  };

  return (
    <div
      className={`prep-field${selected ? " prep-field--selected" : ""}${editable ? "" : " prep-field--locked"}`}
      style={{
        left: `${field.x * 100}%`,
        top: `${field.y * 100}%`,
        width: `${field.width * 100}%`,
        height: `${field.height * 100}%`,
        borderColor: color,
        background: `${color}1f`,
        color,
      }}
      data-testid={`field-${field.kind}`}
      data-role={field.role}
      onPointerDown={begin("move")}
      onPointerMove={track}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <span className="prep-field__tag" style={{ background: color }}>
        {field.role}
      </span>
      <Icon size={13} aria-hidden="true" />
      <span className="prep-field__label">{field.label || kindLabel(field.kind)}</span>
      {selected && editable && (
        <span
          className="prep-field__handle"
          style={{ background: color }}
          data-testid="resize-handle"
          onPointerDown={begin("resize")}
          onPointerMove={track}
          onPointerUp={end}
          onPointerCancel={end}
        />
      )}
    </div>
  );
}

/** The editor where each signer's elements (signature, date, name…) are placed on a document by
 *  drag and drop. A page of its own (from a campaign already sent), or the "Préparer" step of
 *  the sending flow, where it sits under the strip of documents (`embedded`). */
export function DocumentEditor({
  versionId,
  campaignId,
  embedded = false,
  onFinish,
  onSaved,
}: {
  versionId: string;
  campaignId: string | null;
  embedded?: boolean;
  /** Called when the person is done with this document: the next one to prepare, or none. */
  onFinish: (nextVersionId: string | null, backTo: string) => void;
  /** Called after the elements were saved (so the counts around can be refreshed). */
  onSaved?: () => void;
}) {
  const { t } = useTranslation();
  const id = versionId;
  const [info, setInfo] = useState<FieldsResponse | null>(null);
  const [pages, setPages] = useState<PageSize[]>([]);
  const [fields, setFields] = useState<EditorField[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [recipients, setRecipients] = useState(1);
  const [activeRole, setActiveRole] = useState(1);
  // The people who sign are the campaign's (chosen among the users before preparing):
  // each element is given to one of them, or to "every recipient".
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [armed, setArmed] = useState<FieldKind | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<FieldsResponse>(`/documents/versions/${id}/fields`),
      api.get<PageSize[]>(`/documents/versions/${id}/pages`),
    ])
      .then(([loaded, sizes]) => {
        setInfo(loaded);
        setFields(loaded.fields);
        setPages(sizes);
        // The signers also come from the campaign (loaded on its own): whichever answer arrives
        // last must not shrink the list the other one made.
        setRecipients((n) => Math.max(n, 1, ...loaded.fields.map((f) => f.role)));
      })
      .catch((err) => setLoadError(errorText(err, "prepare.documentNotFound")));
  }, [id]);

  useEffect(() => {
    if (!campaignId) return;
    api
      .get<Campaign>(`/campaigns/${campaignId}`)
      .then((loaded) => {
        setCampaign(loaded);
        setRecipients((n) => Math.max(n, loaded.roles.length, 1));
      })
      .catch((err) => setLoadError(errorText(err, "prepare.campaignNotFound")));
  }, [campaignId]);

  const editable = info?.editable ?? false;
  // Whoever the campaign says signs in this position — a person, or every recipient.
  const roleName = (role: number) => {
    const party = campaign?.roles.find((r) => r.role === role);
    if (!party) return t("prepare.position", { n: role });
    return party.mode === "EACH" ? t("prepare.everyRecipient") : (party.user_display_name ?? t("prepare.position", { n: role }));
  };
  const backTo = !campaignId
    ? "/sign"
    : campaign && campaign.status !== "DRAFT"
      ? `/campaigns/${campaignId}`
      : `/sign/${campaignId}?step=3`;
  const selected = fields.find((f) => f.id === selectedId) ?? null;

  const update = useCallback((fieldId: string, patch: Partial<EditorField>) => {
    setFields((all) => all.map((f) => (f.id === fieldId ? { ...f, ...patch } : f)));
    setDirty(true);
    setMessage(null);
  }, []);

  const place = useCallback(
    (kind: FieldKind, page: number, point: { x: number; y: number }) => {
      const rect = tidy(placeCentered(kind, point));
      const created: EditorField = {
        id: crypto.randomUUID(),
        page,
        ...rect,
        kind,
        label: "",
        required: kind === "TEXT",
        role: activeRole,
        group_key: null,
      };
      setFields((all) => [...all, created]);
      setSelectedId(created.id);
      setDirty(true);
      setMessage(null);
      setArmed(null);
    },
    [activeRole],
  );

  const remove = useCallback((fieldId: string) => {
    setFields((all) => all.filter((f) => f.id !== fieldId));
    setSelectedId(null);
    setDirty(true);
    setMessage(null);
  }, []);

  // Keyboard: Delete removes, arrows nudge by half a percent, Escape lets go.
  useEffect(() => {
    if (!editable) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (e.key === "Escape") {
        setSelectedId(null);
        setArmed(null);
        return;
      }
      if (!selectedId) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        remove(selectedId);
      }
      const step = e.shiftKey ? 0.02 : 0.005;
      const nudge: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
      };
      const delta = nudge[e.key];
      if (delta) {
        e.preventDefault();
        setFields((all) =>
          all.map((f) => (f.id === selectedId ? { ...f, ...tidy(moveRect(f, delta[0], delta[1])) } : f)),
        );
        setDirty(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable, selectedId, remove]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = async (): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<FieldsResponse>(`/documents/versions/${id}/fields`, {
        fields: fields.map(({ id: fieldId, page, x, y, width, height, kind, label, required, role, group_key }) => ({
          id: fieldId, page, ...tidy({ x, y, width, height }), kind, label, required, role, group_key,
        })),
      });
      setFields(saved.fields);
      setDirty(false);
      setMessage(t("prepare.savedCount", { count: saved.fields.length }));
      onSaved?.();
      return true;
    } catch (err) {
      setError(errorText(err, "prepare.saveFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Preparing is part of sending a document for signature: when done, back to the
  // campaign, which freezes (publishes) the document when it is launched.
  const nextToPrepare = campaign?.documents.find((d) => d.version_id !== id && d.elements === 0);
  const finish = async () => {
    if (dirty && !(await save())) return;
    onFinish(nextToPrepare?.version_id ?? null, backTo);
  };

  const onDrop = (page: number, overlay: HTMLDivElement) => (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const kind = e.dataTransfer.getData(DRAG_TYPE) as FieldKind;
    if (!kind || !KIND_BY_ID[kind]) return;
    place(kind, page, pointToFraction(e.clientX, e.clientY, overlay.getBoundingClientRect()));
  };

  const counts = useMemo(() => {
    const byRole = new Map<number, number>();
    fields.forEach((f) => byRole.set(f.role, (byRole.get(f.role) ?? 0) + 1));
    return byRole;
  }, [fields]);

  if (!campaignId)
    return (
      <p className="muted">
        <Trans i18nKey="prepare.needRequest" components={{ sign: <Link to="/sign" /> }} />
      </p>
    );
  if (loadError) return <p className="error-text">{loadError}</p>;
  if (campaign && campaign.roles.length === 0)
    return (
      <p className="muted">
        <Trans i18nKey="prepare.chooseSignersFirst" components={{ back: <Link to={backTo} /> }} />
      </p>
    );
  if (!info) return <p className="muted">{t("common.loading")}</p>;

  const pagesWithFields = new Set(fields.map((f) => f.page)).size;

  return (
    <div className="stack prep">
      {!embedded && (
        <Link to={backTo} className="back-link">
          <ArrowLeft size={14} aria-hidden="true" /> {campaign ? campaign.name : t("nav.sign")}
        </Link>
      )}
      <div className="page-header">
        <div>
          {embedded ? (
            <p className="page-subtitle" style={{ margin: 0 }}>
              <Trans
                i18nKey="prepare.versionLine"
                values={{ title: info.document_title, version: info.version_label }}
                components={{ strong: <strong /> }}
              />
            </p>
          ) : (
            <>
              <h1 className="page-title" style={{ margin: 0 }}>
                {t("prepare.pageTitle")}
              </h1>
              <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
                {t("prepare.subtitle", { title: info.document_title, version: info.version_label })}{" "}
                <span className={`badge badge--${info.status.toLowerCase()}`}>{versionStatus(info.status)}</span>
              </p>
            </>
          )}
        </div>
        {editable && (
          <div className="row-actions">
            <span className="muted small" data-testid="prep-status">
              {dirty
                ? t("prepare.unsaved")
                : (message ?? t("prepare.summary", { count: fields.length, pages: pagesWithFields }))}
            </span>
            <button className="button button--secondary" onClick={() => void save()} disabled={saving || !dirty}>
              <Save size={14} aria-hidden="true" /> {saving ? t("common.saving") : t("common.save")}
            </button>
            <button className="button button--primary" onClick={() => void finish()} disabled={saving}>
              <CheckCircle2 size={14} aria-hidden="true" />{" "}
              {nextToPrepare
                ? t("prepare.nextDocument", { title: nextToPrepare.title })
                : embedded
                  ? t("prepare.finishReview")
                  : t("prepare.finish")}
            </button>
          </div>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!editable && (
        <p className="prep-locked-note">
          <Lock size={14} aria-hidden="true" /> {t("prepare.locked")}
        </p>
      )}

      <div className="prep-layout">
        <aside className="prep-rail" aria-label={t("prepare.palette")}>
          {editable && (
            <>
              <div className="prep-rail__title">{t("prepare.whoSigns")}</div>
              <p className="muted small" style={{ margin: "0 0 8px" }}>
                {t("prepare.whoSignsHelp")}
              </p>
              <ul className="prep-roles">
                {Array.from({ length: recipients }, (_, i) => i + 1).map((role) => (
                  <li key={role}>
                    <button
                      type="button"
                      className={`prep-role${activeRole === role ? " prep-role--active" : ""}`}
                      style={{ ["--role" as string]: roleColor(role) }}
                      aria-pressed={activeRole === role}
                      data-testid={`role-${role}`}
                      onClick={() => setActiveRole(role)}
                    >
                      <span className="prep-role__dot" />
                      <UserRound size={14} aria-hidden="true" />
                      <span className="prep-role__name">{roleName(role)}</span>
                      <span className="prep-role__count">{counts.get(role) ?? 0}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <Link to={backTo} className="muted small">
                {t("prepare.editSigners")}
              </Link>

              <div className="prep-rail__title" style={{ marginTop: 18 }}>
                {t("prepare.elementsToPlace")}
              </div>
              <p className="muted small" style={{ margin: "0 0 8px" }}>
                {t("prepare.dragHelp")}
              </p>
              <ul className="prep-palette">
                {KINDS.map((meta) => {
                  const Icon = meta.icon;
                  return (
                    <li key={meta.kind}>
                      <button
                        type="button"
                        draggable
                        className={`prep-tool${armed === meta.kind ? " prep-tool--armed" : ""}`}
                        data-testid={`tool-${meta.kind}`}
                        aria-pressed={armed === meta.kind}
                        title={kindHint(meta.kind)}
                        onDragStart={(e) => {
                          e.dataTransfer.setData(DRAG_TYPE, meta.kind);
                          e.dataTransfer.effectAllowed = "copy";
                        }}
                        onClick={() => setArmed(armed === meta.kind ? null : meta.kind)}
                      >
                        <Icon size={15} aria-hidden="true" />
                        <span>
                          {kindLabel(meta.kind)}
                          <small>{meta.automatic ? t("kinds.automatic") : t("kinds.typed")}</small>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {!editable && <p className="muted small">{t("prepare.readOnly")}</p>}
        </aside>

        <section className="prep-canvas">
          <PdfPages
            url={`/api/documents/versions/${id}/content`}
            pages={pages}
            renderOverlay={(page, frame) => (
              <div
                className={`prep-overlay${armed ? " prep-overlay--armed" : ""}`}
                data-testid={`overlay-${page.number}`}
                onDragOver={(e) => editable && e.preventDefault()}
                onDrop={(e) => editable && frame && onDrop(page.number, frame)(e)}
                onPointerDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (armed && editable && frame) {
                    place(armed, page.number, pointToFraction(e.clientX, e.clientY, frame.getBoundingClientRect()));
                  } else {
                    setSelectedId(null);
                  }
                }}
              >
                {fields
                  .filter((f) => f.page === page.number)
                  .map((f) => (
                    <FieldBox
                      key={f.id}
                      field={f}
                      selected={f.id === selectedId}
                      editable={editable}
                      overlay={frame}
                      onSelect={() => setSelectedId(f.id)}
                      onChange={(rect) => update(f.id, clampRect(rect))}
                    />
                  ))}
              </div>
            )}
          />
        </section>

        <aside className="prep-props" aria-label={t("prepare.properties")}>
          <div className="prep-rail__title">{t("prepare.properties")}</div>
          {!selected && <p className="muted small">{t("prepare.selectHint")}</p>}
          {selected && (
            <div className="stack" style={{ gap: 12 }}>
              <div>
                <strong>{kindLabel(selected.kind)}</strong>
                <div className="muted small">{kindHint(selected.kind)}</div>
              </div>
              <label>
                {t("prepare.role")}
                <select
                  value={selected.role}
                  disabled={!editable}
                  onChange={(e) => update(selected.id, { role: Number(e.target.value) })}
                >
                  {Array.from({ length: recipients }, (_, i) => i + 1).map((role) => (
                    <option key={role} value={role}>
                      {roleName(role)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("prepare.label")}
                <input
                  value={selected.label}
                  maxLength={120}
                  disabled={!editable}
                  placeholder={kindLabel(selected.kind)}
                  onChange={(e) => update(selected.id, { label: e.target.value })}
                />
              </label>
              {selected.kind === "TEXT" && (
                <>
                  <label className="consent-row">
                    <input
                      type="checkbox"
                      checked={selected.required}
                      disabled={!editable}
                      onChange={(e) => update(selected.id, { required: e.target.checked })}
                    />
                    <span>{t("prepare.required")}</span>
                  </label>
                  <label>
                    {t("prepare.sharedKey")}
                    <input
                      value={selected.group_key ?? ""}
                      maxLength={60}
                      disabled={!editable}
                      placeholder={t("prepare.sharedKeyPlaceholder")}
                      onChange={(e) => update(selected.id, { group_key: e.target.value || null })}
                    />
                    <span className="muted small">
                      {t("prepare.sharedKeyHelp")}
                    </span>
                  </label>
                </>
              )}
              {editable && (
                <button className="button button--ghost button--sm" onClick={() => remove(selected.id)}>
                  <Trash2 size={13} aria-hidden="true" /> {t("prepare.deleteElement")}
                </button>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/** The editor as a page of its own, for a document of a campaign already sent. */
export default function PrepareDocumentPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [query] = useSearchParams();
  const campaignId = query.get("campaign");
  return (
    <DocumentEditor
      key={id}
      versionId={id ?? ""}
      campaignId={campaignId}
      onFinish={(next, backTo) =>
        navigate(next ? `/documents/versions/${next}/prepare?campaign=${campaignId}` : backTo)
      }
    />
  );
}
