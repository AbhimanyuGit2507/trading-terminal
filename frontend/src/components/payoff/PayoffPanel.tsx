"use client";

import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { formatCompactOi, formatPnl, formatShortExpiry } from "@/lib/format";
import {
  buildPayoffTableRows,
  computeLegGreeksBreakdown,
  convertPnlByUnit,
  evaluatePayoff,
  type QuantLeg,
  splitSeriesForECharts,
} from "@/lib/quant";
import { useMarketStore } from "@/stores/marketStore";
import { getEffectiveLegs, useStrategyStore } from "@/stores/strategyStore";
import {
  type ChartOverlayKey,
  type PayoffRightTab,
  useUiStore,
} from "@/stores/uiStore";
import { MetricsRibbon } from "./MetricsRibbon";
import { WhatIfControls } from "./WhatIfControls";

const OVERLAY_OPTIONS: Array<{ key: ChartOverlayKey; label: string }> = [
  { key: "expiryPayoff", label: "Expiry Payoff" },
  { key: "targetMtm", label: "Target (T+0)" },
  { key: "sdBands", label: "SD Bands (1σ / 2σ)" },
  { key: "oiOverlay", label: "OI Overlay" },
];

const RIGHT_TABS: Array<{ key: PayoffRightTab; label: string }> = [
  { key: "graph", label: "Payoff Graph" },
  { key: "table", label: "Payoff Table" },
  { key: "greeks", label: "Greeks" },
];

