"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Download,
  Filter,
  Search,
  X,
  Zap,
  ChevronDown,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";

/* ─────────────────────────────────────────────
   CONSTANTS & TYPES
   ───────────────────────────────────────────── */

const COLORS = {
  bg: "#090B0F",
  panel: "#0C0F14",
  drop: "#FF6B6B",
  increase: "#3DD68C",
  undercut: "#FF4444",
  cyan: "#00D4FF",
  muted: "#8B92A5",
  timestamp: "#4A5166",
  border: "rgba(255,255,255,0.05)",
  rowHover: "rgba(255,255,255,0.03)",
  text: "#E2E8F0",
  textLight: "#CBD5E1",
};

const FONT_MONO = "'JetBrains Mono', 'Fira Code', ui-monospace, monospace";
const FONT_SANS = "'DM Sans', 'Inter', ui-sans-serif, system-ui, sans-serif";

interface Competitor {
  id: string;
  name: string;
  color: string;
}

interface Product {
  id: string;
  name: string;
  sku: string;
  yourPrice: number;
}

interface FeedEntry {
  id: string;
  competitorId: string;
  productId: string;
  oldPrice: number;
  newPrice: number;
  timestamp: number;
  isUndercut: boolean;
  reviewed: boolean;
}

type Direction = "all" | "drop" | "increase";
type DateRange = "1h" | "6h" | "24h" | "7d" | "30d";

/* ─────────────────────────────────────────────
   MOCK DATA
   ───────────────────────────────────────────── */

const COMPETITORS: Competitor[] = [
  { id: "c1", name: "TechDirect Pro", color: "#6366F1" },
  { id: "c2", name: "PriceWars Global", color: "#F59E0B" },
  { id: "c3", name: "MegaMart Online", color: "#EC4899" },
  { id: "c4", name: "ValueHunt", color: "#14B8A6" },
  { id: "c5", name: "DealStream", color: "#8B5CF6" },
];

const PRODUCTS: Product[] = [
  { id: "p1", name: "Sony WH-1000XM5 Headphones", sku: "SNY-WH1000XM5", yourPrice: 348.0 },
  { id: "p2", name: "Apple AirPods Pro 2nd Gen", sku: "APL-APP2-USB", yourPrice: 249.99 },
  { id: "p3", name: "Samsung Galaxy S24 Ultra", sku: "SAM-S24U-256", yourPrice: 1299.99 },
  { id: "p4", name: "LG C3 65\" OLED TV", sku: "LG-C3-65-OLED", yourPrice: 1496.99 },
  { id: "p5", name: "Dyson V15 Detect Vacuum", sku: "DYS-V15-DET", yourPrice: 749.99 },
  { id: "p6", name: "Nintendo Switch OLED", sku: "NTD-SW-OLED", yourPrice: 349.99 },
  { id: "p7", name: "Bose QuietComfort Ultra", sku: "BSE-QC-ULTRA", yourPrice: 429.0 },
  { id: "p8", name: "iPad Air M2 256GB", sku: "APL-IPADAIR-M2", yourPrice: 699.0 },
  { id: "p9", name: "Dell XPS 15 Laptop", sku: "DEL-XPS15-I7", yourPrice: 1549.99 },
  { id: "p10", name: "GoPro Hero 12 Black", sku: "GP-HERO12-BLK", yourPrice: 399.99 },
  { id: "p11", name: "Kindle Scribe 64GB", sku: "AMZ-KS-64", yourPrice: 389.99 },
  { id: "p12", name: "Logitech MX Master 3S", sku: "LOG-MXM-3S", yourPrice: 99.99 },
  { id: "p13", name: "Canon EOS R6 Mark II", sku: "CAN-R6M2-BDY", yourPrice: 2499.0 },
  { id: "p14", name: "Sonos Era 300 Speaker", sku: "SON-ERA300", yourPrice: 449.0 },
  { id: "p15", name: "Garmin Fenix 7X Solar", sku: "GAR-F7X-SOL", yourPrice: 799.99 },
  { id: "p16", name: "PS5 Digital Edition", sku: "SNY-PS5-DIG", yourPrice: 449.99 },
  { id: "p17", name: "Apple Watch Ultra 2", sku: "APL-AWU2-49", yourPrice: 799.0 },
  { id: "p18", name: "ThinkPad X1 Carbon Gen 11", sku: "LEN-X1C-G11", yourPrice: 1649.0 },
  { id: "p19", name: "Samsung 980 PRO 2TB SSD", sku: "SAM-980P-2TB", yourPrice: 159.99 },
  { id: "p20", name: "Razer DeathAdder V3 Pro", sku: "RZR-DAV3-PRO", yourPrice: 89.99 },
  { id: "p21", name: "Nikon Z8 Mirrorless Camera", sku: "NKN-Z8-BODY", yourPrice: 3996.95 },
  { id: "p22", name: "Anker 737 Power Bank", sku: "ANK-737-PB", yourPrice: 109.99 },
  { id: "p23", name: "JBL Charge 5 Speaker", sku: "JBL-CHG5-BLK", yourPrice: 179.95 },
  { id: "p24", name: "Roku Ultra 2024", sku: "RKU-ULTRA-24", yourPrice: 99.99 },
  { id: "p25", name: "Ring Video Doorbell Pro 2", sku: "RNG-VDB-PRO2", yourPrice: 249.99 },
  { id: "p26", name: "Fitbit Charge 6", sku: "FIT-CHG6-BLK", yourPrice: 159.95 },
  { id: "p27", name: "SteelSeries Arctis Nova Pro", sku: "SS-ANP-WRLS", yourPrice: 349.99 },
  { id: "p28", name: "ASUS ROG Ally Z1 Extreme", sku: "ASUS-ROG-ALLY", yourPrice: 699.99 },
  { id: "p29", name: "Philips Hue Starter Kit", sku: "PHL-HUE-STRK", yourPrice: 199.99 },
  { id: "p30", name: "Secretlab Titan Evo 2024", sku: "SEC-TITAN-24", yourPrice: 519.0 },
];

