import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useShortcuts, type ShortcutMap } from "./useShortcuts";

function Harness({ map }: { map: ShortcutMap }) {
  useShortcuts(map);
  return <input aria-label="campo" />;
}

describe("useShortcuts", () => {
  it("runs bindings, with modifiers, and not while typing", async () => {
    const calls: string[] = [];
    const map = {
      j: () => calls.push("next"),
      "mod+z": () => calls.push("undo"),
      "mod+shift+z": () => calls.push("redo"),
      "?": () => calls.push("help"),
      escape: () => calls.push("close"),
    };
    const { getByLabelText } = render(<Harness map={map} />);
    const user = userEvent.setup();
    await user.keyboard("j{Control>}z{/Control}{Control>}{Shift>}z{/Shift}{/Control}?");
    expect(calls).toEqual(["next", "undo", "redo", "help"]);
    await user.click(getByLabelText("campo"));
    await user.keyboard("j{Escape}");
    expect(calls).toEqual(["next", "undo", "redo", "help", "close"]);
  });

  it("does nothing while a dialog is open, and letters do not auto-repeat", async () => {
    const calls: string[] = [];
    render(<Harness map={{ x: () => calls.push("x"), arrowright: () => calls.push("next") }} />);
    const user = userEvent.setup();
    const d = document.createElement("dialog");
    d.setAttribute("open", "");
    document.body.appendChild(d);
    await user.keyboard("x");
    d.remove();
    await user.keyboard("{x>3/}{ArrowRight>2/}");
    expect(calls).toEqual(["x", "next", "next"]);
  });
});
