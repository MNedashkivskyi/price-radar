"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from "recharts";
import {
  Package,
  Users,
  TrendingDown,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  Eye,
} from "lucide-react";

/* ═══════════════════════════════════════════════════════════════════════════
   DESIGN TOKENS
   ═══════════════════════════════════════════════════════════════════════════ */

const T = {
  bg: "#0A0C10",
  bgCard: "rgba(17, 19, 28, 0.65)",
  bgCardHover: "rgba(22, 25, 38, 0.8)",
  border: "rgba(45, 55, 80, 0.45)",
  borderHover: "rgba(55, 70, 100, 0.6)",
  borderAccent: "rgba(0, 210, 211, 0.25)",
  cyan: "#00D2D3",
  cyanGlow: "0 0 20px rgba(0, 210, 211, 0.15)",
  green: "#00E676",
  greenDim: "rgba(0, 230, 118, 0.12)",
  amber: "#FFB020",
  amberDim: "rgba(255, 176, 32, 0.12)",
  red: "#FF5252",
  redDim: "rgba(255, 82, 82, 0.12)",
  blue: "#448AFF",
  blueDim: "rgba(68, 138, 255, 0.12)",
  text: "#E8ECF4",
  textMuted: "#6B7A99",
  textDim: "#3D4A63",
  fontMono: "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace",
  fontSans: "'Geist', 'Syne', system-ui, -apple-system, sans-serif",
} as const;

/* ═══════════════════════════════════════════════════════════════════════════
   MOCK DATA
   ═══════════════════════════════════════════════════════════════════════════ */

const MOCK_SUMMARY = {
  productsTracked: 1284,
  productsTrend: 3.2,
  competitorsMonitored: 47,
  priceChanges24h: 89,
  scrapingHealth: 94.6,
};

const MOCK_DISTRIBUTION = [
  { name: "Cheapest", value: 312, color: T.green, dimColor: T.greenDim },
  { name: "Within 5%", value: 487, color: T.blue, dimColor: T.blueDim },
  { name: "Above Average", value: 298, color: T.amber, dimColor: T.amberDim },
  { name: "Most Expensive", value: 187, color: T.red, dimColor: T.redDim },
];

// Precompute slice mid-angles (degrees, Recharts convention: 0°=3-o'clock, counter-clockwise)
const DISTRIBUTION_TOTAL = MOCK_DISTRIBUTION.reduce((s, d) => s + d.value, 0);
const SLICE_MID_ANGLES: number[] = (() => {
  let cum = 0;
  return MOCK_DISTRIBUTION.map((d) => {
    const span = (d.value / DISTRIBUTION_TOTAL) * 360;
    const mid = cum + span / 2;
    cum += span;
    return mid;
  });
})();

const MOCK_ATTENTION_ITEMS = [
  { id: 1, product: "Sony WH-1000XM5", yourPrice: 348.00, lowestPrice: 289.99, competitorName: "BestDeal Co", timeAgo: "12m ago" },
  { id: 2, product: "Apple AirPods Pro 2", yourPrice: 249.00, lowestPrice: 219.95, competitorName: "TechStore", timeAgo: "34m ago" },
  { id: 3, product: "Nike Air Max 90", yourPrice: 129.99, lowestPrice: 109.99, competitorName: "ShoeWars", timeAgo: "1h ago" },
  { id: 4, product: "Dyson V15 Detect", yourPrice: 749.99, lowestPrice: 649.00, competitorName: "CleanDeals", timeAgo: "2h ago" },
  { id: 5, product: "Samsung Galaxy S24", yourPrice: 799.99, lowestPrice: 749.99, competitorName: "MobileHub", timeAgo: "2h ago" },
  { id: 6, product: "Bose QC Ultra", yourPrice: 429.00, lowestPrice: 379.99, competitorName: "AudioZone", timeAgo: "3h ago" },
  { id: 7, product: "iPad Air M2", yourPrice: 599.00, lowestPrice: 549.00, competitorName: "TechStore", timeAgo: "4h ago" },
  { id: 8, product: "Lego Technic Ferrari", yourPrice: 449.99, lowestPrice: 429.99, competitorName: "ToyWorld", timeAgo: "5h ago" },
];

/* ═══════════════════════════════════════════════════════════════════════════
   HOOKS
   ═══════════════════════════════════════════════════════════════════════════ */