export function PayoffPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<echarts.ECharts | null>(null);

  const spot = useMarketStore((s) => s.spot);
  const lotSize = useMarketStore((s) => s.lotSize);
  const asOfIso = useMarketStore((s) => s.asOfIso);
  const indiaVix = useMarketStore((s) => s.indiaVix);
  const activeLegQuotes = useMarketStore((s) => s.activeLegQuotes);
  const strikes = useMarketStore((s) => s.strikes);
  const rowsByStrike = useMarketStore((s) => s.rowsByStrike);

  const legs = useStrategyStore((s) => s.legs);
  const lotMultiplier = useStrategyStore((s) => s.lotMultiplier);
  const realizedPnl = useStrategyStore((s) => s.realizedPnl);
  const margin = useStrategyStore((s) => s.margin);
  const isLoadingMargin = useStrategyStore((s) => s.isLoadingMargin);
  const whatIf = useStrategyStore((s) => s.whatIf);

  const includeCharges = useUiStore((s) => s.includeCharges);
  const theme = useUiStore((s) => s.theme);
  const pnlUnit = useUiStore((s) => s.pnlUnit);
  const rightTab = useUiStore((s) => s.rightTab);
  const setRightTab = useUiStore((s) => s.setRightTab);
  const chartOverlays = useUiStore((s) => s.chartOverlays);
  const toggleChartOverlay = useUiStore((s) => s.toggleChartOverlay);

  const baseDtIso = asOfIso || new Date().toISOString();
  const targetDtIso = whatIf.targetDatetimeIso || baseDtIso;
  const targetSpot = whatIf.targetSpot || spot;

  const effectiveQuantLegs: QuantLeg[] = useMemo(
    () =>
      getEffectiveLegs(legs, lotMultiplier).map((l) => ({
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
    [legs, lotMultiplier, activeLegQuotes, spot]
  );

  // Base quant legs (1x) for LegGreeks breakdown which multiplies explicitly by lotMultiplier
  const baseQuantLegs: QuantLeg[] = useMemo(
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
        legs: effectiveQuantLegs,
        baseDtIso,
        targetSpot,
        targetDtIso,
        ivShiftPct: whatIf.ivShiftPct,
        realizedPnl,
        includeCharges,
        atmIv: Math.max(indiaVix / 100.0, 0.08),
        r: 0.0,
      }),
    [spot, effectiveQuantLegs, baseDtIso, targetSpot, targetDtIso, whatIf.ivShiftPct, realizedPnl, includeCharges, indiaVix]
  );

  const payoffTableRows = useMemo(() => {
    if (rightTab !== "table") return [];
    return buildPayoffTableRows({
      spot,
      legs: effectiveQuantLegs,
      baseDtIso,
      targetSpot,
      targetDtIso,
      ivShiftPct: whatIf.ivShiftPct,
      realizedPnl,
      includeCharges,
      atmIv: Math.max(indiaVix / 100.0, 0.08),
      r: 0.0,
      breakevens: evaluation.breakevens,
    });
  }, [
    rightTab,
    spot,
    effectiveQuantLegs,
    baseDtIso,
    targetSpot,
    targetDtIso,
    whatIf.ivShiftPct,
    realizedPnl,
    includeCharges,
    indiaVix,
    evaluation.breakevens,
  ]);

  const greeksBreakdown = useMemo(() => {
    if (rightTab !== "greeks") return null;
    return computeLegGreeksBreakdown({
      spot,
      targetSpot,
      legs: baseQuantLegs,
      baseDtIso,
      targetDtIso,
      ivShiftPct: whatIf.ivShiftPct,
      lotMultiplier,
      r: 0.0,
    });
  }, [rightTab, spot, targetSpot, baseQuantLegs, baseDtIso, targetDtIso, whatIf.ivShiftPct, lotMultiplier]);

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

  useEffect(() => {
    if (rightTab === "graph") {
      chartInstanceRef.current?.resize();
    }
  }, [rightTab]);

  // Imperatively push updated payoff curves, theme colors, & overlays
  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!chart) return;

    const isDark = theme === "dark";
    const axisLineColor = isDark ? "#334155" : "#cbd5e1";
    const axisLabelColor = isDark ? "#94a3b8" : "#64748b";
    const splitLineColor = isDark ? "rgba(51, 65, 85, 0.35)" : "rgba(203, 213, 225, 0.6)";
    const tooltipBg = isDark ? "#0f172a" : "#ffffff";
    const tooltipBorder = isDark ? "#334155" : "#cbd5e1";
    const tooltipText = isDark ? "#f1f5f9" : "#0f172a";
    const tooltipMuted = isDark ? "#94a3b8" : "#64748b";
    const legendTextColor = isDark ? "#94a3b8" : "#475569";
    const zeroLineColor = isDark ? "#64748b" : "#94a3b8";

    const profitLineColor = isDark ? "#10b981" : "#16A34A";
    const lossLineColor = isDark ? "#ef4444" : "#DC2626";
    const profitFillTop = isDark ? "rgba(16, 185, 129, 0.38)" : "rgba(22, 163, 74, 0.22)";
    const profitFillBot = isDark ? "rgba(16, 185, 129, 0.04)" : "rgba(22, 163, 74, 0.03)";
    const lossFillTop = isDark ? "rgba(239, 68, 68, 0.04)" : "rgba(220, 38, 38, 0.03)";
    const lossFillBot = isDark ? "rgba(239, 68, 68, 0.38)" : "rgba(220, 38, 38, 0.22)";
    const targetLineColor = isDark ? "#38bdf8" : "#2563EB";

    // Convert curve points to active display unit (INR or POINTS)
    const displayPoints = evaluation.points.map((p) => ({
      spot: p.spot,
      expiry_pnl: convertPnlByUnit(p.expiry_pnl, pnlUnit, lotSize),
      target_pnl: convertPnlByUnit(p.target_pnl, pnlUnit, lotSize),
    }));

    const { positiveExpiry, negativeExpiry, targetCurve } = splitSeriesForECharts(displayPoints);

    const markLines: Array<Record<string, unknown>> = [
      { yAxis: 0, lineStyle: { color: zeroLineColor, width: 1 } },
      {
        xAxis: spot,
        lineStyle: { color: isDark ? "#94a3b8" : "#475569", type: "dashed", width: 1.5 },
        label: {
          formatter: `Spot ${spot.toFixed(0)}`,
          color: isDark ? "#cbd5e1" : "#1e293b",
          fontSize: 10,
          position: "insideEndTop",
        },
      },
    ];

    if (chartOverlays.sdBands) {
      const sdColor = isDark ? "rgba(56, 189, 248, 0.35)" : "rgba(37, 99, 235, 0.35)";
      const sd2Color = isDark ? "rgba(148, 163, 184, 0.28)" : "rgba(100, 116, 139, 0.3)";
      const sdLabelColor = isDark ? "#7dd3fc" : "#2563eb";
      const sd2LabelColor = isDark ? "#94a3b8" : "#64748b";
      markLines.push(
        {
          xAxis: evaluation.sd_1_low,
          lineStyle: { color: sdColor, type: "dotted", width: 1 },
          label: { formatter: "-1σ", color: sdLabelColor, fontSize: 9, position: "insideStartTop" },
        },
        {
          xAxis: evaluation.sd_1_high,
          lineStyle: { color: sdColor, type: "dotted", width: 1 },
          label: { formatter: "+1σ", color: sdLabelColor, fontSize: 9, position: "insideStartTop" },
        },
        {
          xAxis: evaluation.sd_2_low,
          lineStyle: { color: sd2Color, type: "dotted", width: 1 },
          label: { formatter: "-2σ", color: sd2LabelColor, fontSize: 9, position: "insideStartTop" },
        },
        {
          xAxis: evaluation.sd_2_high,
          lineStyle: { color: sd2Color, type: "dotted", width: 1 },
          label: { formatter: "+2σ", color: sd2LabelColor, fontSize: 9, position: "insideStartTop" },
        }
      );
    }

    if (Math.abs(targetSpot - spot) >= 1) {
      markLines.push({
        xAxis: targetSpot,
        lineStyle: { color: "#f59e0b", type: "solid", width: 1.5 },
        label: {
          formatter: `Target ${targetSpot.toFixed(0)}`,
          color: isDark ? "#fcd34d" : "#b45309",
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

    const series: Array<Record<string, unknown>> = [];
    const legendNames: string[] = [];

    // Optional Call / Put OI distribution overlay
    let maxVisibleOi = 1;
    if (chartOverlays.oiOverlay && displayPoints.length >= 2) {
      const minX = displayPoints[0].spot;
      const maxX = displayPoints[displayPoints.length - 1].spot;
      const callOiData: Array<[number, number]> = [];
      const putOiData: Array<[number, number]> = [];
      for (const k of strikes) {
        if (k < minX || k > maxX) continue;
        const r = rowsByStrike[k];
        if (!r) continue;
        if (r.ce_oi > maxVisibleOi) maxVisibleOi = r.ce_oi;
        if (r.pe_oi > maxVisibleOi) maxVisibleOi = r.pe_oi;
        callOiData.push([k, r.ce_oi]);
        putOiData.push([k, r.pe_oi]);
      }

      legendNames.push("Call OI", "Put OI");
      series.push(
        {
          name: "Call OI",
          type: "bar",
          yAxisIndex: 1,
          barWidth: 5,
          itemStyle: { color: isDark ? "rgba(16, 185, 129, 0.25)" : "rgba(22, 163, 74, 0.22)" },
          data: callOiData,
          z: 1,
        },
        {
          name: "Put OI",
          type: "bar",
          yAxisIndex: 1,
          barWidth: 5,
          itemStyle: { color: isDark ? "rgba(239, 68, 68, 0.25)" : "rgba(220, 38, 38, 0.22)" },
          data: putOiData,
          z: 1,
        }
      );
    }

    if (chartOverlays.expiryPayoff) {
      legendNames.push("Profit (Expiry)", "Loss (Expiry)");
      series.push(
        {
          name: "Profit (Expiry)",
          type: "line",
          yAxisIndex: 0,
          symbol: "none",
          smooth: false,
          connectNulls: false,
          lineStyle: { color: profitLineColor, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: profitFillTop },
              { offset: 1, color: profitFillBot },
            ]),
          },
          data: positiveExpiry,
          markLine: {
            symbol: "none",
            silent: true,
            data: markLines,
          },
          markPoint: {
            symbol: "pin",
            symbolSize: 32,
            label: { fontSize: 9, color: "#0b0f17", fontWeight: "bold" },
            data: breakevenPins,
          },
          z: 3,
        },
        {
          name: "Loss (Expiry)",
          type: "line",
          yAxisIndex: 0,
          symbol: "none",
          smooth: false,
          connectNulls: false,
          lineStyle: { color: lossLineColor, width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: lossFillTop },
              { offset: 1, color: lossFillBot },
            ]),
          },
          data: negativeExpiry,
          z: 3,
        }
      );
    }

    if (chartOverlays.targetMtm) {
      legendNames.push("Target / T+0 MTM");
      series.push({
        name: "Target / T+0 MTM",
        type: "line",
        yAxisIndex: 0,
        symbol: "none",
        smooth: true,
        lineStyle: { color: targetLineColor, width: 2, type: "dashed" },
        data: targetCurve,
        markLine: !chartOverlays.expiryPayoff
          ? { symbol: "none", silent: true, data: markLines }
          : undefined,
        z: 4,
      });
    }

    chart.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        grid: { left: 68, right: 24, top: 36, bottom: 32 },
        tooltip: {
          trigger: "axis",
          backgroundColor: tooltipBg,
          borderColor: tooltipBorder,
          textStyle: { color: tooltipText, fontSize: 11 },
          axisPointer: { type: "cross", lineStyle: { color: axisLineColor } },
          formatter: (params: unknown) => {
            const arr = Array.isArray(params) ? params : [];
            if (arr.length === 0) return "";
            const first = arr[0] as { axisValue: number };
            const xSpot = Number(first.axisValue);
            const pt = evaluation.points.reduce((best, p) =>
              Math.abs(p.spot - xSpot) < Math.abs(best.spot - xSpot) ? p : best
            );
            const expClr = pt.expiry_pnl >= 0 ? profitLineColor : lossLineColor;
            const tgtClr = pt.target_pnl >= 0 ? targetLineColor : lossLineColor;

            let oiBlock = "";
            if (chartOverlays.oiOverlay && strikes.length > 0) {
              const nearestStrike = strikes.reduce((b, k) =>
                Math.abs(k - xSpot) < Math.abs(b - xSpot) ? k : b
              );
              const oiRow = rowsByStrike[nearestStrike];
              if (oiRow) {
                oiBlock = `<div style="margin-top:4px;font-size:10px;color:${tooltipMuted};">Strike ${nearestStrike}: CE OI ${formatCompactOi(oiRow.ce_oi)} · PE OI ${formatCompactOi(oiRow.pe_oi)}</div>`;
              }
            }

            return `
              <div style="font-variant-numeric: tabular-nums;">
                <div style="color:${tooltipMuted};margin-bottom:4px;">Spot: <strong style="color:${tooltipText}">${xSpot.toFixed(1)}</strong></div>
                <div>Expiry P&L: <strong style="color:${expClr}">${formatPnl(pt.expiry_pnl, pnlUnit, lotSize, { signed: true, decimals: pnlUnit === "POINTS" ? 2 : 0 })}</strong></div>
                <div>Target MTM: <strong style="color:${tgtClr}">${formatPnl(pt.target_pnl, pnlUnit, lotSize, { signed: true, decimals: pnlUnit === "POINTS" ? 2 : 0 })}</strong></div>
                ${oiBlock}
              </div>
            `;
          },
        },
        legend: {
          top: 4,
          right: 16,
          textStyle: { color: legendTextColor, fontSize: 11 },
          data: legendNames,
        },
        xAxis: {
          type: "value",
          scale: true,
          axisLine: { lineStyle: { color: axisLineColor } },
          axisLabel: {
            color: axisLabelColor,
            fontSize: 10,
            formatter: (v: number) => v.toFixed(0),
          },
          splitLine: { lineStyle: { color: splitLineColor } },
        },
        yAxis: [
          {
            type: "value",
            scale: true,
            axisLine: { lineStyle: { color: axisLineColor } },
            axisLabel: {
              color: axisLabelColor,
              fontSize: 10,
              formatter: (v: number) => {
                if (pnlUnit === "POINTS") return `${v.toFixed(0)} pt`;
                return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v.toFixed(0)}`;
              },
            },
            splitLine: { lineStyle: { color: splitLineColor } },
          },
          {
            type: "value",
            show: false,
            min: 0,
            max: maxVisibleOi * 2.6,
          },
        ],
        series,
      },
      { notMerge: true }
    );
  }, [
    evaluation,
    spot,
    targetSpot,
    theme,
    pnlUnit,
    lotSize,
    chartOverlays,
    strikes,
    rowsByStrike,
  ]);

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-[#111827] dark:shadow-lg">
      <MetricsRibbon
        evaluation={evaluation}
        realizedPnl={realizedPnl}
        margin={margin}
        isLoadingMargin={isLoadingMargin}
      />

      {/* Right-Panel Tabs + Chart Layer Overlay Checkboxes */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2 dark:border-slate-800">
        <div
          className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-800 dark:bg-[#0e1523]"
          role="tablist"
          aria-label="Strategy Analysis View"
        >
          {RIGHT_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={rightTab === t.key}
              onClick={() => setRightTab(t.key)}
              className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
                rightTab === t.key
                  ? "bg-white text-blue-700 shadow-sm dark:bg-blue-600 dark:text-white"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {rightTab === "graph" && (
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-700 dark:text-slate-300">
            {OVERLAY_OPTIONS.map((opt) => (
              <label key={opt.key} className="inline-flex cursor-pointer items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={chartOverlays[opt.key]}
                  onChange={() => toggleChartOverlay(opt.key)}
                  className="h-3.5 w-3.5 rounded border-slate-300 accent-blue-600 dark:border-slate-600"
                />
                <span>{opt.label}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {/* Tab 1: Interactive ECharts Payoff Graph */}
      <div
        className={
          rightTab === "graph"
            ? "rounded-lg border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-[#0b101b]"
            : "hidden"
        }
      >
        <div
          ref={chartContainerRef}
          aria-label="Strategy Payoff Graph"
          className="h-[340px] w-full"
        />
      </div>

      {/* Tab 2: Payoff Table (-5% to +5% in 0.5% steps + Current Spot + Breakevens) */}
      {rightTab === "table" && (
        <div className="terminal-scroll max-h-[360px] overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
            <thead className="sticky top-0 z-10 bg-slate-100 text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
              <tr>
                <th className="border-b border-slate-200 px-3 py-2 text-left dark:border-slate-800">
                  Target Spot
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-right dark:border-slate-800">
                  % Chg
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-right dark:border-slate-800">
                  Target Date P&amp;L ({pnlUnit === "POINTS" ? "Pts" : "₹"})
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-right dark:border-slate-800">
                  Expiry P&amp;L ({pnlUnit === "POINTS" ? "Pts" : "₹"})
                </th>
                <th className="border-b border-slate-200 px-3 py-2 text-right dark:border-slate-800">
                  Target Delta
                </th>
              </tr>
            </thead>
            <tbody>
              {payoffTableRows.map((row, idx) => {
                const highlight = row.isBreakeven
                  ? "bg-amber-50 dark:bg-amber-500/10"
                  : row.isCurrentSpot
                    ? "bg-blue-50 dark:bg-blue-500/10"
                    : "hover:bg-slate-50 dark:hover:bg-slate-800/30";
                return (
                  <tr
                    key={`${row.spot}-${idx}`}
                    className={`border-b border-slate-200 dark:border-slate-800/60 ${highlight}`}
                  >
                    <td className="px-3 py-1.5 font-mono font-semibold text-slate-900 dark:text-slate-100">
                      <div className="flex items-center gap-1.5">
                        <span>{row.spot.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                        {row.isCurrentSpot && (
                          <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-bold text-blue-700 dark:bg-blue-500/20 dark:text-blue-300">
                            SPOT
                          </span>
                        )}
                        {row.isBreakeven && (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold text-amber-800 dark:bg-amber-500/25 dark:text-amber-300">
                            BE
                          </span>
                        )}
                      </div>
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right font-mono ${
                        row.pctChange > 0
                          ? "text-[#16A34A] dark:text-emerald-400"
                          : row.pctChange < 0
                            ? "text-[#DC2626] dark:text-rose-400"
                            : "text-slate-600 dark:text-slate-400"
                      }`}
                    >
                      {row.pctChange > 0 ? "+" : ""}
                      {row.pctChange.toFixed(2)}%
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right font-mono font-semibold ${
                        row.targetPnl >= 0
                          ? "text-[#16A34A] dark:text-emerald-400"
                          : "text-[#DC2626] dark:text-rose-400"
                      }`}
                    >
                      {formatPnl(row.targetPnl, pnlUnit, lotSize, {
                        signed: true,
                        decimals: pnlUnit === "POINTS" ? 2 : 0,
                      })}
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right font-mono font-semibold ${
                        row.expiryPnl >= 0
                          ? "text-[#16A34A] dark:text-emerald-400"
                          : "text-[#DC2626] dark:text-rose-400"
                      }`}
                    >
                      {formatPnl(row.expiryPnl, pnlUnit, lotSize, {
                        signed: true,
                        decimals: pnlUnit === "POINTS" ? 2 : 0,
                      })}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">
                      {row.targetDelta.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 3: Per-Leg & Portfolio Greeks Breakdown */}
      {rightTab === "greeks" && (
        <div className="terminal-scroll max-h-[360px] overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
          {!greeksBreakdown || greeksBreakdown.rows.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-500 dark:text-slate-400">
              Add active legs to inspect per-leg and portfolio Greeks.
            </div>
          ) : (
            <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
              <thead className="sticky top-0 z-10 bg-slate-100 text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:bg-[#0d1422] dark:text-slate-400">
                <tr>
                  <th className="border-b border-slate-200 px-2.5 py-2 text-left dark:border-slate-800">
                    Leg
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    Qty
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    IV %
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    Unit Δ / Pos Δ
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    Unit Θ / Pos Θ
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    Unit Γ / Pos Γ
                  </th>
                  <th className="border-b border-slate-200 px-2 py-2 text-right dark:border-slate-800">
                    Unit V / Pos V
                  </th>
                </tr>
              </thead>
              <tbody>
                {greeksBreakdown.rows.map((gr) => (
                  <tr
                    key={gr.legId}
                    className="border-b border-slate-200 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:bg-slate-800/30"
                  >
                    <td className="px-2.5 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`rounded px-1 py-0.5 text-[10px] font-bold ${
                            gr.side === "BUY"
                              ? "bg-[#DCFCE7] text-[#15803D] dark:bg-emerald-600/25 dark:text-emerald-300"
                              : "bg-[#FEE2E2] text-[#B91C1C] dark:bg-rose-600/25 dark:text-rose-300"
                          }`}
                        >
                          {gr.side === "BUY" ? "B" : "S"}
                        </span>
                        <span className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                          {gr.label}
                        </span>
                        <span className="text-[10px] text-slate-500">
                          {formatShortExpiry(gr.expiry)}
                        </span>
                      </div>
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">
                      {gr.effectiveQty} ({gr.effectiveLots}L)
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-600 dark:text-slate-400">
                      {gr.ivPct.toFixed(1)}%
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">
                      <span className="text-slate-400">{gr.unitDelta.toFixed(2)} / </span>
                      <strong className="text-slate-900 dark:text-white">
                        {gr.posDelta.toFixed(1)}
                      </strong>
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono">
                      <span className="text-slate-400">{gr.unitTheta.toFixed(1)} / </span>
                      <strong
                        className={
                          gr.posTheta >= 0
                            ? "text-[#16A34A] dark:text-emerald-400"
                            : "text-[#DC2626] dark:text-rose-400"
                        }
                      >
                        {gr.posTheta >= 0 ? "+" : ""}
                        {gr.posTheta.toFixed(0)}
                      </strong>
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">
                      <span className="text-slate-400">{gr.unitGamma.toFixed(4)} / </span>
                      <strong className="text-slate-900 dark:text-white">
                        {gr.posGamma.toFixed(3)}
                      </strong>
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-700 dark:text-slate-300">
                      <span className="text-slate-400">{gr.unitVega.toFixed(1)} / </span>
                      <strong className="text-slate-900 dark:text-white">
                        {gr.posVega.toFixed(0)}
                      </strong>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="sticky bottom-0 bg-slate-100 font-mono font-bold text-slate-900 dark:bg-[#0d1422] dark:text-white">
                <tr>
                  <td colSpan={3} className="border-t border-slate-300 px-2.5 py-2 text-left dark:border-slate-700">
                    Portfolio Total
                  </td>
                  <td className="border-t border-slate-300 px-2 py-2 text-right dark:border-slate-700">
                    {greeksBreakdown.totals.delta.toFixed(1)}
                  </td>
                  <td
                    className={`border-t border-slate-300 px-2 py-2 text-right dark:border-slate-700 ${
                      greeksBreakdown.totals.theta >= 0
                        ? "text-[#16A34A] dark:text-emerald-400"
                        : "text-[#DC2626] dark:text-rose-400"
                    }`}
                  >
                    {greeksBreakdown.totals.theta >= 0 ? "+" : ""}
                    {greeksBreakdown.totals.theta.toFixed(0)}
                  </td>
                  <td className="border-t border-slate-300 px-2 py-2 text-right dark:border-slate-700">
                    {greeksBreakdown.totals.gamma.toFixed(3)}
                  </td>
                  <td className="border-t border-slate-300 px-2 py-2 text-right dark:border-slate-700">
                    {greeksBreakdown.totals.vega.toFixed(0)}
                  </td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}

      <WhatIfControls />
    </section>
  );
}
