import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

interface ToastData {
  id: number;
  text: string;
  action?: { label: string; run: () => void };
  tone?: "error";
}

type Show = (t: Omit<ToastData, "id">) => void;
const Ctx = createContext<Show>(() => {});

/** One toast at a time at the bottom ("Foto cambiada · Deshacer"); errors stay a bit longer. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [toast, setToast] = useState<ToastData | null>(null);
  const seq = useRef(0);
  // While a modal <dialog> is open the rest of the page is inert (clicks go nowhere): show the toast inside the
  // topmost open dialog, so it can be read and used there too.
  // The host is picked on the next frame: a dialog closing right before the toast (the chooser after «Use it»)
  // is closed by then. If the host closes later, the toast moves to the next open dialog, or to the page.
  const [host, setHost] = useState<Element | null>(null);
  const [placed, setPlaced] = useState(false);
  const pickHost = useCallback(() => {
    const open = document.querySelectorAll("dialog[open]");
    setHost(open.length ? open[open.length - 1]! : null);
    setPlaced(true);
  }, []);
  const show = useCallback<Show>(
    (t) => {
      setPlaced(false);
      setToast({ ...t, id: ++seq.current });
      requestAnimationFrame(pickHost);
    },
    [pickHost],
  );
  useEffect(() => {
    if (!host) return;
    const onClose = () => requestAnimationFrame(pickHost);
    host.addEventListener("close", onClose);
    return () => host.removeEventListener("close", onClose);
  }, [host, pickHost]);
  useEffect(() => {
    if (!toast) return;
    const h = setTimeout(() => setToast(null), toast.tone === "error" ? 9000 : 6000);
    return () => clearTimeout(h);
  }, [toast]);
  const error = toast?.tone === "error";
  return (
    <Ctx.Provider value={show}>
      {children}
      {/* two fixed live regions, so screen readers announce each kind reliably */}
      <div className="sr-only" role="status" aria-live="polite">
        {toast && !error ? toast.text : ""}
      </div>
      <div className="sr-only" role="alert">
        {toast && error ? toast.text : ""}
      </div>
      {toast &&
        placed &&
        createPortal(
          <div
            className="toast"
            key={toast.id}
            style={error ? { borderColor: "var(--color-danger-line)" } : undefined}
          >
            <span className={error ? "danger-text" : undefined}>{toast.text}</span>
            {toast.action && (
              <button
                type="button"
                className="btn sm"
                onClick={() => {
                  toast.action!.run();
                  setToast(null);
                }}
              >
                {toast.action.label}
              </button>
            )}
            <button
              type="button"
              className="icon-btn sm bare"
              aria-label={t("toast.close")}
              onClick={() => setToast(null)}
            >
              <X className="ico" />
            </button>
          </div>,
          host && host.isConnected && (host as HTMLDialogElement).open ? host : document.body,
        )}
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