function useCountUp(target: number, duration = 1200, decimals = 0): number {
  const [value, setValue] = useState(0);
  const startTime = useRef<number | null>(null);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    startTime.current = null;
    const animate = (timestamp: number) => {
      if (startTime.current === null) startTime.current = timestamp;
      const progress = Math.min((timestamp - startTime.current) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Number((eased * target).toFixed(decimals)));
      if (progress < 1) frameRef.current = requestAnimationFrame(animate);
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, duration, decimals]);

  return value;
}

function useInView(threshold = 0.1): [React.RefCallback<HTMLDivElement>, boolean] {
  const [inView, setInView] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const refCallback = useCallback(
    (node: HTMLDivElement | null) => {
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
      if (node) {
        const obs = new IntersectionObserver(
          ([e]) => { if (e.isIntersecting) setInView(true); },
          { threshold },
        );
        obs.observe(node);
        observerRef.current = obs;
      }
    },
    [threshold],
  );

  return [refCallback, inView];
}

/* ═══════════════════════════════════════════════════════════════════════════
   SHARED STYLES
   ═══════════════════════════════════════════════════════════════════════════ */

const glassCard: React.CSSProperties = {
  background: T.bgCard,
  border: `1px solid ${T.border}`,
  borderRadius: 14,
  backdropFilter: "blur(20px)",
  WebkitBackdropFilter: "blur(20px)",
  position: "relative",
  overflow: "hidden",
};

const cardGlow = (color: string): React.CSSProperties => ({
  content: '""',
  position: "absolute",
  top: -1,
  left: -1,
  right: -1,
  height: 1,
  background: `linear-gradient(90deg, transparent 0%, ${color} 50%, transparent 100%)`,
  opacity: 0.5,
});

/* ═══════════════════════════════════════════════════════════════════════════
   MINI SPARKLINE
   ═══════════════════════════════════════════════════════════════════════════ */

