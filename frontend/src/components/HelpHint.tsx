import { useId, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";

/** A small (i) that explains a setting on hover or keyboard focus, with an
 *  example of what to type. The bubble is a real tooltip for assistive tech. */
export default function HelpHint({
  title,
  children,
  example,
}: {
  title: string;
  children: ReactNode;
  example?: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <span className="help">
      <button type="button" className="help__button" aria-label={t("common.help", { title })} aria-describedby={id}>
        <Info size={14} aria-hidden="true" />
      </button>
      <span role="tooltip" id={id} className="help__bubble">
        <strong>{title}</strong>
        <span>{children}</span>
        {example && (
          <span className="help__example">
            {t("common.example")} <code>{example}</code>
          </span>
        )}
      </span>
    </span>
  );
}
