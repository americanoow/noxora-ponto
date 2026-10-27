import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { addDays, dayLabel, hm, monthRange } from "./format";
import { Observable, useObservable } from "./observable";
import { Router, decode, encode } from "./router";

class Counter extends Observable<{ a: number; b: number }> {
  constructor() {
    super({ a: 0, b: 0 });
  }
  incA = () => this.set({ a: this.state.a + 1 });
  incB = () => this.set({ b: this.state.b + 1 });
}

describe("Observable", () => {
  it("só re-renderiza quem lê a propriedade alterada", () => {
    const model = new Counter();
    let renders = 0;
    const selectA = (s: { a: number }) => s.a;
    const { result } = renderHook(() => {
      renders++;
      return useObservable(model, selectA);
    });
    const before = renders;
    act(() => model.incB());
    expect(renders).toBe(before);
    act(() => model.incA());
    expect(result.current).toBe(1);
    expect(renders).toBe(before + 1);
  });
});

describe("Router", () => {
  it("codifica e decodifica a pilha tipada", () => {
    const path = [{ screen: "employees" as const }, { screen: "employee" as const, id: 7 }];
    const hash = encode(path);
    expect(hash).toBe("employees/employee?id=7");
    expect(decode(`#/${hash}`, () => true)).toEqual(path);
    expect(decode("#/proibida", (s) => s !== "proibida")).toEqual([]);
  });

  it("empilha, volta e troca de seção", () => {
    const router = new Router({ screen: "today" });
    router.select({ screen: "closings" });
    router.push({ screen: "closing", id: 3 });
    expect(router.top).toEqual({ screen: "closing", id: 3 });
    router.pop();
    expect(router.state.path).toEqual([{ screen: "closings" }]);
    router.replaceTop({ screen: "timesheet", employeeId: 2 });
    expect(window.location.hash).toBe("#/timesheet?employeeId=2");
  });
});

describe("format", () => {
  it("formata horas e datas sem depender do fuso do navegador", () => {
    expect(hm(125)).toBe("02:05");
    expect(hm(-61)).toBe("−01:01");
    expect(dayLabel("2026-10-19")).toBe("seg 19/10");
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(monthRange("2026-02-10")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
  });
});
