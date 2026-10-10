import i18n from "../i18n";
import {
  CalendarDays,
  Image as ImageIcon,
  Mail,
  PenLine,
  Type,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type FieldKind = "SIGNATURE" | "DATE" | "FULL_NAME" | "EMAIL" | "TEXT" | "LOGO";

export interface KindMeta {
  kind: FieldKind;
  automatic: boolean;
  icon: LucideIcon;
  /** Default size, as a fraction of the page. */
  width: number;
  height: number;
}

/** The elements an operator can place, in the order of the palette. */
export const KINDS: KindMeta[] = [
  { kind: "SIGNATURE", automatic: true, icon: PenLine, width: 0.28, height: 0.06 },
  { kind: "DATE", automatic: true, icon: CalendarDays, width: 0.18, height: 0.035 },
  { kind: "FULL_NAME", automatic: true, icon: UserRound, width: 0.26, height: 0.035 },
  { kind: "EMAIL", automatic: true, icon: Mail, width: 0.3, height: 0.035 },
  { kind: "TEXT", automatic: false, icon: Type, width: 0.3, height: 0.04 },
  { kind: "LOGO", automatic: true, icon: ImageIcon, width: 0.2, height: 0.09 },
];

export const KIND_BY_ID: Record<FieldKind, KindMeta> = Object.fromEntries(
  KINDS.map((k) => [k.kind, k]),
) as Record<FieldKind, KindMeta>;

/** What each element is called and says, in the active language. */
export const kindLabel = (kind: FieldKind): string => i18n.t(`kinds.${kind}.label`);
export const kindHint = (kind: FieldKind): string => i18n.t(`kinds.${kind}.hint`);

/** One colour per recipient, so "who fills what" reads at a glance. */
export const ROLE_COLORS = [
  "#65459b", "#2563eb", "#0f9d6b", "#d97706", "#db2777",
  "#0891b2", "#7c3aed", "#65a30d", "#dc2626", "#475569",
];

export const MAX_RECIPIENTS = ROLE_COLORS.length;

export const roleColor = (role: number): string => ROLE_COLORS[(role - 1) % ROLE_COLORS.length];
