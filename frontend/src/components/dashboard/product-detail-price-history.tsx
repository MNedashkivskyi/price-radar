"use client";

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceDot,
} from "recharts";
import {
  ArrowUpRight,
  ArrowDownRight,
  ArrowLeft,
  Clock,
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  ChevronDown,
  Circle,
  ExternalLink,
  RefreshCw,
} from "lucide-react";

/* ═══════════════════════════════════════════════════════════════════════════
   DESIGN TOKENS
   ═══════════════════════════════════════════════════════════════════════════ */

const T = {
  bg: "#090B0F",
  bgPanel: "#0F1318",
  bgPanelHover: "#151A21",
  bgRow: "rgba(255,255,255,0.015)",
  border: "rgba(255,255,255,0.06)",
  borderHover: "rgba(255,255,255,0.12)",
  // Accent
  cyan: "#00D4FF",
  cyanDim: "rgba(0,212,255,0.10)",
  cyanGlow: "0 0 20px rgba(0,212,255,0.25)",
  // Competitor palette
  slate: "#6C8EBF",
  amber: "#E8A838",
  coral: "#E06C75",
  mint: "#98C379",
  lavender: "#C678DD",
  // Semantic
  green: "#00E676",
  greenDim: "rgba(0,230,118,0.12)",
  amberAlert: "#FFB020",
  amberDim: "rgba(255,176,32,0.12)",
  red: "#FF5252",
  redDim: "rgba(255,82,82,0.12)",
  gray: "#6B7A99",
  // Text
  text: "#E8ECF4",
  textMuted: "#6B7A99",
  textDim: "#3D4A63",
  // Fonts
  fontMono: "'JetBrains Mono', 'Fira Code', ui-monospace, monospace",
  fontSans: "'DM Sans', 'Geist', system-ui, -apple-system, sans-serif",
} as const;

const COMPETITOR_COLORS = [T.slate, T.amber, T.coral, T.mint, T.lavender];

/* ═══════════════════════════════════════════════════════════════════════════
   CURRENCY & TIME FORMATTING
   ═══════════════════════════════════════════════════════════════════════════ */

const fmtCurrency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function fmtPrice(v: number): string {
  return fmtCurrency.format(v);
}

function relativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   MOCK DATA GENERATION
   ═══════════════════════════════════════════════════════════════════════════ */

interface PricePoint {
  date: string;        // "YYYY-MM-DD"
  dateMs: number;
  yourPrice: number;
  [key: string]: number | string;
}

interface Competitor {
  id: string;
  name: string;
  color: string;
  currentPrice: number;
  stockStatus: "in_stock" | "low_stock" | "out_of_stock" | "unknown";
  lastUpdated: Date;
}

const COMPETITORS: Competitor[] = [
  { id: "comp_a", name: "TechDirect Pro", color: T.slate, currentPrice: 117.49, stockStatus: "in_stock", lastUpdated: new Date(Date.now() - 14 * 60000) },
  { id: "comp_b", name: "PriceWars Global", color: T.amber, currentPrice: 134.99, stockStatus: "in_stock", lastUpdated: new Date(Date.now() - 2 * 3600000) },
  { id: "comp_c", name: "BargainBay", color: T.coral, currentPrice: 122.50, stockStatus: "low_stock", lastUpdated: new Date(Date.now() - 38 * 60000) },
  { id: "comp_d", name: "MegaShop Direct", color: T.mint, currentPrice: 141.00, stockStatus: "out_of_stock", lastUpdated: new Date(Date.now() - 5 * 3600000) },
];

const YOUR_CURRENT_PRICE = 127.99;
const YOUR_PRICE_30D_AGO = 124.99;