function generateMockFeed(count = 80): FeedEntry[] {
  const now = Date.now();
  const entries: FeedEntry[] = [];

  for (let i = 0; i < count; i++) {
    const product = PRODUCTS[Math.floor(Math.random() * PRODUCTS.length)];
    const competitor = COMPETITORS[Math.floor(Math.random() * COMPETITORS.length)];

    // Cluster timestamps around "market open" (8-10am, roughly 6-14hrs ago)
    let hoursAgo: number;
    const r = Math.random();
    if (r < 0.3) hoursAgo = Math.random() * 2; // last 2 hours (recent)
    else if (r < 0.65) hoursAgo = 6 + Math.random() * 4; // 6-10 hours ago (market open cluster)
    else if (r < 0.85) hoursAgo = 2 + Math.random() * 4; // 2-6 hours ago
    else hoursAgo = 10 + Math.random() * 14; // 10-24 hours ago

    const timestamp = now - hoursAgo * 3600 * 1000;

    // Generate price change
    const isDrop = Math.random() < 0.55; // slightly more drops
    let pctChange: number;
    const magnitude = Math.random();
    if (magnitude < 0.7) pctChange = 3 + Math.random() * 7; // 3-10%
    else if (magnitude < 0.92) pctChange = 10 + Math.random() * 5; // 10-15%
    else pctChange = 15 + Math.random() * 10; // 15-25% (rare large moves)

    const basePrice = product.yourPrice * (0.85 + Math.random() * 0.3); // competitor base near your price
    const oldPrice = Math.round(basePrice * 100) / 100;
    const newPrice = isDrop
      ? Math.round(oldPrice * (1 - pctChange / 100) * 100) / 100
      : Math.round(oldPrice * (1 + pctChange / 100) * 100) / 100;

    const isUndercut = newPrice < product.yourPrice && isDrop;

    entries.push({
      id: `entry-${i}`,
      competitorId: competitor.id,
      productId: product.id,
      oldPrice,
      newPrice,
      timestamp,
      isUndercut,
      reviewed: false,
    });
  }

  return entries.sort((a, b) => b.timestamp - a.timestamp);
}

/* ─────────────────────────────────────────────
   UTILITIES
   ───────────────────────────────────────────── */

const currencyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatRelativeTime(ts: number): string {
  const diff = Date.now() - ts;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

function formatFullTimestamp(ts: number): string {
  const d = new Date(ts);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${months[d.getMonth()]} ${d.getDate()}, ${hh}:${mm}:${ss}`;
}

function pctChange(oldP: number, newP: number): string {
  const pct = ((newP - oldP) / oldP) * 100;
  const sign = pct >= 0 ? "+" : "\u2212";
  return `${sign}${Math.abs(pct).toFixed(1)}%`;
}

function getDateGroup(ts: number): string {
  const now = new Date();
  const d = new Date(ts);
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterdayStart = todayStart - 86400000;

  if (ts >= todayStart) return "Today";
  if (ts >= yesterdayStart) return "Yesterday";

  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[d.getMonth()]} ${d.getDate()}`;
}

function rangeToMs(range: DateRange): number {
  const map: Record<DateRange, number> = {
    "1h": 3600000,
    "6h": 6 * 3600000,
    "24h": 24 * 3600000,
    "7d": 7 * 24 * 3600000,
    "30d": 30 * 24 * 3600000,
  };
  return map[range];
}

/* ─────────────────────────────────────────────
   COMPONENT
   ───────────────────────────────────────────── */

export function ActivityFeed() {
  // --- Data ---
  const [allEntries] = useState<FeedEntry[]>(() => generateMockFeed(80));

  // --- Filters ---
  const [filterCompetitors, setFilterCompetitors] = useState<Set<string>>(new Set());
  const [filterProduct, setFilterProduct] = useState("");
  const [filterDirection, setFilterDirection] = useState<Direction>("all");
  const [filterDateRange, setFilterDateRange] = useState<DateRange>("24h");
  const [filterUndercutOnly, setFilterUndercutOnly] = useState(false);

  // --- State ---
  const [reviewedIds, setReviewedIds] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(20);
  const [competitorDropdownOpen, setCompetitorDropdownOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [hoveredRowId, setHoveredRowId] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => { setMounted(true); }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setCompetitorDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Debounced product search
  const handleProductSearch = useCallback((val: string) => {
    setFilterProduct(val);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => setDebouncedSearch(val), 150);
  }, []);

  // --- Filtered data ---
  const filteredEntries = useMemo(() => {
    const now = Date.now();
    const rangeMs = rangeToMs(filterDateRange);
    const search = debouncedSearch.toLowerCase();

    return allEntries.filter((entry) => {
      if (entry.timestamp < now - rangeMs) return false;
      if (filterCompetitors.size > 0 && !filterCompetitors.has(entry.competitorId)) return false;
      if (filterUndercutOnly && !entry.isUndercut) return false;
      if (filterDirection === "drop" && entry.newPrice >= entry.oldPrice) return false;
      if (filterDirection === "increase" && entry.newPrice <= entry.oldPrice) return false;
      if (search) {
        const product = PRODUCTS.find((p) => p.id === entry.productId)!;
        if (
          !product.name.toLowerCase().includes(search) &&
          !product.sku.toLowerCase().includes(search)
        )
          return false;
      }
      return true;
    });
  }, [allEntries, filterCompetitors, debouncedSearch, filterDirection, filterDateRange, filterUndercutOnly]);

  const visibleEntries = useMemo(() => filteredEntries.slice(0, visibleCount), [filteredEntries, visibleCount]);

  // --- Sidebar summary (always from full unfiltered 24h data) ---
  const summaryData = useMemo(() => {
    const now = Date.now();
    const last24h = allEntries.filter((e) => e.timestamp >= now - 86400000);
    const drops = last24h.filter((e) => e.newPrice < e.oldPrice);
    const increases = last24h.filter((e) => e.newPrice > e.oldPrice);
    const undercuts = last24h.filter((e) => e.isUndercut);

    // By competitor
    const byCompetitor = COMPETITORS.map((c) => ({
      ...c,
      count: last24h.filter((e) => e.competitorId === c.id).length,
    })).sort((a, b) => b.count - a.count);

    // Most active products
    const productCounts: Record<string, number> = {};
    last24h.forEach((e) => {
      productCounts[e.productId] = (productCounts[e.productId] || 0) + 1;
    });
    const topProducts = Object.entries(productCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([pid, count]) => ({
        product: PRODUCTS.find((p) => p.id === pid)!,
        count,
      }));

    // Recent undercuts
    const recentUndercuts = allEntries.filter((e) => e.isUndercut).slice(0, 3);

    return {
      total: last24h.length,
      drops: drops.length,
      increases: increases.length,
      undercuts: undercuts.length,
      byCompetitor,
      topProducts,
      recentUndercuts,
    };
  }, [allEntries]);

  // --- Filter helpers ---
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (filterCompetitors.size > 0) count++;
    if (debouncedSearch) count++;
    if (filterDirection !== "all") count++;
    if (filterDateRange !== "24h") count++;
    if (filterUndercutOnly) count++;
    return count;
  }, [filterCompetitors, debouncedSearch, filterDirection, filterDateRange, filterUndercutOnly]);

  const clearAllFilters = useCallback(() => {
    setFilterCompetitors(new Set());
    setFilterProduct("");
    setDebouncedSearch("");
    setFilterDirection("all");
    setFilterDateRange("24h");
    setFilterUndercutOnly(false);
    setVisibleCount(20);
  }, []);

  const toggleCompetitor = useCallback((id: string) => {
    setFilterCompetitors((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setVisibleCount(20);
  }, []);

  const toggleReviewed = useCallback((id: string) => {
    setReviewedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const markAllReviewed = useCallback(() => {
    setReviewedIds((prev) => {
      const next = new Set(prev);
      filteredEntries.forEach((e) => next.add(e.id));
      return next;
    });
  }, [filteredEntries]);

  const unmarkAllReviewed = useCallback(() => {
    setReviewedIds((prev) => {
      const next = new Set(prev);
      filteredEntries.forEach((e) => next.delete(e.id));
      return next;
    });
  }, [filteredEntries]);

  const allFilteredReviewed = useMemo(
    () => filteredEntries.length > 0 && filteredEntries.every((e) => reviewedIds.has(e.id)),
    [filteredEntries, reviewedIds],
  );

  const exportCSV = useCallback(() => {
    const header = "Timestamp,Competitor,Product,SKU,Old Price,New Price,Change %,Undercut\n";
    const rows = filteredEntries.map((e) => {
      const comp = COMPETITORS.find((c) => c.id === e.competitorId)!;
      const prod = PRODUCTS.find((p) => p.id === e.productId)!;
      const pct = (((e.newPrice - e.oldPrice) / e.oldPrice) * 100).toFixed(1);
      return `${new Date(e.timestamp).toISOString()},${comp.name},${prod.name},${prod.sku},${e.oldPrice},${e.newPrice},${pct}%,${e.isUndercut ? "Yes" : "No"}`;
    });
    const csv = header + rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `price-changes-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredEntries]);

  // --- Group entries by date (for 7d / 30d ranges) ---
  const showDateGroups = filterDateRange === "7d" || filterDateRange === "30d";

  const groupedEntries = useMemo(() => {
    if (!showDateGroups) return null;
    const groups: { label: string; entries: FeedEntry[] }[] = [];
    let currentGroup = "";
    visibleEntries.forEach((entry) => {
      const group = getDateGroup(entry.timestamp);
      if (group !== currentGroup) {
        currentGroup = group;
        groups.push({ label: group, entries: [] });
      }
      groups[groups.length - 1].entries.push(entry);
    });
    return groups;
  }, [visibleEntries, showDateGroups]);

  // The "stagger index" counter for the animation delay
  let staggerIdx = 0;

  /* ─────────────────────────────────────────────
     RENDER HELPERS
     ───────────────────────────────────────────── */

  function renderFeedRow(entry: FeedEntry, animIndex: number) {
    const competitor = COMPETITORS.find((c) => c.id === entry.competitorId)!;
    const product = PRODUCTS.find((p) => p.id === entry.productId)!;
    const isDrop = entry.newPrice < entry.oldPrice;
    const isReviewed = reviewedIds.has(entry.id);
    const isHovered = hoveredRowId === entry.id;
    const isRecent = Date.now() - entry.timestamp < 5 * 60 * 1000;
    const dirColor = isDrop ? COLORS.drop : COLORS.increase;

    const leftBorder = isReviewed
      ? `2px solid rgba(61,214,140,0.2)`
      : entry.isUndercut && !isReviewed
        ? `2px solid rgba(255,68,68,0.25)`
        : isHovered
          ? `2px solid rgba(0,212,255,0.3)`
          : "2px solid transparent";

    return (
      <div
        key={entry.id}
        className="feed-entry"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 0,
          padding: "10px 16px",
          borderBottom: `1px solid ${COLORS.border}`,
          borderLeft: leftBorder,
          background: isHovered ? COLORS.rowHover : "transparent",
          opacity: isReviewed ? 0.45 : 1,
          transition: "all 0.15s ease",
          cursor: "default",
          animation: mounted ? `slideDown 0.3s ease both` : "none",
          animationDelay: mounted ? `${animIndex * 40}ms` : "0ms",
          overflow: "hidden",
        }}
        onMouseEnter={() => setHoveredRowId(entry.id)}
        onMouseLeave={() => setHoveredRowId(null)}
      >
        {/* Time */}
        <div
          style={{
            width: 68,
            flexShrink: 0,
            fontFamily: FONT_MONO,
            fontSize: 12,
            color: COLORS.timestamp,
            marginRight: 8,
          }}
          title={formatFullTimestamp(entry.timestamp)}
        >
          {formatRelativeTime(entry.timestamp)}
        </div>

        {/* Direction arrow */}
        <div style={{ width: 18, flexShrink: 0, display: "flex", justifyContent: "center", marginRight: 8 }}>
          {isDrop ? (
            <ArrowDown size={15} color={COLORS.drop} />
          ) : (
            <ArrowUp size={15} color={COLORS.increase} />
          )}
        </div>

        {/* Competitor */}
        <div
          style={{
            width: 120,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 6,
            overflow: "hidden",
            marginRight: 8,
          }}
        >
          <div
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: competitor.color,
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 12,
              fontWeight: 500,
              color: COLORS.textLight,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {competitor.name}
          </span>
        </div>

        {/* Product */}
        <div
          style={{
            flex: "1 1 140px",
            minWidth: 100,
            overflow: "hidden",
            marginRight: 10,
          }}
        >
          <div
            style={{
              fontFamily: FONT_SANS,
              fontSize: 12,
              color: COLORS.text,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              cursor: "pointer",
            }}
            title={product.name}
            onClick={() => {/* mock navigate to product detail */}}
          >
            {product.name}
          </div>
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: 10,
              color: COLORS.timestamp,
              marginTop: 1,
            }}
          >
            {product.sku}
          </div>
        </div>

        {/* Price change — the visual hero */}
        <div
          className="price-display"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexShrink: 0,
            marginRight: 8,
          }}
        >
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 12,
              color: COLORS.timestamp,
              textDecoration: "line-through",
              whiteSpace: "nowrap",
            }}
          >
            {currencyFmt.format(entry.oldPrice)}
          </span>
          <span style={{ color: COLORS.timestamp, fontSize: 11 }}>→</span>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 13,
              fontWeight: 700,
              color: dirColor,
              whiteSpace: "nowrap",
            }}
          >
            {currencyFmt.format(entry.newPrice)}
          </span>

          {/* Percentage badge */}
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 11,
              padding: "2px 6px",
              borderRadius: 4,
              background: isDrop ? "rgba(255,107,107,0.12)" : "rgba(61,214,140,0.12)",
              border: `1px solid ${isDrop ? "rgba(255,107,107,0.25)" : "rgba(61,214,140,0.25)"}`,
              color: dirColor,
              whiteSpace: "nowrap",
            }}
          >
            {pctChange(entry.oldPrice, entry.newPrice)}
          </span>
        </div>

        {/* UNDERCUT badge */}
        <div style={{ width: 90, flexShrink: 0, display: "flex", justifyContent: "center", marginRight: 4 }}>
          {entry.isUndercut && (
            <span
              style={{
                fontFamily: FONT_SANS,
                fontSize: 10,
                fontWeight: 600,
                padding: "2px 7px",
                borderRadius: 4,
                background: "rgba(255,68,68,0.15)",
                border: `1px solid ${COLORS.undercut}`,
                color: COLORS.undercut,
                whiteSpace: "nowrap",
                boxShadow: isRecent ? `0 0 8px rgba(255,68,68,0.4)` : "none",
                animation: isRecent ? "undercutPulse 2s infinite" : "none",
              }}
            >
              <Zap size={9} style={{ display: "inline", verticalAlign: "middle", marginRight: 2 }} />
              UNDERCUT
            </span>
          )}
        </div>

        {/* Right side — hover actions + reviewed state */}
        <div style={{ width: 100, flexShrink: 0, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 6 }}>
          {isReviewed ? (
            <span style={{ fontFamily: FONT_SANS, fontSize: 11, color: "rgba(61,214,140,0.5)" }}>
              ✓ Reviewed
            </span>
          ) : isHovered ? (
            <>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 11,
                  color: COLORS.cyan,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
                onClick={() => {/* mock navigate */}}
              >
                View →
              </span>
              <button
                onClick={() => toggleReviewed(entry.id)}
                style={{
                  background: "none",
                  border: `1px solid ${COLORS.border}`,
                  borderRadius: 4,
                  padding: "3px 5px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                }}
                title="Mark reviewed"
              >
                <Check size={12} color={COLORS.muted} />
              </button>
            </>
          ) : null}
        </div>
      </div>
    );
  }

  /* ─────────────────────────────────────────────
     MAIN RENDER
     ───────────────────────────────────────────── */

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", color: COLORS.text }}>
      {/* CSS Keyframes */}
      <style>{`
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes undercutPulse {
          0%, 100% { box-shadow: 0 0 4px rgba(255,68,68,0.2); }
          50% { box-shadow: 0 0 12px rgba(255,68,68,0.5); }
        }

        .feed-entry .price-display {
          flex-wrap: nowrap;
        }
        @media (max-width: 768px) {
          .feed-entry .price-display {
            flex-wrap: wrap;
          }
        }
      `}</style>

      {/* ─── PAGE HEADER ─── */}
      <div style={{ padding: "24px 24px 0", display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontFamily: FONT_SANS, fontSize: 28, fontWeight: 700, color: "#fff", margin: 0 }}>
              Activity Feed
            </h1>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_SANS, fontSize: 13, color: COLORS.increase }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: COLORS.increase,
                  display: "inline-block",
                  animation: "pulse 2s infinite",
                }}
              />
              Live
            </span>
          </div>
          <p style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.muted, marginTop: 4 }}>
            {filteredEntries.length} price changes detected in the last {filterDateRange}
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            onClick={allFilteredReviewed ? unmarkAllReviewed : markAllReviewed}
            style={{
              fontFamily: FONT_SANS,
              fontSize: 13,
              padding: "7px 14px",
              borderRadius: 6,
              background: "transparent",
              border: `1px solid ${allFilteredReviewed ? "rgba(61,214,140,0.25)" : COLORS.border}`,
              color: allFilteredReviewed ? COLORS.increase : COLORS.muted,
              cursor: "pointer",
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = allFilteredReviewed ? "rgba(61,214,140,0.4)" : "rgba(255,255,255,0.15)"; e.currentTarget.style.color = allFilteredReviewed ? COLORS.increase : COLORS.text; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = allFilteredReviewed ? "rgba(61,214,140,0.25)" : COLORS.border; e.currentTarget.style.color = allFilteredReviewed ? COLORS.increase : COLORS.muted; }}
          >
            {allFilteredReviewed ? "Unmark All" : "Mark All as Reviewed"}
          </button>
          <button
            onClick={exportCSV}
            style={{
              fontFamily: FONT_SANS,
              fontSize: 13,
              padding: "7px 14px",
              borderRadius: 6,
              background: "transparent",
              border: `1px solid rgba(0,212,255,0.3)`,
              color: COLORS.cyan,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = COLORS.cyan; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(0,212,255,0.3)"; }}
          >
            <Download size={14} />
            Export CSV
          </button>
          {/* Sidebar toggle (desktop) */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            style={{
              fontFamily: FONT_SANS,
              fontSize: 13,
              padding: "7px 10px",
              borderRadius: 6,
              background: "transparent",
              border: `1px solid ${COLORS.border}`,
              color: COLORS.muted,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
            title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
        </div>
      </div>

      {/* ─── TOOLBAR ─── */}
      <div style={{ padding: "16px 24px", display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        {/* Filter badge */}
        {activeFilterCount > 0 && (
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 11,
              padding: "3px 8px",
              borderRadius: 10,
              background: "rgba(0,212,255,0.12)",
              color: COLORS.cyan,
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            <Filter size={10} />
            {activeFilterCount} active
          </span>
        )}

        {/* Competitor dropdown */}
        <div style={{ position: "relative" }} ref={dropdownRef}>
          <button
            onClick={() => setCompetitorDropdownOpen(!competitorDropdownOpen)}
            style={{
              fontFamily: FONT_SANS,
              fontSize: 13,
              padding: "6px 12px",
              borderRadius: 6,
              background: COLORS.panel,
              border: `1px solid ${COLORS.border}`,
              color: filterCompetitors.size > 0 ? COLORS.text : COLORS.muted,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {filterCompetitors.size > 0 ? `${filterCompetitors.size} Competitors` : "All Competitors"}
            <ChevronDown size={14} />
          </button>

          {competitorDropdownOpen && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                marginTop: 4,
                background: "rgba(12,15,20,0.95)",
                backdropFilter: "blur(12px)",
                border: `1px solid rgba(255,255,255,0.08)`,
                borderRadius: 8,
                padding: 8,
                zIndex: 50,
                minWidth: 220,
              }}
            >
              {COMPETITORS.map((c) => (
                <label
                  key={c.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 8px",
                    borderRadius: 4,
                    cursor: "pointer",
                    fontFamily: FONT_SANS,
                    fontSize: 13,
                    color: COLORS.textLight,
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = COLORS.rowHover; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                >
                  <input
                    type="checkbox"
                    checked={filterCompetitors.has(c.id)}
                    onChange={() => toggleCompetitor(c.id)}
                    style={{ accentColor: c.color }}
                  />
                  <span style={{ width: 10, height: 10, borderRadius: "50%", background: c.color, flexShrink: 0 }} />
                  {c.name}
                </label>
              ))}
            </div>
          )}

          {/* Selected competitor pills */}
          {filterCompetitors.size > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4, position: "absolute", top: "100%", left: 0, paddingTop: competitorDropdownOpen ? 0 : 4 }}>
              {[...filterCompetitors].map((cid) => {
                const c = COMPETITORS.find((x) => x.id === cid)!;
                return (
                  <span
                    key={cid}
                    style={{
                      fontFamily: FONT_SANS,
                      fontSize: 11,
                      padding: "2px 6px",
                      borderRadius: 10,
                      background: `${c.color}20`,
                      color: c.color,
                      display: "flex",
                      alignItems: "center",
                      gap: 3,
                      cursor: "pointer",
                    }}
                    onClick={() => toggleCompetitor(cid)}
                  >
                    {c.name}
                    <X size={10} />
                  </span>
                );
              })}
            </div>
          )}
        </div>

        {/* Product search */}
        <div style={{ position: "relative" }}>
          <Search
            size={14}
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: COLORS.timestamp,
            }}
          />
          <input
            type="text"
            placeholder="Search products..."
            value={filterProduct}
            onChange={(e) => handleProductSearch(e.target.value)}
            style={{
              fontFamily: FONT_MONO,
              fontSize: 13,
              padding: "6px 12px 6px 30px",
              borderRadius: 6,
              background: COLORS.panel,
              border: `1px solid ${COLORS.border}`,
              color: COLORS.text,
              outline: "none",
              width: 200,
              transition: "border-color 0.15s",
            }}
            onFocus={(e) => { e.currentTarget.style.borderColor = "rgba(0,212,255,0.4)"; e.currentTarget.style.boxShadow = "0 0 0 2px rgba(0,212,255,0.1)"; }}
            onBlur={(e) => { e.currentTarget.style.borderColor = COLORS.border; e.currentTarget.style.boxShadow = "none"; }}
          />
        </div>

        {/* Direction filter — 3-way pill toggle */}
        <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${COLORS.border}` }}>
          {([
            { key: "all" as Direction, label: "All", color: COLORS.cyan },
            { key: "drop" as Direction, label: "↓ Drops", color: COLORS.drop },
            { key: "increase" as Direction, label: "↑ Increases", color: COLORS.increase },
          ]).map(({ key, label, color }) => (
            <button
              key={key}
              onClick={() => { setFilterDirection(key); setVisibleCount(20); }}
              style={{
                fontFamily: FONT_SANS,
                fontSize: 12,
                padding: "5px 12px",
                background: filterDirection === key ? `${color}20` : "transparent",
                color: filterDirection === key ? color : COLORS.muted,
                border: "none",
                cursor: "pointer",
                borderRight: `1px solid ${COLORS.border}`,
                transition: "all 0.15s",
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Date range pills */}
        <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${COLORS.border}` }}>
          {(["1h", "6h", "24h", "7d", "30d"] as DateRange[]).map((range) => (
            <button
              key={range}
              onClick={() => { setFilterDateRange(range); setVisibleCount(20); }}
              style={{
                fontFamily: FONT_MONO,
                fontSize: 12,
                padding: "5px 10px",
                background: filterDateRange === range ? "rgba(0,212,255,0.15)" : "transparent",
                color: filterDateRange === range ? COLORS.cyan : COLORS.muted,
                border: "none",
                cursor: "pointer",
                borderRight: `1px solid ${COLORS.border}`,
                transition: "all 0.15s",
                textTransform: "uppercase",
              }}
            >
              {range}
            </button>
          ))}
        </div>

        {/* Undercut only toggle */}
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            cursor: "pointer",
            fontFamily: FONT_SANS,
            fontSize: 13,
            color: filterUndercutOnly ? COLORS.undercut : COLORS.muted,
          }}
        >
          <div
            onClick={() => { setFilterUndercutOnly(!filterUndercutOnly); setVisibleCount(20); }}
            style={{
              width: 36,
              height: 20,
              borderRadius: 10,
              background: filterUndercutOnly ? COLORS.undercut : "#1A2332",
              position: "relative",
              cursor: "pointer",
              transition: "background 0.2s",
            }}
          >
            <div
              style={{
                width: 16,
                height: 16,
                borderRadius: "50%",
                background: "#fff",
                position: "absolute",
                top: 2,
                left: filterUndercutOnly ? 18 : 2,
                transition: "left 0.2s",
              }}
            />
          </div>
          Undercut only
        </label>
      </div>

      {/* Active filters summary */}
      {activeFilterCount > 0 && (
        <div
          style={{
            padding: "0 24px 12px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.muted }}>
            Showing {filteredEntries.length} of {allEntries.length} changes
            {filterCompetitors.size > 0 && ` · ${[...filterCompetitors].map((id) => COMPETITORS.find((c) => c.id === id)?.name).join(", ")}`}
            {filterDirection !== "all" && ` · ${filterDirection === "drop" ? "↓ Drops" : "↑ Increases"}`}
            {` · Last ${filterDateRange}`}
            {filterUndercutOnly && " · Undercuts only"}
          </span>
          <button
            onClick={clearAllFilters}
            style={{
              fontFamily: FONT_SANS,
              fontSize: 12,
              color: COLORS.cyan,
              background: "none",
              border: "none",
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            Clear all filters
          </button>
        </div>
      )}

      {/* ─── MAIN CONTENT (Feed + Sidebar) ─── */}
      <div style={{ display: "flex", padding: "0 24px 40px", gap: 20 }}>
        {/* Feed Panel */}
        <div
          style={{
            flex: 1,
            background: COLORS.panel,
            borderRadius: 10,
            border: `1px solid ${COLORS.border}`,
            overflow: "hidden",
            minWidth: 0,
          }}
        >
          {filteredEntries.length === 0 ? (
            /* Empty state */
            <div style={{ padding: "80px 24px", textAlign: "center" }}>
              <Search size={48} color={COLORS.timestamp} style={{ margin: "0 auto 16px", display: "block", opacity: 0.5 }} />
              <p style={{ fontFamily: FONT_SANS, fontSize: 16, color: COLORS.muted, margin: 0 }}>
                No price changes match your filters
              </p>
              <p style={{ fontFamily: FONT_SANS, fontSize: 13, color: COLORS.timestamp, margin: "8px 0 20px" }}>
                Try adjusting your date range or removing competitor filters
              </p>
              <button
                onClick={clearAllFilters}
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 13,
                  padding: "8px 16px",
                  borderRadius: 6,
                  background: "transparent",
                  border: `1px solid rgba(0,212,255,0.3)`,
                  color: COLORS.cyan,
                  cursor: "pointer",
                }}
              >
                Clear filters
              </button>
            </div>
          ) : showDateGroups && groupedEntries ? (
            /* Grouped by date */
            <>
              {groupedEntries.map((group) => (
                <div key={group.label}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 16,
                      padding: "16px 16px 8px",
                    }}
                  >
                    <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.06)" }} />
                    <span
                      style={{
                        fontFamily: FONT_MONO,
                        fontSize: 11,
                        color: COLORS.muted,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {group.label} — {group.entries.length} changes
                    </span>
                    <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.06)" }} />
                  </div>
                  {group.entries.map((entry) => {
                    const idx = staggerIdx++;
                    return renderFeedRow(entry, idx);
                  })}
                </div>
              ))}
            </>
          ) : (
            /* Flat list */
            visibleEntries.map((entry, i) => renderFeedRow(entry, i))
          )}

          {/* Load more */}
          {filteredEntries.length > 0 && (
            <div style={{ padding: "20px 16px", textAlign: "center" }}>
              {visibleCount < filteredEntries.length ? (
                <>
                  <button
                    onClick={() => setVisibleCount((v) => v + 20)}
                    style={{
                      fontFamily: FONT_SANS,
                      fontSize: 13,
                      padding: "8px 20px",
                      borderRadius: 6,
                      background: "transparent",
                      border: `1px solid ${COLORS.border}`,
                      color: COLORS.muted,
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.15)"; e.currentTarget.style.color = COLORS.text; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = COLORS.border; e.currentTarget.style.color = COLORS.muted; }}
                  >
                    Load 20 more
                  </button>
                  <p style={{ fontFamily: FONT_MONO, fontSize: 11, color: COLORS.timestamp, marginTop: 8 }}>
                    Showing {visibleCount} of {filteredEntries.length} changes
                  </p>
                </>
              ) : (
                <p style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.muted }}>
                  All {filteredEntries.length} changes loaded ✓
                </p>
              )}
            </div>
          )}
        </div>

        {/* ─── SIDEBAR ─── */}
        {sidebarOpen && (
          <div
            style={{
              width: 280,
              flexShrink: 0,
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            {/* Last 24h Summary */}
            <div
              style={{
                background: COLORS.panel,
                borderRadius: 10,
                border: `1px solid ${COLORS.border}`,
                padding: 20,
              }}
            >
              <h3 style={{ fontFamily: FONT_SANS, fontSize: 13, fontWeight: 600, color: COLORS.muted, margin: "0 0 16px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Last 24h Summary
              </h3>
              <div style={{ fontFamily: FONT_MONO, fontSize: 32, fontWeight: 700, color: "#fff", lineHeight: 1 }}>
                {summaryData.total}
              </div>
              <div style={{ fontFamily: FONT_SANS, fontSize: 12, color: COLORS.muted, marginTop: 2 }}>
                total changes
              </div>

              {/* Drop vs Increase bar */}
              <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", marginTop: 16, background: "rgba(255,255,255,0.05)" }}>
                <div style={{ width: `${summaryData.total ? (summaryData.drops / summaryData.total) * 100 : 0}%`, background: COLORS.drop, transition: "width 0.3s" }} />
                <div style={{ width: `${summaryData.total ? (summaryData.increases / summaryData.total) * 100 : 0}%`, background: COLORS.increase, transition: "width 0.3s" }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.drop }}>
                  ↓ {summaryData.drops} drops
                </span>
                <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.increase }}>
                  ↑ {summaryData.increases} increases
                </span>
              </div>

              {/* Undercuts count */}
              <div
                style={{
                  marginTop: 16,
                  padding: "10px 12px",
                  borderRadius: 6,
                  background: "rgba(255,68,68,0.08)",
                  border: "1px solid rgba(255,68,68,0.15)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <Zap size={14} color={COLORS.undercut} />
                <span style={{ fontFamily: FONT_MONO, fontSize: 14, fontWeight: 700, color: COLORS.undercut }}>
                  {summaryData.undercuts}
                </span>
                <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: COLORS.muted }}>
                  undercuts
                </span>
              </div>
            </div>

            {/* By Competitor */}
            <div
              style={{
                background: COLORS.panel,
                borderRadius: 10,
                border: `1px solid ${COLORS.border}`,
                padding: 20,
              }}
            >
              <h3 style={{ fontFamily: FONT_SANS, fontSize: 13, fontWeight: 600, color: COLORS.muted, margin: "0 0 12px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                By Competitor
              </h3>
              {summaryData.byCompetitor.map((c) => {
                const maxCount = summaryData.byCompetitor[0]?.count || 1;
                return (
                  <div key={c.id} style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: c.color, display: "inline-block" }} />
                        <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: COLORS.textLight }}>{c.name}</span>
                      </div>
                      <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.muted }}>{c.count}</span>
                    </div>
                    <div style={{ height: 3, borderRadius: 2, background: "rgba(255,255,255,0.05)" }}>
                      <div
                        style={{
                          height: "100%",
                          borderRadius: 2,
                          background: c.color,
                          width: `${(c.count / maxCount) * 100}%`,
                          opacity: 0.6,
                          transition: "width 0.3s",
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Most Active Products */}
            <div
              style={{
                background: COLORS.panel,
                borderRadius: 10,
                border: `1px solid ${COLORS.border}`,
                padding: 20,
              }}
            >
              <h3 style={{ fontFamily: FONT_SANS, fontSize: 13, fontWeight: 600, color: COLORS.muted, margin: "0 0 12px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Most Active Products
              </h3>
              {summaryData.topProducts.map(({ product, count }) => (
                <div
                  key={product.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "6px 0",
                    borderBottom: `1px solid ${COLORS.border}`,
                    cursor: "pointer",
                  }}
                >
                  <span
                    style={{
                      fontFamily: FONT_SANS,
                      fontSize: 12,
                      color: COLORS.text,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      maxWidth: 190,
                    }}
                  >
                    {product.name}
                  </span>
                  <span
                    style={{
                      fontFamily: FONT_MONO,
                      fontSize: 11,
                      padding: "1px 6px",
                      borderRadius: 4,
                      background: "rgba(0,212,255,0.1)",
                      color: COLORS.cyan,
                      flexShrink: 0,
                    }}
                  >
                    {count}
                  </span>
                </div>
              ))}
            </div>

            {/* Recent Undercuts */}
            <div
              style={{
                background: "rgba(255,68,68,0.05)",
                borderRadius: 10,
                border: `1px solid rgba(255,68,68,0.1)`,
                padding: 20,
              }}
            >
              <h3 style={{ fontFamily: FONT_SANS, fontSize: 13, fontWeight: 600, color: COLORS.undercut, margin: "0 0 12px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Recent Undercuts
              </h3>
              {summaryData.recentUndercuts.length === 0 ? (
                <p style={{ fontFamily: FONT_SANS, fontSize: 12, color: COLORS.muted }}>No undercuts detected</p>
              ) : (
                summaryData.recentUndercuts.map((entry) => {
                  const comp = COMPETITORS.find((c) => c.id === entry.competitorId)!;
                  const prod = PRODUCTS.find((p) => p.id === entry.productId)!;
                  return (
                    <div
                      key={entry.id}
                      style={{
                        padding: "8px 0",
                        borderBottom: `1px solid rgba(255,68,68,0.08)`,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Zap size={11} color={COLORS.undercut} />
                        <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: COLORS.textLight, fontWeight: 500 }}>
                          {comp.name}
                        </span>
                      </div>
                      <div style={{ fontFamily: FONT_SANS, fontSize: 11, color: COLORS.muted, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {prod.name}
                      </div>
                      <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: COLORS.timestamp, marginTop: 2 }}>
                        {formatRelativeTime(entry.timestamp)}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
