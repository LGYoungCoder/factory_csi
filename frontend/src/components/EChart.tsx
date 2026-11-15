import * as echarts from "echarts";
import { useEffect, useRef } from "react";

export function EChart({ option, height = 220 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, "dark", { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption({ backgroundColor: "transparent", animation: false, ...option }, true);
  }, [option]);
  return <div ref={ref} style={{ height }} className="w-full" />;
}