function generateMockData(): PricePoint[] {
  const data: PricePoint[] = [];
  const now = new Date();
  const startDate = new Date(now);
  startDate.setDate(startDate.getDate() - 90);

  // Seed-based pseudo-random for reproducible data
  let seed = 42;
  const rand = () => {
    seed = (seed * 16807 + 0) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  // Your price: starts at 119.99, step up to 124.99 on day ~30, step up to 127.99 on day ~65
  const yourPriceSteps = [
    { until: 30, price: 119.99 },
    { until: 65, price: 124.99 },
    { until: 999, price: 127.99 },
  ];

  // Competitor base prices with organic drift
  const compBases = [
    { base: 115.00, volatility: 0.04 },   // TechDirect Pro - cheapest, steady
    { base: 130.00, volatility: 0.06 },   // PriceWars Global - higher, volatile
    { base: 118.00, volatility: 0.05 },   // BargainBay - competitive
    { base: 138.00, volatility: 0.03 },   // MegaShop Direct - premium
  ];

  const compPrices = compBases.map(c => c.base);

  for (let day = 0; day <= 90; day++) {
    const date = new Date(startDate);
    date.setDate(date.getDate() + day);
    const dateStr = date.toISOString().split("T")[0];

    // Your price (step function)
    const yourStep = yourPriceSteps.find(s => day < s.until) || yourPriceSteps[yourPriceSteps.length - 1];

    // Competitor prices: organic random walk with mean-reversion
    const point: PricePoint = {
      date: dateStr,
      dateMs: date.getTime(),
      yourPrice: yourStep.price,
    };

    COMPETITORS.forEach((comp, i) => {
      const drift = (compBases[i].base - compPrices[i]) * 0.05; // mean reversion
      const noise = (rand() - 0.5) * 2 * compBases[i].base * compBases[i].volatility;
      // Occasional larger moves (10% chance)
      const bigMove = rand() < 0.10 ? (rand() - 0.5) * compBases[i].base * 0.12 : 0;
      compPrices[i] = Math.max(
        compBases[i].base * 0.85,
        Math.min(compBases[i].base * 1.15, compPrices[i] + drift + noise + bigMove)
      );
      point[comp.id] = Math.round(compPrices[i] * 100) / 100;
    });

    data.push(point);
  }

  // Update competitor current prices to match final day
  const lastPoint = data[data.length - 1];
  COMPETITORS[0].currentPrice = lastPoint[COMPETITORS[0].id] as number;
  COMPETITORS[1].currentPrice = lastPoint[COMPETITORS[1].id] as number;
  COMPETITORS[2].currentPrice = lastPoint[COMPETITORS[2].id] as number;
  COMPETITORS[3].currentPrice = lastPoint[COMPETITORS[3].id] as number;

  return data;
}

const MOCK_PRICE_DATA = generateMockData();

// Find your price change events (days where price changed from previous)
const YOUR_PRICE_CHANGE_DAYS: number[] = [];
for (let i = 1; i < MOCK_PRICE_DATA.length; i++) {
  if (MOCK_PRICE_DATA[i].yourPrice !== MOCK_PRICE_DATA[i - 1].yourPrice) {
    YOUR_PRICE_CHANGE_DAYS.push(i);
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   PRODUCT METADATA
   ═══════════════════════════════════════════════════════════════════════════ */

const PRODUCT = {
  name: "Sony WH-1000XM5 Wireless Headphones",
  sku: "SKU-WH1000XM5-BLK",
  category: ["Electronics", "Audio", "Headphones"],
  lastScraped: new Date(Date.now() - 4 * 60000),
};

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

/* ═══════════════════════════════════════════════════════════════════════════
   SHARED STYLES
   ═══════════════════════════════════════════════════════════════════════════ */

const panelStyle: React.CSSProperties = {
  background: T.bgPanel,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  position: "relative",
  overflow: "hidden",
};

const topGlow = (color: string): React.CSSProperties => ({
  position: "absolute",
  top: -1,
  left: -1,
  right: -1,
  height: 1,
  background: `linear-gradient(90deg, transparent 0%, ${color} 50%, transparent 100%)`,
  opacity: 0.4,
  pointerEvents: "none",
});

/* ═══════════════════════════════════════════════════════════════════════════
   SKELETON / SHIMMER
   ═══════════════════════════════════════════════════════════════════════════ */

function Skeleton({ width, height = 16 }: { width: number | string; height?: number }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 6,
        background: `linear-gradient(90deg, ${T.bgPanel} 0%, rgba(255,255,255,0.04) 50%, ${T.bgPanel} 100%)`,
        backgroundSize: "200% 100%",
        animation: "shimmer 1.5s ease-in-out infinite",
      }}
    />
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   STATUS BADGES
   ═══════════════════════════════════════════════════════════════════════════ */

function TrackingBadge() {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        fontFamily: T.fontSans,
        fontWeight: 500,
        color: T.green,
        background: T.greenDim,
        padding: "4px 12px",
        borderRadius: 20,
        border: `1px solid rgba(0,230,118,0.2)`,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: T.green,
          boxShadow: `0 0 8px ${T.green}88`,
          animation: "pulse-dot 2s ease-in-out infinite",
        }}
      />
      Tracking Active
    </span>
  );
}

type PositionType = "most_expensive" | "competitive" | "price_leader";

function PositionBadge({ position }: { position: PositionType }) {
  const config = {
    most_expensive: { label: "Most Expensive", color: T.red, bg: T.redDim },
    competitive: { label: "Competitive", color: T.amberAlert, bg: T.amberDim },
    price_leader: { label: "Price Leader", color: T.green, bg: T.greenDim },
  };
  const c = config[position];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        fontFamily: T.fontSans,
        fontWeight: 500,
        color: c.color,
        background: c.bg,
        padding: "4px 12px",
        borderRadius: 20,
        border: `1px solid ${c.color}33`,
      }}
    >
      <Circle size={6} fill={c.color} stroke="none" />
      {c.label}
    </span>
  );
}

