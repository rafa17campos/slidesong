import { QueryClient } from "@tanstack/react-query";

import { applyProject, keys, planKey } from "./queries";
import type { Project } from "./types";

describe("applyProject", () => {
  it("merges the stored project over the cached view instead of replacing it", () => {
    const qc = new QueryClient();
    const view = {
      id: "p",
      slots: [],
      running: "render",
      history: { undo: "fijar", redo: null },
      server_now: "x",
    };
    qc.setQueryData(keys.project("p"), view as unknown as Project);
    qc.setQueryData(planKey("p"), { shots: [], boundaries: [] });
    applyProject(qc, "p", { id: "p", slots: [{ asset: "a" }], title: "nuevo" });
    const after = qc.getQueryData<Project>(keys.project("p"))!;
    expect(after.running).toBe("render"); // the job bar and polling stay
    expect(after.history?.undo).toBe("fijar"); // undo stays enabled until the refetch brings the new label
    expect(after.title).toBe("nuevo");
    expect(qc.getQueryState(keys.project("p"))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(planKey("p"))?.isInvalidated).toBe(true);
  });
});
