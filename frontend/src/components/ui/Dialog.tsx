import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Modal dialog on <dialog> (focus trap, Esc, inert page for free); a bottom sheet on phones. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
  className = "",
  bodyClassName = "dlg-body",
  headClassName = "",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
  className?: string;
  bodyClassName?: string;
  headClassName?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      d.querySelector<HTMLElement>("[data-autofocus]")?.focus(); // else the browser picks the first button
    }
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={`dlg ${wide ? "wide" : ""} ${className}`}
      aria-labelledby={titleId}
      // the native close event comes late: if the same dialog was opened again meanwhile (two confirmations
      // in a row), that late event must not close the second one
      onClose={() => {
        if (!ref.current?.open) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on the backdrop
      }}
    >
      {open && (
        <div className="dlg-in">
          <div className={`modal-head ${headClassName}`}>
            <div className="grow" style={{ minWidth: 0 }} id={titleId}>
              {typeof title === "string" ? <h2>{title}</h2> : title}
            </div>
            <button type="button" className="icon-btn bare" aria-label={t("actions.close")} onClick={onClose}>
              <X className="ico" />
            </button>
          </div>
          <div className={bodyClassName}>{children}</div>
        </div>
      )}
    </dialog>
  );
}