function StockBadge({ status }: { status: Competitor["stockStatus"] }) {
  const config = {
    in_stock: { label: "In Stock", color: T.green },
    low_stock: { label: "Low Stock", color: T.amberAlert },
    out_of_stock: { label: "Out of Stock", color: T.red },
    unknown: { label: "Unknown", color: T.gray },
  };
  const c = config[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 11,
        fontFamily: T.fontSans,
        fontWeight: 500,
        color: c.color,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: c.color,
          boxShadow: `0 0 4px ${c.color}66`,
          flexShrink: 0,
        }}
      />
      {c.label}
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DATE RANGE PILLS
   ═══════════════════════════════════════════════════════════════════════════ */

type DateRange = "7D" | "30D" | "60D" | "90D";

function DateRangePills({
  selected,
  onChange,
}: {
  selected: DateRange;
  onChange: (r: DateRange) => void;
}) {
  const ranges: DateRange[] = ["7D", "30D", "60D", "90D"];
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: "rgba(255,255,255,0.03)",
        borderRadius: 8,
        padding: 2,
        border: `1px solid ${T.border}`,
      }}
    >
      {ranges.map((r) => {
        const isActive = r === selected;
        return (
          <button
            key={r}
            onClick={() => onChange(r)}
            style={{
              padding: "5px 14px",
              borderRadius: 6,
              border: "none",
              cursor: "pointer",
              fontSize: 12,
              fontFamily: T.fontMono,
              fontWeight: 600,
              letterSpacing: "0.02em",
              transition: "all 0.2s",
              background: isActive ? T.cyan : "transparent",
              color: isActive ? T.bg : T.textMuted,
              boxShadow: isActive ? `0 0 12px ${T.cyan}44` : "none",
            }}
            onMouseEnter={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLElement).style.color = T.text;
                (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.06)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLElement).style.color = T.textMuted;
                (e.currentTarget as HTMLElement).style.background = "transparent";
              }
            }}
          >
            {r}
          </button>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CUSTOM TOOLTIP
   ═══════════════════════════════════════════════════════════════════════════ */

interface TooltipPayloadItem {
  name: string;
  value: number;
  dataKey: string;
  color: string;
  stroke: string;
}

function PriceChartTooltip({
  active,
  payload,
  label,
  hiddenCompetitors,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
  hiddenCompetitors: Set<string>;
}) {
  if (!active || !payload?.length || !label) return null;

  const yourEntry = payload.find((p) => p.dataKey === "yourPrice");
  const yourPrice = yourEntry?.value ?? 0;

  // Format the date label nicely
  const dateObj = new Date(label + "T00:00:00");
  const dateLabel = dateObj.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div
      style={{
        background: "rgba(15,19,24,0.95)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        border: `1px solid ${T.border}`,
        borderRadius: 10,
        padding: "14px 16px",
        boxShadow: `0 8px 32px rgba(0,0,0,0.6), ${T.cyanGlow}`,
        minWidth: 220,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontFamily: T.fontMono,
          color: T.textDim,
          marginBottom: 10,
          letterSpacing: "0.04em",
        }}
      >
        {dateLabel}
      </div>

      {/* Your price — highlighted */}
      {yourEntry && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            padding: "6px 0",
            borderBottom: `1px solid ${T.border}`,
            marginBottom: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 10,
                height: 3,
                borderRadius: 2,
                background: T.cyan,
                boxShadow: `0 0 6px ${T.cyan}88`,
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontFamily: T.fontSans,
                fontWeight: 600,
                color: T.cyan,
              }}
            >
              Your Price
            </span>
          </div>
          <span
            style={{
              fontSize: 14,
              fontFamily: T.fontMono,
              fontWeight: 700,
              color: T.cyan,
            }}
          >
            {fmtPrice(yourPrice)}
          </span>
        </div>
      )}

      {/* Competitor prices */}
      {payload
        .filter((p) => p.dataKey !== "yourPrice" && !hiddenCompetitors.has(p.dataKey))
        .sort((a, b) => a.value - b.value)
        .map((entry) => {
          const diff = yourPrice > 0 ? ((entry.value - yourPrice) / yourPrice) * 100 : 0;
          const diffColor = diff < 0 ? T.green : diff > 5 ? T.red : T.amberAlert;
          const comp = COMPETITORS.find((c) => c.id === entry.dataKey);
          return (
            <div
              key={entry.dataKey}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "4px 0",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div
                  style={{
                    width: 10,
                    height: 3,
                    borderRadius: 2,
                    background: entry.stroke || entry.color,
                  }}
                />
                <span
                  style={{
                    fontSize: 11,
                    fontFamily: T.fontSans,
                    color: T.textMuted,
                  }}
                >
                  {comp?.name ?? entry.dataKey}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{
                    fontSize: 12,
                    fontFamily: T.fontMono,
                    fontWeight: 500,
                    color: T.text,
                  }}
                >
                  {fmtPrice(entry.value)}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontFamily: T.fontMono,
                    fontWeight: 600,
                    color: diffColor,
                    minWidth: 48,
                    textAlign: "right",
                  }}
                >
                  {diff >= 0 ? "+" : ""}
                  {diff.toFixed(1)}%
                </span>
              </div>
            </div>
          );
        })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CUSTOM LEGEND
   ═══════════════════════════════════════════════════════════════════════════ */

