import { useEffect, useRef } from "react";
import i18n from "@/i18n";

/**
 * Keyboard shortcuts. Keys are KeyboardEvent.key values, lower-cased for letters ("j", "arrowleft", "escape"),
 * optionally prefixed with "mod+" (Ctrl or ⌘) and/or "shift+": "mod+z", "mod+shift+z", "?".
 * Ignored while typing in a field (except Escape) and while a modifier the binding does not ask for is held.
 */
export type ShortcutMap = Record<string, (e: KeyboardEvent) => void>;

export function shortcutName(e: KeyboardEvent): string {
  const key = e.key.toLowerCase();
  const mod = e.ctrlKey || e.metaKey ? "mod+" : "";
  // shift is part of printable symbols already ("?"), so only name it for letters and named keys
  const shift = e.shiftKey && (/^[a-z]$/.test(key) || e.key.length > 1) ? "shift+" : "";
  return `${mod}${shift}${key}`;
}

function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName === "INPUT") {
    const type = (el as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit"].includes(type); // a range takes the arrow keys
  }
  return false;
}

export function useShortcuts(map: ShortcutMap, enabled = true) {
  const ref = useRef(map);
  useEffect(() => {
    ref.current = map;
  });
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.altKey) return;
      // a dialog on top (a confirmation, the chooser, «More»…) owns the keyboard: nothing acts underneath
      if (document.querySelector("dialog[open]")) return;
      const name = shortcutName(e);
      if (typing(e.target) && name !== "escape") return;
      // a held key repeats: fine for moving between shots, not for «Don't use» or «Pin»
      if (e.repeat && !name.startsWith("arrow") && name !== "j" && name !== "k") return;
      const fn = ref.current[name];
      if (fn) {
        e.preventDefault();
        fn(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}

/** The shortcuts of the storyboard / shot editor, for the "?" help sheet (keys, what they do). */
export const shortcutHelp = (): [string, string][] => [
  ["← → · J K", i18n.t("common:shortcuts.prevNext")],
  [i18n.t("common:shortcuts.keyEnter"), i18n.t("common:shortcuts.open")],
  ["Esc", i18n.t("common:shortcuts.close")],
  ["C", i18n.t("common:shortcuts.change")],
  ["X", i18n.t("common:shortcuts.reject")],
  ["F", i18n.t("common:shortcuts.pin")],
  ["P", i18n.t("common:shortcuts.play")],
  ["Ctrl Z", i18n.t("common:shortcuts.undo")],
  [i18n.t("common:shortcuts.keyRedo"), i18n.t("common:shortcuts.redo")],
  ["?", i18n.t("common:shortcuts.help")],
];
