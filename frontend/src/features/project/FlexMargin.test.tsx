import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { FlexMargin } from "./PhotosStep";

function Harness({ start, saved }: { start: number; saved: number[] }) {
  const [v, setV] = useState(start);
  return (
    <>
      <FlexMargin
        value={v}
        onChange={(d) => {
          saved.push(d);
          setV(d);
        }}
        onDone={() => {}}
      />
      <button type="button" onClick={() => setV(14)}>
        deshacer
      </button>
    </>
  );
}

describe("FlexMargin", () => {
  it("saves a custom number of days, and the most there can be when it is too many", async () => {
    const saved: number[] = [];
    render(<Harness start={7} saved={saved} />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Margen de fechas"), "custom");
    const days = screen.getByLabelText("Margen en días");
    await user.clear(days);
    await user.type(days, "90");
    expect(saved.at(-1)).toBe(90);
    await user.clear(days);
    await user.type(days, "400");
    expect(screen.getByRole("alert")).toHaveTextContent("365");
    fireEvent.blur(days);
    expect(saved.at(-1)).toBe(365);
    expect(days).toHaveValue(365);
  });

  it("ignores decimals, and goes back to what is saved on leaving", async () => {
    const saved: number[] = [];
    render(<Harness start={45} saved={saved} />);
    const user = userEvent.setup();
    const days = screen.getByLabelText("Margen en días");
    await user.clear(days);
    await user.type(days, "2.5");
    expect(saved).toEqual([2]);
    fireEvent.blur(days);
    expect(days).toHaveValue(2);
  });

  it("follows a change from outside to a usual margin", async () => {
    render(<Harness start={45} saved={[]} />);
    expect(screen.getByLabelText("Margen de fechas")).toHaveValue("custom");
    await userEvent.setup().click(screen.getByText("deshacer"));
    expect(screen.getByLabelText("Margen de fechas")).toHaveValue("14");
    expect(screen.queryByLabelText("Margen en días")).toBeNull();
  });
});
