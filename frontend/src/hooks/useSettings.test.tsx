import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";

import { keys } from "@/api/queries";
import type { Project } from "@/api/types";

import { useSettings } from "./useSettings";

function setup() {
  const qc = new QueryClient();
  qc.setQueryData(keys.project("p1"), { id: "p1", title: "Viejo", running: null } as unknown as Project);
  const bodies: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      bodies.push(body);
      return new Response(JSON.stringify({ id: "p1", title: "Viejo", running: null, ...body }), {
        headers: { "content-type": "application/json" },
      });
    }),
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useSettings("p1"), { wrapper });
  return { qc, bodies, hook };
}

describe("useSettings", () => {
  afterEach(() => {
    cleanup(); // unmounting saves what is pending: it must still see the stubbed fetch
    vi.unstubAllGlobals();
  });

  it("shows a change at once and saves typed text in one request on flush", async () => {
    vi.useFakeTimers();
    const { qc, bodies, hook } = setup();
    act(() => {
      hook.result.current.set({ title: "N" }, { debounce: true });
      hook.result.current.set({ title: "Nuevo" }, { debounce: true });
      hook.result.current.set({ title_overlay: "Hola" }, { debounce: true });
    });
    expect(qc.getQueryData<Project>(keys.project("p1"))?.title).toBe("Nuevo");
    expect(bodies).toEqual([]);
    await act(() => hook.result.current.flush());
    expect(bodies).toEqual([{ title: "Nuevo", title_overlay: "Hola" }]);
    vi.useRealTimers();
  });

  it("keeps typed text on top of a refetch that arrives before it is saved", () => {
    vi.useFakeTimers();
    const { qc, hook } = setup();
    act(() => hook.result.current.set({ title: "Escribiendo" }, { debounce: true }));
    act(() => {
      qc.setQueryData(keys.project("p1"), {
        id: "p1",
        title: "Viejo",
        running: "render",
      } as unknown as Project);
    });
    expect(qc.getQueryData<Project>(keys.project("p1"))?.title).toBe("Escribiendo");
    vi.useRealTimers();
  });

  it("saves non-text changes immediately", async () => {
    const { bodies, hook } = setup();
    await act(async () => {
      hook.result.current.set({ pace: "fast" });
      await hook.result.current.flush();
    });
    expect(bodies).toEqual([{ pace: "fast" }]);
  });
});
