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
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import {
  getDashboardOverview,
  type DashboardOverviewResponse,
  type AttentionProduct,
} from "@/lib/api";

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
   SKELETON PLACEHOLDER
   ═══════════════════════════════════════════════════════════════════════════ */

function SkeletonPulse({ width, height, borderRadius = 6 }: { width: string | number; height: string | number; borderRadius?: number }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius,
        background: `linear-gradient(90deg, ${T.textDim}22 25%, ${T.textDim}44 50%, ${T.textDim}22 75%)`,
        backgroundSize: "200% 100%",
        animation: "skeleton-pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}

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
  loading = false,
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
  loading?: boolean;
}) {
  const animated = useCountUp(loading ? 0 : value, 1400, decimals);

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

          {loading ? (
            <SkeletonPulse width={120} height={32} borderRadius={8} />
          ) : (
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{
                fontSize: 32, fontWeight: 600, color: T.text,
                fontFamily: T.fontMono, letterSpacing: "-0.02em", lineHeight: 1,
              }}>
                {decimals > 0 ? animated.toFixed(decimals) : animated.toLocaleString()}
                {suffix && <span style={{ fontSize: 18, color: T.textMuted, marginLeft: 2 }}>{suffix}</span>}
              </span>
              {trend !== undefined && trend !== 0 && (
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
          )}
        </div>

        {sparkData && !loading && (
          <div style={{ marginTop: 20, opacity: 0.7 }}>
            <Sparkline data={sparkData} color={accentColor} />
          </div>
        )}
        {!loading && children}
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

interface DistributionChartProps {
  distribution: { name: string; value: number; color: string; dimColor: string }[];
  loading?: boolean;
}

function DistributionChart({ distribution, loading = false }: DistributionChartProps) {
  const [ref, inView] = useInView(0.2);
  const [hoveredSlice, setHoveredSlice] = useState<number | null>(null);
  const total = distribution.reduce((s, d) => s + d.value, 0);

  return (
    <div ref={ref} style={{ ...glassCard, padding: "24px" }}>
      <div style={cardGlow(T.cyan)} />
      <h3 style={{
        fontSize: 13, fontWeight: 600, color: T.textMuted, fontFamily: T.fontSans,
        letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 24,
      }}>
        Price Position Distribution
      </h3>

      {loading ? (
        <div style={{ display: "flex", alignItems: "center", gap: 32, flexWrap: "wrap" }}>
          <SkeletonPulse width={200} height={200} borderRadius={100} />
          <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1, minWidth: 180 }}>
            {[1, 2, 3, 4].map((i) => (
              <SkeletonPulse key={i} width="100%" height={40} borderRadius={10} />
            ))}
          </div>
        </div>
      ) : total === 0 ? (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          padding: "40px 0", color: T.textMuted, fontFamily: T.fontSans, fontSize: 14,
        }}>
          <Package size={32} style={{ marginBottom: 12, opacity: 0.4 }} />
          <span>No products with competitor data yet</span>
          <span style={{ fontSize: 12, marginTop: 4 }}>Add competitor product mappings to see price positions</span>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 32, flexWrap: "wrap" }}>
          {/* Donut */}
          <div style={{ width: 200, height: 200, position: "relative", flexShrink: 0 }} onMouseLeave={() => setHoveredSlice(null)}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={distribution}
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
                  {distribution.map((entry, index) => (
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
          </div>

          {/* Legend */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1, minWidth: 180 }}>
            {distribution.map((entry, i) => {
              const pct = total > 0 ? ((entry.value / total) * 100).toFixed(1) : "0.0";
              const isActive = hoveredSlice === i;
              return (
                <div
                  key={entry.name}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "8px 12px",
                    borderRadius: 10, cursor: "pointer",
                    background: isActive ? entry.dimColor : "transparent",
                    border: `1px solid ${isActive ? entry.color + "33" : "transparent"}`,
                    transition: "all 0.2s",
                  }}
                  onMouseEnter={() => setHoveredSlice(i)}
                  onMouseLeave={() => setHoveredSlice(null)}
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
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TIME AGO HELPER
   ═══════════════════════════════════════════════════════════════════════════ */

function timeAgo(isoString: string | null): string {
  if (!isoString) return "—";
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  if (diffMs < 0) return "just now";

  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   ATTENTION TABLE
   ═══════════════════════════════════════════════════════════════════════════ */

interface AttentionTableProps {
  items: AttentionProduct[];
  loading?: boolean;
}

function AttentionTable({ items, loading = false }: AttentionTableProps) {
  const getSeverity = (ourPrice: number, competitorPrice: number) => {
    const gap = ((ourPrice - competitorPrice) / ourPrice) * 100;
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
            {loading ? "—" : `${items.length} items`}
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
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${T.border}` }}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} style={{ padding: "12px 16px" }}>
                      <SkeletonPulse width={j === 0 ? 140 : 70} height={16} />
                    </td>
                  ))}
                </tr>
              ))
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={7} style={{
                  padding: "32px 16px", textAlign: "center",
                  color: T.textMuted, fontFamily: T.fontSans, fontSize: 14,
                }}>
                  No products being undercut right now
                </td>
              </tr>
            ) : (
              items.map((item) => {
                const gap = ((item.our_price - item.competitor_price) / item.our_price) * 100;
                const severity = getSeverity(item.our_price, item.competitor_price);
                return (
                  <tr
                    key={`${item.product_id}-${item.competitor_name}`}
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
                        {item.title}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ fontSize: 13, fontFamily: T.fontMono, color: T.textMuted }}>
                        ${item.our_price.toFixed(2)}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ fontSize: 13, fontFamily: T.fontMono, fontWeight: 600, color: severity.color }}>
                        ${item.competitor_price.toFixed(2)}
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
                        {item.competitor_name}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ fontSize: 12, fontFamily: T.fontMono, color: T.textDim }}>
                        {timeAgo(item.last_changed)}
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
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {!loading && items.length > 0 && (
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
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ERROR BANNER
   ═══════════════════════════════════════════════════════════════════════════ */

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{
      ...glassCard,
      padding: "20px 24px",
      borderColor: T.red + "44",
      display: "flex",
      alignItems: "center",
      gap: 14,
      marginBottom: 20,
    }}>
      <div style={cardGlow(T.red)} />
      <AlertTriangle size={20} color={T.red} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <span style={{ fontSize: 13, color: T.text, fontFamily: T.fontSans }}>
          Failed to load dashboard data
        </span>
        <span style={{ fontSize: 12, color: T.textMuted, fontFamily: T.fontSans, marginLeft: 8 }}>
          {message}
        </span>
      </div>
      <button
        onClick={onRetry}
        style={{
          background: T.redDim,
          border: `1px solid ${T.red}33`,
          borderRadius: 8,
          padding: "6px 14px",
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          fontWeight: 600,
          color: T.red,
          fontFamily: T.fontSans,
          transition: "background 0.15s",
        }}
      >
        <RefreshCw size={12} /> Retry
      </button>
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
  const [data, setData] = useState<DashboardOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getDashboardOverview();
      setData(response);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Derive distribution data from API response
  const distribution = data
    ? [
        { name: "Cheapest", value: data.price_position.cheapest, color: T.green, dimColor: T.greenDim },
        { name: "Within 5%", value: data.price_position.within_5_pct, color: T.blue, dimColor: T.blueDim },
        { name: "Above Average", value: data.price_position.above_average, color: T.amber, dimColor: T.amberDim },
        { name: "Most Expensive", value: data.price_position.most_expensive, color: T.red, dimColor: T.redDim },
      ]
    : [
        { name: "Cheapest", value: 0, color: T.green, dimColor: T.greenDim },
        { name: "Within 5%", value: 0, color: T.blue, dimColor: T.blueDim },
        { name: "Above Average", value: 0, color: T.amber, dimColor: T.amberDim },
        { name: "Most Expensive", value: 0, color: T.red, dimColor: T.redDim },
      ];

  const summary = data?.summary;
  const scrapingHealth = summary?.scraping_health_pct ?? 0;
  const healthColor = scrapingHealth >= 90 ? T.green : scrapingHealth >= 70 ? T.amber : T.red;

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
        @keyframes skeleton-pulse {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
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

      {/* Error banner */}
      {error && <ErrorBanner message={error} onRetry={fetchData} />}

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
          value={summary?.products_tracked ?? 0}
          trend={summary?.products_trend_pct}
          accentColor={T.cyan}
          loading={loading}
        />
        <StatCard
          icon={Users}
          label="Competitors"
          value={summary?.competitors_monitored ?? 0}
          accentColor={T.blue}
          loading={loading}
        />
        <StatCard
          icon={TrendingDown}
          label="Price Changes 24h"
          value={summary?.price_changes_24h ?? 0}
          accentColor={T.amber}
          loading={loading}
        />
        <StatCard
          icon={Activity}
          label="Scraping Health"
          value={scrapingHealth}
          decimals={1}
          suffix="%"
          accentColor={healthColor}
          loading={loading}
        >
          <HealthRing value={scrapingHealth} />
        </StatCard>
      </div>

      {/* ── Main Content Grid ──────────────────────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr",
        gap: 20,
      }}>
        {/* Distribution Chart */}
        <DistributionChart distribution={distribution} loading={loading} />

        {/* Attention Table */}
        <AttentionTable items={data?.attention_products ?? []} loading={loading} />
      </div>
    </div>
  );
}

export default PricePositionOverview;
