import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider, ZH_KEYS } from "@/i18n";
import { StartButton } from "@/components/Workspace";
import { CATEGORY_LABEL, VTYPE_LABEL } from "@/lib/format";
import { STATUS_STYLE, SUPPORT_LABEL } from "@/lib/status";
import { STEPS } from "@/events/reducer";

const sources = import.meta.glob(["./components/*.tsx", "./pages/*.tsx"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("Chinese translations", () => {
  it("cover every literal t(\"…\") key in components and pages", () => {
    const keys = new Set(ZH_KEYS);
    const missing: string[] = [];
    for (const [file, src] of Object.entries(sources)) {
      for (const m of src.matchAll(/\bt[r]?\("((?:[^"\\]|\\.)+)"\)/g)) if (!keys.has(m[1])) missing.push(`${file}: ${m[1]}`);
    }
    expect(missing).toEqual([]);
  });
  it("cover labels rendered through t()", () => {
    const keys = new Set(ZH_KEYS);
    const labels = [...Object.values(CATEGORY_LABEL), ...Object.values(VTYPE_LABEL), ...Object.values(SUPPORT_LABEL),
      ...Object.values(STATUS_STYLE).map((s) => s.label), ...STEPS, "Evidence-supported cause", "Suspected cause",
      "Insufficient evidence for a conclusion", "supports", "contradicts", "neutral"];
    expect(labels.filter((l) => !keys.has(l))).toEqual([]);
  });
  it("renders Chinese when selected", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider lang="zh"><Tooltip.Provider><MemoryRouter>
          <StartButton disabledReason={null} onStart={() => {}} pending={false} />
        </MemoryRouter></Tooltip.Provider></I18nProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: /开始调查/ })).toBeInTheDocument();
  });
});