function Sparkline({ data, color, width = 64, height = 24 }: { data: number[]; color: string; width?: number; height?: number }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data
    .map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * height}`)
    .join(" ");
  return (
    <svg width={width} height={height} style={{ overflow: "visible" }}>
      <polyline
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   STAT CARD
   ═══════════════════════════════════════════════════════════════════════════ */

function StatCard({
  icon: Icon,
  label,
  value,
  decimals = 0,
  suffix = "",
  trend,
  accentColor,
  sparkData,
  children,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
  decimals?: number;
  suffix?: string;
  trend?: number;
  accentColor: string;
  sparkData?: number[];
  children?: React.ReactNode;
}) {
  const animated = useCountUp(value, 1400, decimals);

  return (
    <div style={{ ...glassCard, padding: "20px 22px", transition: "border-color 0.25s" }}
         onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = accentColor + "55"; }}
         onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = T.border; }}>
      {/* Top glow line */}
      <div style={cardGlow(accentColor)} />

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <div style={{
              width: 30, height: 30, borderRadius: 8,
              background: accentColor + "14",
              border: `1px solid ${accentColor}22`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Icon size={14} color={accentColor} />
            </div>
            <span style={{
              fontSize: 12, fontWeight: 500, color: T.textMuted,
              fontFamily: T.fontSans, letterSpacing: "0.04em", textTransform: "uppercase",
            }}>
              {label}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{
              fontSize: 32, fontWeight: 600, color: T.text,
              fontFamily: T.fontMono, letterSpacing: "-0.02em", lineHeight: 1,
            }}>
              {decimals > 0 ? animated.toFixed(decimals) : animated.toLocaleString()}
              {suffix && <span style={{ fontSize: 18, color: T.textMuted, marginLeft: 2 }}>{suffix}</span>}
            </span>
            {trend !== undefined && (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 2,
                fontSize: 12, fontFamily: T.fontMono, fontWeight: 500,
                color: trend >= 0 ? T.green : T.red,
                background: trend >= 0 ? T.greenDim : T.redDim,
                padding: "2px 7px", borderRadius: 6,
              }}>
                {trend >= 0 ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                {Math.abs(trend)}%
              </span>
            )}
          </div>
        </div>

        {sparkData && (
          <div style={{ marginTop: 20, opacity: 0.7 }}>
            <Sparkline data={sparkData} color={accentColor} />
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SCRAPING HEALTH RING
   ═══════════════════════════════════════════════════════════════════════════ */

function HealthRing({ value }: { value: number }) {
  const animated = useCountUp(value, 1600, 1);
  const color = value >= 90 ? T.green : value >= 70 ? T.amber : T.red;
  const circumference = 2 * Math.PI * 28;
  const offset = circumference - (animated / 100) * circumference;

  return (
    <div style={{ position: "relative", width: 68, height: 68, marginTop: 4 }}>
      {/* Pulse glow */}
      <div style={{
        position: "absolute", inset: -4, borderRadius: "50%",
        background: `radial-gradient(circle, ${color}18 0%, transparent 70%)`,
        animation: "pulse-ring 2.5s ease-in-out infinite",
      }} />
      <svg width={68} height={68} style={{ transform: "rotate(-90deg)" }}>
        {/* Track */}
        <circle cx={34} cy={34} r={28} fill="none"
          stroke={T.textDim} strokeWidth={3.5} opacity={0.3} />
        {/* Value */}
        <circle cx={34} cy={34} r={28} fill="none"
          stroke={color} strokeWidth={3.5}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{
            transition: "stroke-dashoffset 1.6s cubic-bezier(0.16, 1, 0.3, 1)",
            filter: `drop-shadow(0 0 6px ${color}88)`,
          }}
        />
      </svg>
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <span style={{
          fontSize: 15, fontWeight: 600, fontFamily: T.fontMono,
          color, letterSpacing: "-0.02em",
        }}>
          {animated.toFixed(1)}
        </span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DISTRIBUTION CHART (Donut Ring)
   ═══════════════════════════════════════════════════════════════════════════ */

function DistributionChart() {
  const [ref, inView] = useInView(0.2);
  const [hoveredSlice, setHoveredSlice] = useState<number | null>(null);
  const total = DISTRIBUTION_TOTAL;

  return (
    <div ref={ref} style={{ ...glassCard, padding: "24px", overflow: "visible" }}>
      <div style={cardGlow(T.cyan)} />
      <h3 style={{
        fontSize: 13, fontWeight: 600, color: T.textMuted, fontFamily: T.fontSans,
        letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 24,
      }}>
        Price Position Distribution
      </h3>

      <div style={{ display: "flex", alignItems: "center", gap: 32, flexWrap: "wrap" }}>
        {/* Donut */}
        <div style={{ width: 200, height: 200, position: "relative", flexShrink: 0 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={MOCK_DISTRIBUTION}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={85}
                paddingAngle={3}
                dataKey="value"
                animationBegin={inView ? 0 : 99999}
                animationDuration={1200}
                animationEasing="ease-out"
                onMouseEnter={(_, index) => setHoveredSlice(index)}
                onMouseLeave={() => setHoveredSlice(null)}
                stroke="none"
              >
                {MOCK_DISTRIBUTION.map((entry, index) => (
                  <Cell
                    key={entry.name}
                    fill={entry.color}
                    opacity={hoveredSlice === null || hoveredSlice === index ? 1 : 0.35}
                    style={{
                      filter: hoveredSlice === index ? `drop-shadow(0 0 8px ${entry.color}88)` : "none",
                      transition: "opacity 0.2s, filter 0.2s",
                      cursor: "pointer",
                    }}
                  />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          {/* Centre label */}
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
            pointerEvents: "none",
          }}>
            <span style={{ fontSize: 28, fontWeight: 700, fontFamily: T.fontMono, color: T.text }}>
              {total.toLocaleString()}
            </span>
            <span style={{ fontSize: 11, color: T.textMuted, fontFamily: T.fontSans }}>
              products
            </span>
          </div>
          {/* Custom tooltip — positioned outward from donut center */}
          {hoveredSlice !== null && (() => {
            const entry = MOCK_DISTRIBUTION[hoveredSlice];
            const midDeg = SLICE_MID_ANGLES[hoveredSlice];
            const midRad = (midDeg * Math.PI) / 180;
            const cos = Math.cos(midRad);
            const sin = Math.sin(midRad);
            const dist = 85 + 8; // outerRadius + 8px offset (close to donut edge)
            const cx = 100, cy = 100;
            const tx = cx + dist * cos;
            const ty = cy - dist * sin;
            // Anchor the tooltip edge closest to center so it extends outward
            const translateX = `${(-50) * (1 - cos)}%`;
            const translateY = `${(-50) * (1 + sin)}%`;
            return (
              <div style={{
                position: "absolute",
                left: tx,
                top: ty,
                transform: `translate(${translateX}, ${translateY})`,
                ...glassCard,
                padding: "10px 14px",
                boxShadow: `0 8px 32px rgba(0,0,0,0.5), ${T.cyanGlow}`,
                pointerEvents: "none",
                zIndex: 10,
                whiteSpace: "nowrap",
              }}>
                <div style={{ fontSize: 12, fontFamily: T.fontSans, color: T.textMuted, marginBottom: 4 }}>{entry.name}</div>
                <div style={{ fontSize: 18, fontFamily: T.fontMono, fontWeight: 600, color: entry.color }}>
                  {entry.value} <span style={{ fontSize: 12, color: T.textMuted }}>({((entry.value / total) * 100).toFixed(1)}%)</span>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Legend */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1, minWidth: 180 }}>
          {MOCK_DISTRIBUTION.map((entry, i) => {
            const pct = ((entry.value / total) * 100).toFixed(1);
            return (
              <div
                key={entry.name}
                className="distribution-legend-item"
                style={{
                  "--legend-dim-color": entry.dimColor,
                  "--legend-border-color": entry.color + "33",
                  display: "flex", alignItems: "center", gap: 12, padding: "8px 12px",
                  borderRadius: 10, cursor: "pointer",
                  background: "transparent",
                  border: "1px solid transparent",
                  transition: "all 0.2s",
                } as React.CSSProperties}
              >
                <div style={{
                  width: 10, height: 10, borderRadius: 3,
                  background: entry.color,
                  boxShadow: `0 0 6px ${entry.color}66`,
                  flexShrink: 0,
                }} />
                <span style={{ fontSize: 13, color: T.text, fontFamily: T.fontSans, flex: 1 }}>
                  {entry.name}
                </span>
                <span style={{ fontSize: 14, fontFamily: T.fontMono, fontWeight: 600, color: entry.color }}>
                  {entry.value}
                </span>
                <span style={{ fontSize: 11, fontFamily: T.fontMono, color: T.textMuted, width: 45, textAlign: "right" }}>
                  {pct}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ATTENTION TABLE
   ═══════════════════════════════════════════════════════════════════════════ */

function AttentionTable() {
  const getSeverity = (yourPrice: number, lowestPrice: number) => {
    const gap = ((yourPrice - lowestPrice) / yourPrice) * 100;
    if (gap > 10) return { color: T.red, bg: T.redDim, label: "Critical" };
    if (gap > 5) return { color: T.amber, bg: T.amberDim, label: "Warning" };
    return { color: "#EAB308", bg: "rgba(234, 179, 8, 0.10)", label: "Minor" };
  };

  return (
    <div style={{ ...glassCard, padding: 0, overflow: "hidden" }}>
      <div style={cardGlow(T.amber)} />

      <div style={{ padding: "20px 24px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{
            fontSize: 13, fontWeight: 600, color: T.textMuted, fontFamily: T.fontSans,
            letterSpacing: "0.06em", textTransform: "uppercase",
          }}>
            Products Needing Attention
          </h3>
          <span style={{
            fontSize: 11, fontFamily: T.fontMono, color: T.amber,
            background: T.amberDim, padding: "3px 10px", borderRadius: 6,
          }}>
            {MOCK_ATTENTION_ITEMS.length} items
          </span>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 680 }}>
          <thead>
            <tr style={{ borderTop: `1px solid ${T.border}` }}>
              {["Product", "Your Price", "Lowest", "Gap", "Competitor", "Changed"].map((h) => (
                <th key={h} style={{
                  padding: "10px 16px", textAlign: "left", fontSize: 11,
                  fontWeight: 600, color: T.textDim, fontFamily: T.fontSans,
                  letterSpacing: "0.05em", textTransform: "uppercase",
                  borderBottom: `1px solid ${T.border}`,
                }}>
                  {h}
                </th>
              ))}
              <th style={{ width: 48, borderBottom: `1px solid ${T.border}` }} />
            </tr>
          </thead>
          <tbody>
            {MOCK_ATTENTION_ITEMS.map((item) => {
              const gap = ((item.yourPrice - item.lowestPrice) / item.yourPrice) * 100;
              const severity = getSeverity(item.yourPrice, item.lowestPrice);
              return (
                <tr
                  key={item.id}
                  className="attention-row"
                  style={{
                    borderBottom: `1px solid ${T.border}`,
                    background: "transparent",
                    transition: "background 0.15s",
                    cursor: "pointer",
                  }}
                >
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ fontSize: 13, fontWeight: 500, color: T.text, fontFamily: T.fontSans }}>
                      {item.product}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ fontSize: 13, fontFamily: T.fontMono, color: T.textMuted }}>
                      ${item.yourPrice.toFixed(2)}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ fontSize: 13, fontFamily: T.fontMono, fontWeight: 600, color: severity.color }}>
                      ${item.lowestPrice.toFixed(2)}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 3,
                      fontSize: 12, fontFamily: T.fontMono, fontWeight: 600,
                      color: severity.color, background: severity.bg,
                      padding: "3px 9px", borderRadius: 6,
                    }}>
                      <TrendingDown size={11} />
                      {gap.toFixed(1)}%
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ fontSize: 12, color: T.textMuted, fontFamily: T.fontSans }}>
                      {item.competitorName}
                    </span>
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <span style={{ fontSize: 12, fontFamily: T.fontMono, color: T.textDim }}>
                      {item.timeAgo}
                    </span>
                  </td>
                  <td style={{ padding: "12px 8px", textAlign: "center" }}>
                    <button
                      className="attention-review-btn"
                      style={{
                        opacity: 0,
                        transform: "translateX(-4px)",
                        transition: "all 0.2s",
                        background: T.cyan + "14",
                        border: `1px solid ${T.cyan}33`,
                        borderRadius: 7,
                        padding: "5px 10px",
                        cursor: "pointer",
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 11, fontWeight: 600, color: T.cyan,
                        fontFamily: T.fontSans,
                      }}
                    >
                      <Eye size={11} /> Review
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div style={{
        padding: "14px 24px", borderTop: `1px solid ${T.border}`,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <button style={{
          background: "none", border: "none", cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 6,
          fontSize: 12, fontWeight: 600, color: T.cyan, fontFamily: T.fontSans,
          padding: "4px 12px", borderRadius: 6,
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = T.cyan + "14"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "none"; }}>
          View All Undercut Products <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   LIVE INDICATOR
   ═══════════════════════════════════════════════════════════════════════════ */

function LiveDot() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: T.green,
        boxShadow: `0 0 8px ${T.green}88`,
        animation: "pulse-dot 2s ease-in-out infinite",
      }} />
      <span style={{ fontSize: 11, fontFamily: T.fontMono, color: T.green, fontWeight: 500 }}>
        LIVE
      </span>
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN DASHBOARD COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */

export function PricePositionOverview() {
  return (
    <div style={{ fontFamily: T.fontSans }}>
      {/* CSS Animations */}
      <style>{`
        @keyframes pulse-ring {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.08); }
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }

        /* Distribution legend hover via CSS to avoid stuck JS state */
        .distribution-legend-item:hover {
          background: var(--legend-dim-color) !important;
          border-color: var(--legend-border-color) !important;
        }

        /* Attention table hover via CSS to avoid stuck JS state */
        .attention-row:hover {
          background: ${T.bgCardHover} !important;
        }
        .attention-row:hover .attention-review-btn {
          opacity: 1 !important;
          transform: translateX(0) !important;
        }
      `}</style>

      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 24, flexWrap: "wrap", gap: 12,
      }}>
        <div>
          <h1 style={{
            fontSize: 22, fontWeight: 700, color: T.text,
            fontFamily: T.fontSans, letterSpacing: "-0.01em", margin: 0,
          }}>
            Price Position Overview
          </h1>
          <p style={{
            fontSize: 13, color: T.textMuted, fontFamily: T.fontSans,
            margin: "4px 0 0",
          }}>
            Real-time competitive intelligence across your catalog
          </p>
        </div>
        <LiveDot />
      </div>

      {/* ── Summary Stats ──────────────────────────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
        gap: 14,
        marginBottom: 20,
      }}>
        <StatCard
          icon={Package}
          label="Products Tracked"
          value={MOCK_SUMMARY.productsTracked}
          trend={MOCK_SUMMARY.productsTrend}
          accentColor={T.cyan}
          sparkData={[820, 910, 980, 1050, 1120, 1180, 1220, 1284]}
        />
        <StatCard
          icon={Users}
          label="Competitors"
          value={MOCK_SUMMARY.competitorsMonitored}
          accentColor={T.blue}
          sparkData={[30, 33, 35, 38, 40, 42, 45, 47]}
        />
        <StatCard
          icon={TrendingDown}
          label="Price Changes 24h"
          value={MOCK_SUMMARY.priceChanges24h}
          accentColor={T.amber}
          sparkData={[45, 62, 38, 71, 55, 68, 92, 89]}
        />
        <StatCard
          icon={Activity}
          label="Scraping Health"
          value={MOCK_SUMMARY.scrapingHealth}
          decimals={1}
          suffix="%"
          accentColor={MOCK_SUMMARY.scrapingHealth >= 90 ? T.green : MOCK_SUMMARY.scrapingHealth >= 70 ? T.amber : T.red}
        >
          <HealthRing value={MOCK_SUMMARY.scrapingHealth} />
        </StatCard>
      </div>

      {/* ── Main Content Grid ──────────────────────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr",
        gap: 20,
      }}>
        {/* Distribution Chart */}
        <DistributionChart />

        {/* Attention Table */}
        <AttentionTable />
      </div>
    </div>
  );
}

export default PricePositionOverview;