function ChartLegend({
  hiddenCompetitors,
  onToggle,
}: {
  hiddenCompetitors: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        flexWrap: "wrap",
        padding: "14px 20px 0",
      }}
    >
      {/* Your price — always visible, larger */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 0",
        }}
      >
        <div
          style={{
            width: 18,
            height: 3,
            borderRadius: 2,
            background: T.cyan,
            boxShadow: `0 0 8px ${T.cyan}88`,
          }}
        />
        <span
          style={{
            fontSize: 13,
            fontFamily: T.fontSans,
            fontWeight: 600,
            color: T.cyan,
          }}
        >
          Your Price
        </span>
      </div>

      {/* Competitors — togglable */}
      {COMPETITORS.map((comp) => {
        const hidden = hiddenCompetitors.has(comp.id);
        return (
          <button
            key={comp.id}
            onClick={() => onToggle(comp.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 0",
              background: "none",
              border: "none",
              cursor: "pointer",
              opacity: hidden ? 0.35 : 1,
              transition: "opacity 0.2s",
            }}
          >
            <div
              style={{
                width: 14,
                height: 3,
                borderRadius: 2,
                background: comp.color,
                textDecoration: hidden ? "line-through" : "none",
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontFamily: T.fontSans,
                color: hidden ? T.textDim : T.textMuted,
                textDecoration: hidden ? "line-through" : "none",
              }}
            >
              {comp.name}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PRICE HISTORY CHART PANEL
   ═══════════════════════════════════════════════════════════════════════════ */

function PriceHistoryChart() {
  const [dateRange, setDateRange] = useState<DateRange>("30D");
  const [hiddenCompetitors, setHiddenCompetitors] = useState<Set<string>>(
    new Set()
  );

  const toggleCompetitor = useCallback((id: string) => {
    setHiddenCompetitors((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const chartData = useMemo(() => {
    const days = { "7D": 7, "30D": 30, "60D": 60, "90D": 90 }[dateRange];
    return MOCK_PRICE_DATA.slice(-days);
  }, [dateRange]);

  // Price change events within visible range
  const priceChangePoints = useMemo(() => {
    const days = { "7D": 7, "30D": 30, "60D": 60, "90D": 90 }[dateRange];
    const startIdx = MOCK_PRICE_DATA.length - days;
    return YOUR_PRICE_CHANGE_DAYS.filter((i) => i >= startIdx).map(
      (i) => MOCK_PRICE_DATA[i]
    );
  }, [dateRange]);

  // Y-axis domain — find min/max across visible data
  const [yMin, yMax] = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const point of chartData) {
      if (point.yourPrice < min) min = point.yourPrice;
      if (point.yourPrice > max) max = point.yourPrice;
      for (const comp of COMPETITORS) {
        if (!hiddenCompetitors.has(comp.id)) {
          const v = point[comp.id] as number;
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
    }
    const padding = (max - min) * 0.12;
    return [Math.floor(min - padding), Math.ceil(max + padding)];
  }, [chartData, hiddenCompetitors]);

  const formatDateTick = (dateStr: string) => {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div style={{ ...panelStyle }}>
      <div style={topGlow(T.cyan)} />

      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "18px 20px 12px",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            fontFamily: T.fontSans,
            color: T.textMuted,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          Price History
        </span>
        <DateRangePills selected={dateRange} onChange={setDateRange} />
      </div>

      {/* Chart */}
      <div style={{ padding: "0 8px 0 0" }}>
        <ResponsiveContainer width="100%" height={380}>
          <LineChart
            data={chartData}
            margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
          >
            {/* SVG filter for cyan glow */}
            <defs>
              <filter id="cyanGlow" x="-20%" y="-20%" width="140%" height="140%" filterUnits="userSpaceOnUse">
                <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
                <feFlood floodColor={T.cyan} floodOpacity="0.4" result="color" />
                <feComposite in="color" in2="blur" operator="in" result="shadow" />
                <feMerge>
                  <feMergeNode in="shadow" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <CartesianGrid
              horizontal={true}
              vertical={false}
              stroke="rgba(255,255,255,0.05)"
              strokeDasharray="0"
            />

            <XAxis
              dataKey="date"
              tickFormatter={formatDateTick}
              tick={{
                fontSize: 11,
                fontFamily: T.fontMono,
                fill: T.textDim,
              }}
              axisLine={{ stroke: T.border }}
              tickLine={false}
              tickMargin={8}
              interval="preserveStartEnd"
              minTickGap={40}
            />

            <YAxis
              domain={[yMin, yMax]}
              tickFormatter={(v: number) => `$${v}`}
              tick={{
                fontSize: 11,
                fontFamily: T.fontMono,
                fill: T.textDim,
              }}
              axisLine={false}
              tickLine={false}
              tickMargin={8}
              width={55}
            />

            <Tooltip
              content={
                <PriceChartTooltip hiddenCompetitors={hiddenCompetitors} />
              }
              cursor={{
                stroke: "rgba(255,255,255,0.08)",
                strokeWidth: 1,
                strokeDasharray: "4 4",
              }}
            />

            {/* Competitor lines */}
            {COMPETITORS.map((comp) => (
              <Line
                key={comp.id}
                type="monotone"
                dataKey={comp.id}
                stroke={comp.color}
                strokeWidth={1.5}
                dot={false}
                activeDot={{
                  r: 3,
                  fill: comp.color,
                  stroke: T.bgPanel,
                  strokeWidth: 2,
                }}
                hide={hiddenCompetitors.has(comp.id)}
                animationDuration={600}
                animationEasing="ease-out"
                connectNulls
              />
            ))}

            {/* Your price line — hero, with glow */}
            <Line
              type="stepAfter"
              dataKey="yourPrice"
              stroke={T.cyan}
              strokeWidth={2.5}
              dot={false}
              activeDot={{
                r: 5,
                fill: T.cyan,
                stroke: T.bgPanel,
                strokeWidth: 3,
                style: { filter: `drop-shadow(0 0 6px ${T.cyan})` },
              }}
              filter="url(#cyanGlow)"
              animationDuration={800}
              animationEasing="ease-out"
            />

            {/* Dots only at price change events */}
            {priceChangePoints.map((point, i) => (
              <ReferenceDot
                key={i}
                x={point.date}
                y={point.yourPrice}
                r={5}
                fill={T.cyan}
                stroke={T.bgPanel}
                strokeWidth={2.5}
                style={{ filter: `drop-shadow(0 0 8px ${T.cyan})` }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <ChartLegend
        hiddenCompetitors={hiddenCompetitors}
        onToggle={toggleCompetitor}
      />

      <div style={{ height: 14 }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SIDEBAR METRICS PANEL
   ═══════════════════════════════════════════════════════════════════════════ */

function SidebarMetrics() {
  const animatedPrice = useCountUp(YOUR_CURRENT_PRICE, 1400, 2);
  const sortedComps = [...COMPETITORS].sort(
    (a, b) => a.currentPrice - b.currentPrice
  );
  const allPrices = [YOUR_CURRENT_PRICE, ...COMPETITORS.map((c) => c.currentPrice)].sort(
    (a, b) => a - b
  );
  const yourRank = allPrices.indexOf(YOUR_CURRENT_PRICE) + 1;
  const totalPrices = allPrices.length;

  const lowest = allPrices[0];
  const highest = allPrices[allPrices.length - 1];
  const average = allPrices.reduce((s, p) => s + p, 0) / allPrices.length;
  const percentile = Math.round(((totalPrices - yourRank) / (totalPrices - 1)) * 100);

  const trendVs30d = ((YOUR_CURRENT_PRICE - YOUR_PRICE_30D_AGO) / YOUR_PRICE_30D_AGO) * 100;

  // Gap alert
  const cheapest = sortedComps[0];
  const gapDollar = YOUR_CURRENT_PRICE - cheapest.currentPrice;
  const gapPercent = (gapDollar / cheapest.currentPrice) * 100;
  const showGapAlert = gapDollar > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* ── Your Current Price Card ─── */}
      <div style={{ ...panelStyle, padding: "22px 20px" }}>
        <div style={topGlow(T.cyan)} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            fontFamily: T.fontSans,
            color: T.textMuted,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          Your Price
        </span>

        <div
          style={{
            fontSize: 38,
            fontWeight: 700,
            fontFamily: T.fontMono,
            color: T.cyan,
            letterSpacing: "-0.03em",
            lineHeight: 1.1,
            marginTop: 8,
            textShadow: `0 0 30px ${T.cyan}44`,
          }}
        >
          {fmtPrice(animatedPrice)}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginTop: 10,
          }}
        >
          <span
            style={{
              fontSize: 12,
              fontFamily: T.fontSans,
              color: T.textMuted,
            }}
          >
            {yourRank}
            {yourRank === 1 ? "st" : yourRank === 2 ? "nd" : yourRank === 3 ? "rd" : "th"}{" "}
            of {totalPrices} competitors
          </span>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 8,
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              fontSize: 12,
              fontFamily: T.fontMono,
              fontWeight: 600,
              color: trendVs30d >= 0 ? T.red : T.green,
              background: trendVs30d >= 0 ? T.redDim : T.greenDim,
              padding: "3px 8px",
              borderRadius: 5,
            }}
          >
            {trendVs30d >= 0 ? (
              <ArrowUpRight size={11} />
            ) : (
              <ArrowDownRight size={11} />
            )}
            {Math.abs(trendVs30d).toFixed(1)}%
          </span>
          <span
            style={{
              fontSize: 11,
              fontFamily: T.fontSans,
              color: T.textDim,
            }}
          >
            vs 30d ago
          </span>
        </div>
      </div>

      {/* ── Market Summary 2x2 Grid ─── */}
      <div
        style={{
          ...panelStyle,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          padding: 0,
        }}
      >
        <div style={topGlow(T.slate)} />

        {[
          { label: "Lowest", value: lowest, color: T.green },
          { label: "Highest", value: highest, color: T.red },
          { label: "Average", value: average, color: T.text },
          { label: "Your %ile", value: percentile, color: T.cyan, isSuffix: true },
        ].map((cell, i) => (
          <div
            key={cell.label}
            style={{
              padding: "16px 16px",
              borderRight: i % 2 === 0 ? `1px solid ${T.border}` : "none",
              borderBottom: i < 2 ? `1px solid ${T.border}` : "none",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                fontFamily: T.fontSans,
                color: T.textDim,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              {cell.label}
            </div>
            <div
              style={{
                fontSize: 18,
                fontWeight: 600,
                fontFamily: T.fontMono,
                color: cell.color,
                letterSpacing: "-0.02em",
              }}
            >
              {cell.isSuffix
                ? `${cell.value}%`
                : fmtPrice(cell.value)}
            </div>
          </div>
        ))}
      </div>

      {/* ── Price Gap Alert (conditional) ─── */}
      {showGapAlert && (
        <div
          style={{
            ...panelStyle,
            padding: "18px 18px",
            background: "rgba(255,176,32,0.04)",
            border: `1px solid rgba(255,176,32,0.15)`,
            boxShadow: gapPercent > 5
              ? `inset 0 0 30px rgba(255,82,82,0.05), 0 0 20px rgba(255,82,82,0.05)`
              : `inset 0 0 30px rgba(255,176,32,0.04)`,
          }}
        >
          <div
            style={topGlow(gapPercent > 5 ? T.red : T.amberAlert)}
          />
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
            }}
          >
            <AlertTriangle
              size={16}
              color={gapPercent > 5 ? T.red : T.amberAlert}
              style={{ marginTop: 1, flexShrink: 0 }}
            />
            <div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  fontFamily: T.fontSans,
                  color: gapPercent > 5 ? T.red : T.amberAlert,
                  marginBottom: 4,
                }}
              >
                Undercut by {fmtPrice(gapDollar)}
              </div>
              <div
                style={{
                  fontSize: 12,
                  fontFamily: T.fontSans,
                  color: T.textMuted,
                  lineHeight: 1.5,
                }}
              >
                {gapPercent.toFixed(1)}% above cheapest competitor ({cheapest.name})
              </div>
            </div>
          </div>

          <button
            style={{
              marginTop: 14,
              width: "100%",
              padding: "9px 16px",
              borderRadius: 8,
              border: `1px solid ${gapPercent > 5 ? T.red : T.amberAlert}55`,
              background: "transparent",
              color: gapPercent > 5 ? T.red : T.amberAlert,
              fontSize: 12,
              fontWeight: 600,
              fontFamily: T.fontSans,
              cursor: "pointer",
              transition: "all 0.2s",
              letterSpacing: "0.02em",
            }}
            onMouseEnter={(e) => {
              const btn = e.currentTarget as HTMLElement;
              btn.style.background =
                gapPercent > 5 ? T.redDim : T.amberDim;
            }}
            onMouseLeave={(e) => {
              const btn = e.currentTarget as HTMLElement;
              btn.style.background = "transparent";
            }}
          >
            Reprice Now
          </button>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COMPETITOR PRICES TABLE
   ═══════════════════════════════════════════════════════════════════════════ */

function CompetitorPricesTable() {
  const sorted = [...COMPETITORS].sort(
    (a, b) => a.currentPrice - b.currentPrice
  );

  return (
    <div style={{ ...panelStyle }}>
      <div style={topGlow(T.slate)} />

      {/* Header */}
      <div style={{ padding: "18px 20px 14px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              fontFamily: T.fontSans,
              color: T.textMuted,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            Current Competitor Prices
          </span>
          <span
            style={{
              fontSize: 11,
              fontFamily: T.fontMono,
              color: T.textDim,
            }}
          >
            {COMPETITORS.length} competitors
          </span>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            minWidth: 700,
          }}
        >
          <thead>
            <tr>
              {[
                "Competitor",
                "Current Price",
                "vs You",
                "Diff $",
                "Stock Status",
                "Last Updated",
              ].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: "10px 20px",
                    textAlign: "left",
                    fontSize: 10,
                    fontWeight: 600,
                    fontFamily: T.fontSans,
                    color: T.textDim,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    borderTop: `1px solid ${T.border}`,
                    borderBottom: `1px solid ${T.border}`,
                    background: "rgba(255,255,255,0.01)",
                    position: "sticky",
                    top: 0,
                    zIndex: 1,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((comp, idx) => {
              const diff = comp.currentPrice - YOUR_CURRENT_PRICE;
              const diffPct = (diff / YOUR_CURRENT_PRICE) * 100;

              // Color logic from YOUR perspective:
              // If they're cheaper (diff < 0) → RED (they undercut you — danger)
              // If they're slightly more expensive → AMBER
              // If they're significantly more expensive → GREEN (you're winning)
              let pillColor: string;
              let pillBg: string;
              let pillPrefix: string;
              if (diffPct < -2) {
                // They're cheaper → bad for you
                pillColor = T.red;
                pillBg = T.redDim;
                pillPrefix = "";
              } else if (diffPct < 2) {
                // Close range
                pillColor = T.amberAlert;
                pillBg = T.amberDim;
                pillPrefix = diffPct >= 0 ? "+" : "";
              } else {
                // They're more expensive → good for you
                pillColor = T.green;
                pillBg = T.greenDim;
                pillPrefix = "+";
              }

              return (
                <tr
                  key={comp.id}
                  className="competitor-row"
                  style={{
                    "--comp-color": comp.color,
                    background: idx % 2 === 1
                      ? T.bgRow
                      : "transparent",
                    borderBottom: `1px solid ${T.border}`,
                    transition: "background 0.15s",
                    cursor: "pointer",
                    borderLeft: "2px solid transparent",
                  } as React.CSSProperties}
                >
                  {/* Competitor name with color swatch */}
                  <td style={{ padding: "14px 20px" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                      }}
                    >
                      <div
                        style={{
                          width: 2,
                          height: 14,
                          borderRadius: 1,
                          background: comp.color,
                          flexShrink: 0,
                        }}
                      />
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 500,
                          fontFamily: T.fontSans,
                          color: T.text,
                        }}
                      >
                        {comp.name}
                      </span>
                    </div>
                  </td>

                  {/* Current Price */}
                  <td style={{ padding: "14px 20px" }}>
                    <span
                      style={{
                        fontSize: 14,
                        fontFamily: T.fontMono,
                        fontWeight: 600,
                        color: T.text,
                      }}
                    >
                      {fmtPrice(comp.currentPrice)}
                    </span>
                  </td>

                  {/* vs You pill */}
                  <td style={{ padding: "14px 20px" }}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 3,
                        fontSize: 12,
                        fontFamily: T.fontMono,
                        fontWeight: 600,
                        color: pillColor,
                        background: pillBg,
                        padding: "3px 10px",
                        borderRadius: 6,
                      }}
                    >
                      {pillPrefix}
                      {diffPct.toFixed(1)}%
                    </span>
                  </td>

                  {/* Diff $ */}
                  <td style={{ padding: "14px 20px" }}>
                    <span
                      style={{
                        fontSize: 13,
                        fontFamily: T.fontMono,
                        color: diff < 0 ? T.red : diff > 0 ? T.green : T.textMuted,
                      }}
                    >
                      {diff >= 0 ? "+" : ""}
                      {fmtPrice(Math.abs(diff))}
                    </span>
                  </td>

                  {/* Stock Status */}
                  <td style={{ padding: "14px 20px" }}>
                    <StockBadge status={comp.stockStatus} />
                  </td>

                  {/* Last Updated */}
                  <td style={{ padding: "14px 20px" }}>
                    <span
                      style={{
                        fontSize: 12,
                        fontFamily: T.fontMono,
                        color: T.textDim,
                      }}
                    >
                      {relativeTime(comp.lastUpdated)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN PAGE COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */

export function ProductDetailPriceHistory() {
  // Determine position
  const allPrices = [
    YOUR_CURRENT_PRICE,
    ...COMPETITORS.map((c) => c.currentPrice),
  ].sort((a, b) => a - b);
  const yourRank = allPrices.indexOf(YOUR_CURRENT_PRICE) + 1;
  const position: PositionType =
    yourRank === allPrices.length
      ? "most_expensive"
      : yourRank === 1
      ? "price_leader"
      : "competitive";

  return (
    <div style={{ fontFamily: T.fontSans, maxWidth: 1400, margin: "0 auto" }}>
      {/* CSS Animations + Fonts */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        /* Responsive: below 768px stack layout */
        @media (max-width: 768px) {
          .pdph-main-grid {
            grid-template-columns: 1fr !important;
          }
          .pdph-header-meta {
            flex-direction: column !important;
            align-items: flex-start !important;
          }
        }

        /* Competitor row hover via CSS to avoid stuck JS state */
        .competitor-row:hover {
          background: ${T.bgPanelHover} !important;
          border-left-color: var(--comp-color) !important;
        }

        /* Custom scrollbar for table */
        .pdph-table-scroll::-webkit-scrollbar {
          height: 6px;
        }
        .pdph-table-scroll::-webkit-scrollbar-track {
          background: transparent;
        }
        .pdph-table-scroll::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.08);
          border-radius: 3px;
        }
        .pdph-table-scroll::-webkit-scrollbar-thumb:hover {
          background: rgba(255,255,255,0.15);
        }
      `}</style>

      {/* ── Header ──────────────────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        {/* Back link */}
        <button
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 12,
            fontFamily: T.fontSans,
            color: T.textDim,
            padding: "4px 0",
            marginBottom: 16,
            transition: "color 0.2s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.color = T.textMuted;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.color = T.textDim;
          }}
        >
          <ArrowLeft size={14} />
          Back to Products
        </button>

        {/* Product name */}
        <h1
          style={{
            fontSize: 26,
            fontWeight: 700,
            fontFamily: T.fontSans,
            color: T.text,
            letterSpacing: "-0.02em",
            margin: "0 0 6px",
            lineHeight: 1.2,
          }}
        >
          {PRODUCT.name}
        </h1>

        {/* Meta row */}
        <div
          className="pdph-header-meta"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          {/* SKU */}
          <span
            style={{
              fontSize: 12,
              fontFamily: T.fontMono,
              color: T.textDim,
              letterSpacing: "0.02em",
            }}
          >
            {PRODUCT.sku}
          </span>

          <span style={{ color: T.textDim, fontSize: 10 }}>|</span>

          {/* Category breadcrumb */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 12,
              fontFamily: T.fontSans,
            }}
          >
            {PRODUCT.category.map((cat, i) => (
              <span key={cat}>
                <span
                  style={{
                    color: i === PRODUCT.category.length - 1 ? T.textMuted : T.textDim,
                    cursor: "pointer",
                  }}
                >
                  {cat}
                </span>
                {i < PRODUCT.category.length - 1 && (
                  <ChevronDown
                    size={10}
                    color={T.textDim}
                    style={{
                      transform: "rotate(-90deg)",
                      display: "inline-block",
                      margin: "0 2px",
                      verticalAlign: "middle",
                    }}
                  />
                )}
              </span>
            ))}
          </div>

          <span style={{ color: T.textDim, fontSize: 10 }}>|</span>

          {/* Badges */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <TrackingBadge />
            <PositionBadge position={position} />
          </div>

          <span style={{ color: T.textDim, fontSize: 10 }}>|</span>

          {/* Last scraped */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <Clock size={11} color={T.textDim} />
            <span
              style={{
                fontSize: 11,
                fontFamily: T.fontMono,
                color: T.textDim,
              }}
            >
              Updated {relativeTime(PRODUCT.lastScraped)}
            </span>
          </div>
        </div>
      </div>

      {/* ── Main Content Grid: Chart (8 cols) + Sidebar (4 cols) ── */}
      <div
        className="pdph-main-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <PriceHistoryChart />
        <SidebarMetrics />
      </div>

      {/* ── Competitor Table (full width) ─── */}
      <CompetitorPricesTable />
    </div>
  );
}

export default ProductDetailPriceHistory;
