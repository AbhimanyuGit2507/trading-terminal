"use client";

import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { formatInr } from "@/lib/format";
import {
  evaluatePayoff,
  type QuantLeg,
  splitSeriesForECharts,
} from "@/lib/quant";
import { useMarketStore } from "@/stores/marketStore";
import { useStrategyStore } from "@/stores/strategyStore";
import { useUiStore } from "@/stores/uiStore";
import { MetricsRibbon } from "./MetricsRibbon";
import { WhatIfControls } from "./WhatIfControls";

export function PayoffPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<echarts.ECharts | null>(null);

  const spot = useMarketStore((s) => s.spot);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const indiaVix = useMarketStore((s) => s.indiaVix);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);

  const legs = useStrategyStore((s) => s.legs);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const margin = useStrategyStore((s) => s.margin);
  const isLoadingMargin = useStrategyStore((s) => s.isLoadingMargin);
  const whatIf = useStrategyStore((s) => s.whatIf);

  const includeCharges = useUiStore((s) => s.includeCharges);

  const quantLegs: QuantLeg[] = useMemo(
    () =>
      legs.map((l) => ({
        leg_id: l.leg_id,
        symbol: l.symbol,
        expiry: l.expiry,
        option_type: l.option_type,
        side: l.side,
        lots: l.lots,
        lot_size: l.lot_size,
        entry_price: l.entry_price,
        entry_iv: activeLegQuotes[l.contract_id]
          ? activeLegQuotes[l.contract_id].iv / 100.0
          : l.entry_iv,
        strike: l.strike ?? null,
        forward_at_base:
          activeLegQuotes[l.contract_id]?.forward_price ?? l.forward_at_base ?? spot,
        enabled: l.enabled,
        status: l.status,
        exchange: l.exchange,
      })),
    [legs, activeLegQuotes, spot]
  );

  // Instantaneous <0.15ms TS Float64Array evaluation for 120fps sliders
  const evaluation = useMemo(
    () =>
      evaluatePayoff({
        spot,
        legs: quantLegs,
        baseDtIso: asOfIso || new Date().toISOString(),
        targetSpot: whatIf.targetSpot || spot,
        targetDtIso: whatIf.targetDatetimeIso || asOfIso || new Date().toISOString(),
        ivShiftPct: whatIf.ivShiftPct,
        realizedPnl,
        includeCharges,
        atmIv: Math.max(indiaVix / 100.0, 0.08),
        r: 0.0,
      }),
    [spot, quantLegs, asOfIso, whatIf, realizedPnl, includeCharges, indiaVix]
  );

  // Initialize ECharts canvas once
  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    chartInstanceRef.current = chart;

    const ro = new ResizeObserver(() => {
      chart.resize();
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, []);

  // Imperatively push updated payoff curves without tearing down ECharts
  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!chart) return;

    const { positiveExpiry, negativeExpiry, targetCurve } = splitSeriesForECharts(
      evaluation.points
    );
    const targetSpot = whatIf.targetSpot || spot;

    const markLines: Array<Record<string, unknown>> = [
      {
        xAxis: spot,
        lineStyle: { color: "#94a3b8", type: "dashed", width: 1.5 },
        label: {
          formatter: `Spot ${spot.toFixed(0)}`,
          color: "#cbd5e1",
          fontSize: 10,
          position: "insideEndTop",
        },
      },
      {
        xAxis: evaluation.sd_1_low,
        lineStyle: { color: "rgba(56, 189, 248, 0.25)", type: "dotted", width: 1 },
        label: { formatter: "-1σ", color: "#7dd3fc", fontSize: 9, position: "insideStartTop" },
      },
      {
        xAxis: evaluation.sd_1_high,
        lineStyle: { color: "rgba(56, 189, 248, 0.25)", type: "dotted", width: 1 },
        label: { formatter: "+1σ", color: "#7dd3fc", fontSize: 9, position: "insideStartTop" },
      },
    ];

    if (Math.abs(targetSpot - spot) >= 1) {
      markLines.push({
        xAxis: targetSpot,
        lineStyle: { color: "#f59e0b", type: "solid", width: 1.5 },
        label: {
          formatter: `Target ${targetSpot.toFixed(0)}`,
          color: "#fcd34d",
          fontSize: 10,
          position: "insideEndBottom",
        },
      });
    }

    const breakevenPins = evaluation.breakevens.map((be) => ({
      name: "BE",
      coord: [be, 0],
      value: be.toFixed(0),
      itemStyle: { color: "#f59e0b" },
    }));

    chart.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        grid: { left: 68, right: 24, top: 36, bottom: 32 },
        tooltip: {
          trigger: "axis",
          backgroundColor: "#0f172a",
          borderColor: "#334155",
          textStyle: { color: "#f1f5f9", fontSize: 11 },
          axisPointer: { type: "cross", lineStyle: { color: "#475569" } },
          formatter: (params: unknown) => {
            const arr = Array.isArray(params) ? params : [];
            if (arr.length === 0) return "";
            const first = arr[0] as { axisValue: number };
            const xSpot = Number(first.axisValue);
            const pt = evaluation.points.reduce((best, p) =>
              Math.abs(p.spot - xSpot) < Math.abs(best.spot - xSpot) ? p : best
            );
            const expClr = pt.expiry_pnl >= 0 ? "#10b981" : "#ef4444";
            const tgtClr = pt.target_pnl >= 0 ? "#38bdf8" : "#f87171";
            return `
              <div style="font-variant-numeric: tabular-nums;">
                <div style="color:#94a3b8;margin-bottom:4px;">Spot: <strong style="color:#f8fafc">${xSpot.toFixed(1)}</strong></div>
                <div>Expiry P&L: <strong style="color:${expClr}">${formatInr(pt.expiry_pnl, 0)}</strong></div>
                <div>Target MTM: <strong style="color:${tgtClr}">${formatInr(pt.target_pnl, 0)}</strong></div>
              </div>
            `;
          },
        },
        legend: {
          top: 4,
          right: 16,
          textStyle: { color: "#94a3b8", fontSize: 11 },
          data: ["Profit (Expiry)", "Loss (Expiry)", "Target / T+0 MTM"],
        },
        xAxis: {
          type: "value",
          scale: true,
          axisLine: { lineStyle: { color: "#334155" } },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 10,
            formatter: (v: number) => v.toFixed(0),
          },
          splitLine: { lineStyle: { color: "rgba(51, 65, 85, 0.35)" } },
        },
        yAxis: {
          type: "value",
          scale: true,
          axisLine: { lineStyle: { color: "#334155" } },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 10,
            formatter: (v: number) =>
              Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v.toFixed(0)}`,
          },
          splitLine: { lineStyle: { color: "rgba(51, 65, 85, 0.35)" } },
        },
        series: [
          {
            name: "Profit (Expiry)",
            type: "line",
            symbol: "none",
            smooth: false,
            connectNulls: false,
            lineStyle: { color: "#10b981", width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "rgba(16, 185, 129, 0.38)" },
                { offset: 1, color: "rgba(16, 185, 129, 0.04)" },
              ]),
            },
            data: positiveExpiry,
            markLine: {
              symbol: "none",
              silent: true,
              data: [{ yAxis: 0, lineStyle: { color: "#64748b", width: 1 } }, ...markLines],
            },
            markPoint: {
              symbol: "pin",
              symbolSize: 32,
              label: { fontSize: 9, color: "#0b0f17", fontWeight: "bold" },
              data: breakevenPins,
            },
          },
          {
            name: "Loss (Expiry)",
            type: "line",
            symbol: "none",
            smooth: false,
            connectNulls: false,
            lineStyle: { color: "#ef4444", width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "rgba(239, 68, 68, 0.04)" },
                { offset: 1, color: "rgba(239, 68, 68, 0.38)" },
              ]),
            },
            data: negativeExpiry,
          },
          {
            name: "Target / T+0 MTM",
            type: "line",
            symbol: "none",
            smooth: true,
            lineStyle: { color: "#38bdf8", width: 2, type: "dashed" },
            data: targetCurve,
          },
        ],
      },
      { notMerge: true }
    );
  }, [evaluation, spot, whatIf.targetSpot]);

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-[#111827] p-3 shadow-lg">
      <MetricsRibbon
        evaluation={evaluation}
        realizedPnl={realizedPnl}
        margin={margin}
        isLoadingMargin={isLoadingMargin}
      />

      {/* Interactive ECharts Payoff Graph */}
      <div className="rounded-lg border border-slate-800 bg-[#0b101b] p-2">
        <div
          ref={chartContainerRef}
          aria-label="Strategy Payoff Graph"
          className="h-[340px] w-full"
        />
      </div>

      <WhatIfControls />
    </section>
  );
}

