"use client";

import {
  useState,
  useMemo,
  useEffect,
  useRef,
  useCallback,
} from "react";
import {
  Download,
  X,
  ChevronDown,
  ArrowUpRight,
  ArrowDownRight,
  Check,
  Loader2,
  TrendingUp,
  Search,
} from "lucide-react";

/* ═══════════════════════════════════════════════════════════════════════════
   DESIGN TOKENS
   ═══════════════════════════════════════════════════════════════════════════ */

const T = {
  bg: "#090B0F",
  bgPanel: "#0F1318",
  bgPanelHover: "rgba(255,255,255,0.04)",
  bgRow: "rgba(255,255,255,0.015)",
  border: "rgba(255,255,255,0.05)",
  borderHover: "rgba(255,255,255,0.12)",
  // Cell semantics
  cellWin: "#0F2A1C",
  cellWinText: "#3DD68C",
  cellWinBadgeBg: "rgba(61,214,140,0.15)",
  cellWinBadgeBorder: "rgba(61,214,140,0.3)",
  cellNeutral: "#141825",
  cellNeutralText: "#8B92A5",
  cellNeutralBadgeBg: "rgba(139,146,165,0.1)",
  cellNeutralBadgeBorder: "rgba(139,146,165,0.2)",
  cellLose: "#2A0F13",
  cellLoseText: "#FF6B6B",
  cellLoseBadgeBg: "rgba(255,107,107,0.15)",
  cellLoseBadgeBorder: "rgba(255,107,107,0.3)",
  cellNoData: "#0C0E13",
  // Your column
  yourColBg: "#0A1A26",
  yourColBorder: "rgba(0,212,255,0.2)",
  cyan: "#00D4FF",
  cyanDim: "rgba(0,212,255,0.10)",
  cyanBorder: "rgba(0,212,255,0.3)",
  // Semantic
  green: "#3DD68C",
  greenDim: "rgba(61,214,140,0.12)",
  amber: "#FFB020",
  amberDim: "rgba(255,176,32,0.12)",
  red: "#FF6B6B",
  redDim: "rgba(255,107,107,0.12)",
  // Text
  text: "#E8ECF4",
  textMuted: "#6B7A99",
  textDim: "#3D4A63",
  // Fonts
  fontMono: "'JetBrains Mono', 'Fira Code', ui-monospace, monospace",
  fontSans: "'DM Sans', 'Geist', system-ui, -apple-system, sans-serif",
} as const;

/* ═══════════════════════════════════════════════════════════════════════════
   COMPETITOR CONFIG
   ═══════════════════════════════════════════════════════════════════════════ */

interface CompetitorDef {
  id: string;
  name: string;
  color: string;
  initial: string;
}

const COMPETITORS: CompetitorDef[] = [
  { id: "comp_a", name: "TechDirect Pro", color: "#6C8EBF", initial: "T" },
  { id: "comp_b", name: "PriceWars Global", color: "#E8A838", initial: "P" },
  { id: "comp_c", name: "BargainBay", color: "#E06C75", initial: "B" },
  { id: "comp_d", name: "MegaShop Direct", color: "#98C379", initial: "M" },
  { id: "comp_e", name: "ValueVault", color: "#C678DD", initial: "V" },
];

/* ═══════════════════════════════════════════════════════════════════════════
   MOCK DATA
   ═══════════════════════════════════════════════════════════════════════════ */

type Category = "Electronics" | "Apparel" | "Home & Garden" | "Sports";
type Tag = "sale" | "new" | "clearance" | "featured";

interface CompetitorPrice {
  price: number | null;
  diffPct: number | null;   // vs your price, from YOUR perspective. positive = they're more expensive
  diffDollar: number | null;
}

interface ProductRow {
  id: number;
  name: string;
  sku: string;
  category: Category;
  tags: Tag[];
  yourPrice: number;
  competitors: Record<string, CompetitorPrice>;
  priceChanges24h: number;
}

function generateMockProducts(): ProductRow[] {
  let seed = 137;
  const rand = () => {
    seed = (seed * 16807 + 0) % 2147483647;
    return (seed - 1) / 2147483646;
  };

  const products: Array<{ name: string; sku: string; category: Category; basePrice: number; tags: Tag[] }> = [
    { name: "Sony WH-1000XM5", sku: "SKU-WH1000XM5", category: "Electronics", basePrice: 327.99, tags: ["featured"] },
    { name: "Apple AirPods Pro 2", sku: "SKU-APP2-WHT", category: "Electronics", basePrice: 249.00, tags: ["new", "featured"] },
    { name: "Samsung Galaxy S24 Ultra", sku: "SKU-SGS24U-256", category: "Electronics", basePrice: 1199.99, tags: ["new"] },
    { name: "Nike Air Max 90", sku: "SKU-NAM90-BLK", category: "Apparel", basePrice: 129.99, tags: ["sale"] },
    { name: "Dyson V15 Detect", sku: "SKU-DV15-ABS", category: "Home & Garden", basePrice: 749.99, tags: [] },
    { name: "Bose QC Ultra Headphones", sku: "SKU-BQC-ULT", category: "Electronics", basePrice: 429.00, tags: ["featured"] },
    { name: "iPad Air M2 256GB", sku: "SKU-IPA-M2-256", category: "Electronics", basePrice: 599.00, tags: [] },
    { name: "Lego Technic Ferrari", sku: "SKU-LT-FER-42", category: "Home & Garden", basePrice: 449.99, tags: ["clearance"] },
    { name: "Adidas Ultraboost 23", sku: "SKU-AUB23-WHT", category: "Apparel", basePrice: 189.99, tags: ["sale"] },
    { name: "Canon EOS R6 Mark II", sku: "SKU-CER6-MK2", category: "Electronics", basePrice: 2499.00, tags: [] },
    { name: "Wilson Pro Staff 97", sku: "SKU-WPS97-V14", category: "Sports", basePrice: 269.00, tags: [] },
    { name: "Patagonia Nano Puff", sku: "SKU-PNP-BLU-L", category: "Apparel", basePrice: 229.00, tags: ["featured"] },
    { name: "iRobot Roomba j7+", sku: "SKU-IRJ7-PLUS", category: "Home & Garden", basePrice: 599.99, tags: ["sale"] },
    { name: "Garmin Fenix 7X", sku: "SKU-GF7X-SOL", category: "Sports", basePrice: 899.99, tags: ["new"] },
    { name: "LG C3 65\" OLED TV", sku: "SKU-LGC3-65", category: "Electronics", basePrice: 1796.99, tags: ["clearance"] },
    { name: "North Face Nuptse 700", sku: "SKU-NFN700-BLK", category: "Apparel", basePrice: 320.00, tags: [] },
    { name: "Yeti Rambler 26oz", sku: "SKU-YR26-NVY", category: "Home & Garden", basePrice: 38.00, tags: ["featured"] },
    { name: "Peloton Bike+", sku: "SKU-PLT-BIKE+", category: "Sports", basePrice: 2495.00, tags: [] },
    { name: "Marshall Stanmore III", sku: "SKU-MST3-BLK", category: "Electronics", basePrice: 379.99, tags: [] },
    { name: "Brooks Ghost 15", sku: "SKU-BG15-GRY", category: "Sports", basePrice: 139.95, tags: ["sale"] },
    { name: "Hydro Flask 32oz Wide", sku: "SKU-HF32-AGV", category: "Home & Garden", basePrice: 44.95, tags: [] },
    { name: "Under Armour HOVR", sku: "SKU-UAHVR-BLK", category: "Sports", basePrice: 159.99, tags: ["new"] },
    { name: "Sonos Era 300", sku: "SKU-SE300-WHT", category: "Electronics", basePrice: 449.00, tags: ["featured"] },
    { name: "Columbia Bugaboo III", sku: "SKU-CB3-NVY-M", category: "Apparel", basePrice: 199.99, tags: ["clearance"] },
    { name: "Theragun Pro Plus", sku: "SKU-TGP-PLUS", category: "Sports", basePrice: 499.00, tags: [] },
  ];

  return products.map((p, idx) => {
    const competitors: Record<string, CompetitorPrice> = {};

    for (const comp of COMPETITORS) {
      // 12% chance of no data
      if (rand() < 0.12) {
        competitors[comp.id] = { price: null, diffPct: null, diffDollar: null };
        continue;
      }
      // Generate price: ±15% of your price with bias
      const variance = (rand() - 0.45) * 0.30; // slight bias towards being cheaper
      const compPrice = Math.round(p.basePrice * (1 + variance) * 100) / 100;
      const diffDollar = compPrice - p.basePrice;
      const diffPct = (diffDollar / p.basePrice) * 100;
      competitors[comp.id] = {
        price: compPrice,
        diffPct: Math.round(diffPct * 10) / 10,
        diffDollar: Math.round(diffDollar * 100) / 100,
      };
    }

    const priceChanges24h = rand() < 0.25 ? Math.floor(rand() * 5) + 1 : 0;

    return {
      id: idx + 1,
      name: p.name,
      sku: p.sku,
      category: p.category,
      tags: p.tags,
      yourPrice: p.basePrice,
      competitors,
      priceChanges24h,
    };
  });
}

const ALL_PRODUCTS = generateMockProducts();
const ALL_CATEGORIES: Category[] = ["Electronics", "Apparel", "Home & Garden", "Sports"];
const ALL_TAGS: Tag[] = ["sale", "new", "clearance", "featured"];

/* ═══════════════════════════════════════════════════════════════════════════
   FORMATTING
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

function fmtDiff(pct: number): string {
  return (pct > 0 ? "+" : "") + pct.toFixed(1) + "%";
}

/* ═══════════════════════════════════════════════════════════════════════════
   SORT MODES
   ═══════════════════════════════════════════════════════════════════════════ */

type SortMode = "biggest_undercut" | "biggest_overcharge" | "alpha_az" | "alpha_za" | "most_changes";

const SORT_OPTIONS: { value: SortMode; label: string }[] = [
  { value: "biggest_undercut", label: "Biggest Undercut" },
  { value: "biggest_overcharge", label: "Biggest Overcharge" },
  { value: "alpha_az", label: "Alphabetical (A→Z)" },
  { value: "alpha_za", label: "Alphabetical (Z→A)" },
  { value: "most_changes", label: "Most Price Changes (24h)" },
];

function getRowUndercutScore(row: ProductRow, visibleComps: string[]): number {
  // How many competitors is your price cheaper than?
  let score = 0;
  for (const cid of visibleComps) {
    const cp = row.competitors[cid];
    if (cp?.diffPct != null && cp.diffPct > 0) score += cp.diffPct;
  }
  return score;
}

function getRowOverchargeScore(row: ProductRow, visibleComps: string[]): number {
  let score = 0;
  for (const cid of visibleComps) {
    const cp = row.competitors[cid];
    if (cp?.diffPct != null && cp.diffPct < 0) score += Math.abs(cp.diffPct);
  }
  return score;
}

/* ═══════════════════════════════════════════════════════════════════════════
   ROW STATUS DOT
   ═══════════════════════════════════════════════════════════════════════════ */

function RowStatusIndicator({ product, visibleComps }: { product: ProductRow; visibleComps: string[] }) {
  let cheaperCount = 0;
  let undercutBy = 0;
  let totalTracked = 0;

  for (const cid of visibleComps) {
    const cp = product.competitors[cid];
    if (cp?.price == null) continue;
    totalTracked++;
    if (cp.diffPct != null && cp.diffPct < -5) undercutBy++;
    if (cp.diffPct != null && cp.diffPct > 5) cheaperCount++;
  }

  const indicators: React.ReactNode[] = [];

  if (totalTracked > 0 && cheaperCount === totalTracked) {
    // Cheapest across all
    indicators.push(
      <span key="win" title="Cheapest across all competitors" style={{
        width: 6, height: 6, borderRadius: "50%", background: T.green,
        boxShadow: `0 0 4px ${T.green}66`, display: "inline-block", flexShrink: 0,
      }} />
    );
  } else if (undercutBy >= 2) {
    indicators.push(
      <span key="lose" title={`Undercut by ${undercutBy} competitors`} style={{
        width: 6, height: 6, borderRadius: "50%", background: T.red,
        boxShadow: `0 0 4px ${T.red}66`, display: "inline-block", flexShrink: 0,
      }} />
    );
  } else if (undercutBy === 1) {
    indicators.push(
      <span key="warn" title="Undercut by 1 competitor" style={{
        width: 6, height: 6, borderRadius: "50%", background: T.amber,
        boxShadow: `0 0 4px ${T.amber}66`, display: "inline-block", flexShrink: 0,
      }} />
    );
  }

  if (product.priceChanges24h > 0) {
    indicators.push(
      <span key="changes" title={`${product.priceChanges24h} price changes in 24h`} style={{
        display: "inline-flex", alignItems: "center", gap: 2,
        fontSize: 9, fontFamily: T.fontMono, fontWeight: 600,
        color: T.amber, background: T.amberDim,
        padding: "1px 5px", borderRadius: 4, flexShrink: 0,
      }}>
        <TrendingUp size={8} />
        {product.priceChanges24h}
      </span>
    );
  }

  if (indicators.length === 0) return null;

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginLeft: 6 }}>
      {indicators}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DIFF BADGE
   ═══════════════════════════════════════════════════════════════════════════ */

function DiffBadge({ diffPct }: { diffPct: number }) {
  let badgeBg: string;
  let badgeBorder: string;
  let badgeText: string;

  if (diffPct > 5) {
    // They're more expensive — you're winning
    badgeBg = T.cellWinBadgeBg;
    badgeBorder = T.cellWinBadgeBorder;
    badgeText = T.cellWinText;
  } else if (diffPct < -5) {
    // They're cheaper — you're losing
    badgeBg = T.cellLoseBadgeBg;
    badgeBorder = T.cellLoseBadgeBorder;
    badgeText = T.cellLoseText;
  } else {
    badgeBg = T.cellNeutralBadgeBg;
    badgeBorder = T.cellNeutralBadgeBorder;
    badgeText = T.cellNeutralText;
  }

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 2,
      fontSize: 11, fontFamily: T.fontMono, fontWeight: 600,
      color: badgeText, background: badgeBg,
      border: `1px solid ${badgeBorder}`,
      padding: "2px 6px", borderRadius: 4, lineHeight: 1.2,
      whiteSpace: "nowrap",
    }}>
      {fmtDiff(diffPct)}
      {diffPct > 5 && <ArrowUpRight size={9} />}
      {diffPct < -5 && <ArrowDownRight size={9} />}
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TOAST NOTIFICATION
   ═══════════════════════════════════════════════════════════════════════════ */

function Toast({ message, visible, onDone }: { message: string; visible: boolean; onDone: () => void }) {
  useEffect(() => {
    if (visible) {
      const t = setTimeout(onDone, 3000);
      return () => clearTimeout(t);
    }
  }, [visible, onDone]);

  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 9999,
      background: "#1A2332",
      border: `1px solid ${T.cellWinBadgeBorder}`,
      borderRadius: 10, padding: "12px 18px",
      display: "flex", alignItems: "center", gap: 10,
      boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
      transform: visible ? "translateY(0)" : "translateY(20px)",
      opacity: visible ? 1 : 0,
      transition: "all 0.3s ease",
      pointerEvents: visible ? "auto" : "none",
    }}>
      <div style={{
        width: 20, height: 20, borderRadius: "50%",
        background: T.greenDim, display: "flex",
        alignItems: "center", justifyContent: "center",
      }}>
        <Check size={12} color={T.green} />
      </div>
      <span style={{ fontSize: 13, fontFamily: T.fontSans, color: T.text }}>
        {message}
      </span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DROPDOWN COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */

function Dropdown({
  label,
  children,
  width = 220,
}: {
  label: React.ReactNode;
  children: (close: () => void) => React.ReactNode;
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "7px 12px", borderRadius: 8,
          border: `1px solid ${open ? T.borderHover : T.border}`,
          background: open ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
          color: T.textMuted, fontSize: 12, fontFamily: T.fontSans,
          cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = T.borderHover; }}
        onMouseLeave={(e) => { if (!open) (e.currentTarget as HTMLElement).style.borderColor = T.border; }}
      >
        {label}
        <ChevronDown size={12} style={{
          transform: open ? "rotate(180deg)" : "rotate(0)",
          transition: "transform 0.2s",
        }} />
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 100,
          width,
          background: "rgba(15,19,24,0.97)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: `1px solid ${T.borderHover}`,
          borderRadius: 10, padding: "6px",
          boxShadow: "0 12px 40px rgba(0,0,0,0.6)",
        }}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   EXPORT CSV
   ═══════════════════════════════════════════════════════════════════════════ */

function generateCSV(products: ProductRow[], visibleComps: CompetitorDef[]): string {
  const headers = ["Product Name", "SKU", "Category", "Your Price"];
  for (const c of visibleComps) {
    headers.push(`${c.name} Price`, `${c.name} Diff %`);
  }

  const rows = products.map((p) => {
    const row: string[] = [
      `"${p.name}"`,
      p.sku,
      p.category,
      p.yourPrice.toFixed(2),
    ];
    for (const c of visibleComps) {
      const cp = p.competitors[c.id];
      row.push(cp?.price != null ? cp.price.toFixed(2) : "N/A");
      row.push(cp?.diffPct != null ? fmtDiff(cp.diffPct) : "N/A");
    }
    return row.join(",");
  });

  return [headers.join(","), ...rows].join("\n");
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */

export function CompetitorComparisonMatrix() {
  // ── State ──
  const [categoryFilter, setCategoryFilter] = useState<Category | null>(null);
  const [tagFilters, setTagFilters] = useState<Set<Tag>>(new Set());
  const [sortMode, setSortMode] = useState<SortMode>("biggest_undercut");
  const [visibleCompetitors, setVisibleCompetitors] = useState<Set<string>>(
    new Set(COMPETITORS.map((c) => c.id))
  );
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage] = useState(50);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);
  const [hoveredCol, setHoveredCol] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [toastVisible, setToastVisible] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [sortByCompetitor, setSortByCompetitor] = useState<string | null>(null);

  const visibleComps = COMPETITORS.filter((c) => visibleCompetitors.has(c.id));

  // ── Filtered + Sorted Data ──
  const filteredSorted = useMemo(() => {
    let data = [...ALL_PRODUCTS];

    // Category filter
    if (categoryFilter) {
      data = data.filter((p) => p.category === categoryFilter);
    }

    // Tag filter
    if (tagFilters.size > 0) {
      data = data.filter((p) => p.tags.some((t) => tagFilters.has(t)));
    }

    // Sort
    const visComps = COMPETITORS.filter((c) => visibleCompetitors.has(c.id)).map((c) => c.id);

    if (sortByCompetitor) {
      // Sort by specific competitor diff
      data.sort((a, b) => {
        const aDiff = a.competitors[sortByCompetitor]?.diffPct ?? 0;
        const bDiff = b.competitors[sortByCompetitor]?.diffPct ?? 0;
        return bDiff - aDiff;
      });
    } else {
      switch (sortMode) {
        case "biggest_undercut":
          data.sort((a, b) => getRowUndercutScore(b, visComps) - getRowUndercutScore(a, visComps));
          break;
        case "biggest_overcharge":
          data.sort((a, b) => getRowOverchargeScore(b, visComps) - getRowOverchargeScore(a, visComps));
          break;
        case "alpha_az":
          data.sort((a, b) => a.name.localeCompare(b.name));
          break;
        case "alpha_za":
          data.sort((a, b) => b.name.localeCompare(a.name));
          break;
        case "most_changes":
          data.sort((a, b) => b.priceChanges24h - a.priceChanges24h);
          break;
      }
    }

    return data;
  }, [categoryFilter, tagFilters, sortMode, visibleCompetitors, sortByCompetitor]);

  // Pagination
  const totalProducts = filteredSorted.length;
  const totalPages = Math.max(1, Math.ceil(totalProducts / perPage));
  const pageStart = (currentPage - 1) * perPage;
  const pageEnd = Math.min(pageStart + perPage, totalProducts);
  const pageData = filteredSorted.slice(pageStart, pageEnd);

  // Reset page on filter change
  useEffect(() => {
    setCurrentPage(1);
  }, [categoryFilter, tagFilters, sortMode, sortByCompetitor]);

  // ── Averages summary row ──
  const averages = useMemo(() => {
    const avgs: Record<string, number | null> = {};
    for (const comp of visibleComps) {
      const diffs = filteredSorted
        .map((p) => p.competitors[comp.id]?.diffPct)
        .filter((d): d is number => d != null);
      avgs[comp.id] = diffs.length > 0 ? diffs.reduce((s, d) => s + d, 0) / diffs.length : null;
    }
    return avgs;
  }, [filteredSorted, visibleComps]);

  // ── Competitor toggle ──
  const toggleCompetitor = useCallback((id: string) => {
    setVisibleCompetitors((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size <= 1) return prev; // keep at least 1
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    if (sortByCompetitor === id) setSortByCompetitor(null);
  }, [sortByCompetitor]);

  // ── Tag toggle ──
  const toggleTag = useCallback((tag: Tag) => {
    setTagFilters((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  // ── Export ──
  const handleExport = useCallback(() => {
    setExporting(true);
    setTimeout(() => {
      const csv = generateCSV(filteredSorted, visibleComps);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const dateStr = new Date().toISOString().split("T")[0];
      link.href = url;
      link.download = `comparison-matrix-${dateStr}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      setExporting(false);
      setToastMessage(`Exported ${filteredSorted.length} products`);
      setToastVisible(true);
    }, 800);
  }, [filteredSorted, visibleComps]);

  // ── Count categories ──
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const cat of ALL_CATEGORIES) {
      counts[cat] = ALL_PRODUCTS.filter((p) => p.category === cat).length;
    }
    return counts;
  }, []);

  const hasActiveFilters = categoryFilter !== null || tagFilters.size > 0;

  // ── Cell color logic ──
  function getCellStyle(diffPct: number | null): { bg: string; text: string } {
    if (diffPct == null) return { bg: T.cellNoData, text: T.textDim };
    if (diffPct > 5) return { bg: T.cellWin, text: T.cellWinText };
    if (diffPct < -5) return { bg: T.cellLose, text: T.cellLoseText };
    return { bg: T.cellNeutral, text: T.cellNeutralText };
  }

  return (
    <div style={{ fontFamily: T.fontSans, maxWidth: 1600, margin: "0 auto" }}>
      {/* CSS */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

        .ccm-table-scroll::-webkit-scrollbar { height: 8px; width: 8px; }
        .ccm-table-scroll::-webkit-scrollbar-track { background: transparent; }
        .ccm-table-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
        .ccm-table-scroll::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
        .ccm-table-scroll::-webkit-scrollbar-corner { background: transparent; }

        @media (max-width: 900px) {
          .ccm-toolbar { flex-direction: column !important; align-items: flex-start !important; }
        }
      `}</style>

      {/* ═══════════════ PAGE HEADER ═══════════════ */}
      <div style={{
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        marginBottom: 24, flexWrap: "wrap", gap: 16,
      }}>
        <div>
          <h1 style={{
            fontSize: 26, fontWeight: 700, fontFamily: T.fontSans,
            color: T.text, letterSpacing: "-0.02em", margin: "0 0 6px",
          }}>
            Comparison Matrix
          </h1>
          <p style={{
            fontSize: 12, fontFamily: T.fontMono, color: T.textDim,
            margin: 0, letterSpacing: "0.02em",
          }}>
            {ALL_PRODUCTS.length} products × {COMPETITORS.length} competitors — last updated 3 min ago
          </p>
        </div>

        {/* Export CSV button */}
        <button
          onClick={handleExport}
          disabled={exporting}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "9px 18px", borderRadius: 8,
            border: `1px solid ${T.cyanBorder}`,
            background: exporting ? T.cyanDim : "rgba(0,212,255,0.05)",
            color: T.cyan, fontSize: 13, fontWeight: 600,
            fontFamily: T.fontSans, cursor: exporting ? "wait" : "pointer",
            transition: "all 0.2s", letterSpacing: "0.01em",
          }}
          onMouseEnter={(e) => {
            if (!exporting) (e.currentTarget as HTMLElement).style.background = T.cyanDim;
          }}
          onMouseLeave={(e) => {
            if (!exporting) (e.currentTarget as HTMLElement).style.background = "rgba(0,212,255,0.05)";
          }}
        >
          {exporting ? (
            <>
              <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
              Preparing export...
            </>
          ) : (
            <>
              <Download size={14} />
              Export CSV
            </>
          )}
        </button>
      </div>

      {/* ═══════════════ TOOLBAR ROW ═══════════════ */}
      <div className="ccm-toolbar" style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, marginBottom: hasActiveFilters ? 8 : 16, flexWrap: "wrap",
      }}>
        {/* Left — Filters */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Category filter */}
          <Dropdown
            label={categoryFilter || "All Categories"}
            width={240}
          >
            {(close) => (
              <>
                <button
                  onClick={() => { setCategoryFilter(null); close(); }}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: 6,
                    border: "none", background: !categoryFilter ? "rgba(255,255,255,0.06)" : "transparent",
                    color: T.text, fontSize: 12, fontFamily: T.fontSans,
                    cursor: "pointer", textAlign: "left", transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.06)"; }}
                  onMouseLeave={(e) => { if (categoryFilter) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  All Categories <span style={{ color: T.textDim, fontFamily: T.fontMono, fontSize: 11 }}>({ALL_PRODUCTS.length})</span>
                </button>
                {ALL_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => { setCategoryFilter(cat); close(); }}
                    style={{
                      width: "100%", padding: "8px 12px", borderRadius: 6,
                      border: "none", background: categoryFilter === cat ? "rgba(255,255,255,0.06)" : "transparent",
                      color: T.text, fontSize: 12, fontFamily: T.fontSans,
                      cursor: "pointer", textAlign: "left", transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.06)"; }}
                    onMouseLeave={(e) => { if (categoryFilter !== cat) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >
                    {cat} <span style={{ color: T.textDim, fontFamily: T.fontMono, fontSize: 11 }}>({categoryCounts[cat]})</span>
                  </button>
                ))}
              </>
            )}
          </Dropdown>

          {/* Tag filter */}
          <Dropdown label={tagFilters.size > 0 ? `${tagFilters.size} tags` : "Filter by tag..."} width={200}>
            {() => (
              <>
                {ALL_TAGS.map((tag) => {
                  const active = tagFilters.has(tag);
                  return (
                    <button
                      key={tag}
                      onClick={() => toggleTag(tag)}
                      style={{
                        width: "100%", padding: "8px 12px", borderRadius: 6,
                        border: "none", background: active ? "rgba(255,255,255,0.06)" : "transparent",
                        color: T.text, fontSize: 12, fontFamily: T.fontSans,
                        cursor: "pointer", textAlign: "left", transition: "background 0.15s",
                        display: "flex", alignItems: "center", gap: 8,
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.06)"; }}
                      onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                    >
                      <div style={{
                        width: 14, height: 14, borderRadius: 3,
                        border: `1px solid ${active ? T.cyan : T.border}`,
                        background: active ? T.cyanDim : "transparent",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        transition: "all 0.15s",
                      }}>
                        {active && <Check size={9} color={T.cyan} />}
                      </div>
                      {tag}
                    </button>
                  );
                })}
              </>
            )}
          </Dropdown>

          {/* Selected tag pills */}
          {Array.from(tagFilters).map((tag) => (
            <span key={tag} style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              fontSize: 11, fontFamily: T.fontSans, fontWeight: 500,
              color: T.cyan, background: T.cyanDim,
              border: `1px solid ${T.cyanBorder}`,
              padding: "4px 10px", borderRadius: 20,
            }}>
              {tag}
              <X
                size={10}
                style={{ cursor: "pointer", opacity: 0.7 }}
                onClick={() => toggleTag(tag)}
              />
            </span>
          ))}

          {/* Competitor visibility pills */}
          <div style={{
            display: "flex", gap: 4, marginLeft: 4,
            borderLeft: `1px solid ${T.border}`, paddingLeft: 12,
          }}>
            {COMPETITORS.map((comp) => {
              const active = visibleCompetitors.has(comp.id);
              return (
                <button
                  key={comp.id}
                  onClick={() => toggleCompetitor(comp.id)}
                  title={comp.name}
                  style={{
                    display: "flex", alignItems: "center", gap: 5,
                    padding: "4px 10px", borderRadius: 20, fontSize: 11,
                    fontFamily: T.fontSans, fontWeight: 500, cursor: "pointer",
                    transition: "all 0.2s", border: `1px solid`,
                    borderColor: active ? comp.color + "66" : T.border,
                    background: active ? comp.color + "18" : "transparent",
                    color: active ? comp.color : T.textDim,
                  }}
                >
                  <span style={{
                    width: 8, height: 8, borderRadius: "50%",
                    background: active ? comp.color : T.textDim,
                    transition: "background 0.2s",
                  }} />
                  {comp.initial}
                </button>
              );
            })}
          </div>
        </div>

        {/* Right — Sort */}
        <Dropdown
          label={<><span style={{ color: T.textDim }}>Sort by:</span> {SORT_OPTIONS.find((s) => s.value === sortMode)?.label}</>}
          width={240}
        >
          {(close) => (
            <>
              {SORT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => { setSortMode(opt.value); setSortByCompetitor(null); close(); }}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: 6,
                    border: "none",
                    background: sortMode === opt.value && !sortByCompetitor ? "rgba(255,255,255,0.06)" : "transparent",
                    color: sortMode === opt.value && !sortByCompetitor ? T.cyan : T.text,
                    fontSize: 12, fontFamily: T.fontSans,
                    cursor: "pointer", textAlign: "left", transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.06)"; }}
                  onMouseLeave={(e) => { if (sortMode !== opt.value || sortByCompetitor) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  {opt.label}
                </button>
              ))}
            </>
          )}
        </Dropdown>
      </div>

      {/* Active filter summary */}
      {hasActiveFilters && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          marginBottom: 14, fontSize: 12, fontFamily: T.fontSans,
        }}>
          <span style={{ color: T.textMuted }}>
            Showing {filteredSorted.length} of {ALL_PRODUCTS.length} products
          </span>
          {categoryFilter && (
            <span style={{ color: T.textDim }}>
              — {categoryFilter}
            </span>
          )}
          {tagFilters.size > 0 && (
            <span style={{ color: T.textDim }}>
              · Tags: {Array.from(tagFilters).join(", ")}
            </span>
          )}
          <button
            onClick={() => { setCategoryFilter(null); setTagFilters(new Set()); }}
            style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 12, fontFamily: T.fontSans, color: T.cyan,
              padding: 0, textDecoration: "underline", textUnderlineOffset: 2,
            }}
          >
            Clear all
          </button>
        </div>
      )}

      {/* ═══════════════ THE MATRIX ═══════════════ */}
      <div
        className="ccm-table-scroll"
        style={{
          background: T.bgPanel,
          border: `1px solid ${T.border}`,
          borderRadius: 12,
          overflow: "auto",
          position: "relative",
          maxHeight: "calc(100vh - 280px)",
        }}
      >
        <table style={{
          width: "100%", borderCollapse: "separate", borderSpacing: 0,
          minWidth: 700 + visibleComps.length * 150,
        }}>
          {/* ── HEADER ── */}
          <thead>
            <tr>
              {/* Product Name header */}
              <th style={{
                position: "sticky", left: 0, top: 0, zIndex: 30,
                padding: "12px 16px", textAlign: "left",
                fontSize: 10, fontWeight: 600, fontFamily: T.fontSans,
                color: T.textDim, letterSpacing: "0.08em", textTransform: "uppercase",
                background: T.bgPanel, borderBottom: `1px solid ${T.border}`,
                borderRight: `1px solid ${T.border}`,
                width: 220, minWidth: 220,
              }}>
                Product Name
              </th>

              {/* SKU header */}
              <th style={{
                position: "sticky", top: 0, zIndex: 20,
                padding: "12px 12px", textAlign: "left",
                fontSize: 10, fontWeight: 600, fontFamily: T.fontSans,
                color: T.textDim, letterSpacing: "0.08em", textTransform: "uppercase",
                background: T.bgPanel, borderBottom: `1px solid ${T.border}`,
                borderRight: `1px solid ${T.border}`,
                width: 130, minWidth: 130,
              }}>
                SKU
              </th>

              {/* Your Price header */}
              <th style={{
                position: "sticky", top: 0, zIndex: 20,
                padding: "10px 16px", textAlign: "left",
                background: T.yourColBg,
                borderBottom: `1px solid ${T.border}`,
                borderLeft: `2px solid ${T.yourColBorder}`,
                borderRight: `1px solid ${T.border}`,
                width: 130, minWidth: 130,
              }}>
                <div style={{
                  display: "inline-block",
                  fontSize: 9, fontWeight: 700, fontFamily: T.fontMono,
                  color: T.bg, background: T.cyan,
                  padding: "2px 7px", borderRadius: 4,
                  letterSpacing: "0.08em", marginBottom: 4,
                }}>
                  YOU
                </div>
                <div style={{
                  fontSize: 10, fontWeight: 600, fontFamily: T.fontSans,
                  color: T.cyan, letterSpacing: "0.06em", textTransform: "uppercase",
                }}>
                  Your Price
                </div>
              </th>

              {/* Competitor headers */}
              {visibleComps.map((comp) => (
                <th
                  key={comp.id}
                  style={{
                    position: "sticky", top: 0, zIndex: 20,
                    padding: "10px 14px", textAlign: "left",
                    background: hoveredCol === comp.id ? "rgba(255,255,255,0.035)" : T.bgPanel,
                    borderBottom: `1px solid ${T.border}`,
                    borderTop: `2px solid ${comp.color}`,
                    borderRight: `1px solid ${T.border}`,
                    cursor: "pointer",
                    transition: "background 0.15s",
                    width: 150, minWidth: 150,
                  }}
                  onClick={() => {
                    setSortByCompetitor(sortByCompetitor === comp.id ? null : comp.id);
                  }}
                  onMouseEnter={() => setHoveredCol(comp.id)}
                  onMouseLeave={() => setHoveredCol(null)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                      width: 22, height: 22, borderRadius: "50%",
                      background: comp.color + "22", border: `1px solid ${comp.color}44`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, fontWeight: 700, fontFamily: T.fontSans,
                      color: comp.color, flexShrink: 0,
                    }}>
                      {comp.initial}
                    </div>
                    <div>
                      <div style={{
                        fontSize: 11, fontWeight: 600, fontFamily: T.fontSans,
                        color: hoveredCol === comp.id ? T.text : T.textMuted,
                        transition: "color 0.15s", lineHeight: 1.3,
                      }}>
                        {comp.name}
                      </div>
                      {sortByCompetitor === comp.id && (
                        <div style={{
                          fontSize: 9, fontFamily: T.fontMono, color: comp.color,
                          marginTop: 2,
                        }}>
                          ↕ sorted
                        </div>
                      )}
                    </div>
                  </div>
                </th>
              ))}

              {/* Spacer for hover link */}
              <th style={{
                position: "sticky", top: 0, zIndex: 20,
                background: T.bgPanel,
                borderBottom: `1px solid ${T.border}`,
                width: 60, minWidth: 60,
              }} />
            </tr>
          </thead>

          {/* ── BODY ── */}
          <tbody>
            {pageData.map((product, rowIdx) => {
              const isHovered = hoveredRow === product.id;
              return (
                <tr
                  key={product.id}
                  onMouseEnter={() => setHoveredRow(product.id)}
                  onMouseLeave={() => setHoveredRow(null)}
                  style={{ transition: "background 0.1s" }}
                >
                  {/* Product Name (sticky) */}
                  <td style={{
                    position: "sticky", left: 0, zIndex: 10,
                    padding: "12px 16px",
                    background: isHovered ? "#151A21" : (rowIdx % 2 === 1 ? "#0D1016" : T.bgPanel),
                    borderBottom: `1px solid ${T.border}`,
                    borderRight: `1px solid ${T.border}`,
                    borderLeft: isHovered ? `2px solid ${T.cyan}` : "2px solid transparent",
                    transition: "all 0.1s",
                  }}>
                    <div style={{ display: "flex", alignItems: "center" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 500, fontFamily: T.fontSans,
                          color: T.text, whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis",
                          maxWidth: 180,
                        }} title={product.name}>
                          {product.name}
                          <RowStatusIndicator product={product} visibleComps={visibleComps.map((c) => c.id)} />
                        </div>
                        <div style={{
                          fontSize: 10, fontFamily: T.fontSans, color: T.textDim,
                          marginTop: 2,
                        }}>
                          <span style={{
                            display: "inline-block",
                            fontSize: 9, fontFamily: T.fontSans,
                            color: T.textDim, background: "rgba(255,255,255,0.04)",
                            padding: "1px 6px", borderRadius: 3,
                          }}>
                            {product.category}
                          </span>
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* SKU */}
                  <td style={{
                    padding: "12px 12px",
                    background: isHovered ? "#151A21" : (rowIdx % 2 === 1 ? "#0D1016" : T.bgPanel),
                    borderBottom: `1px solid ${T.border}`,
                    borderRight: `1px solid ${T.border}`,
                    transition: "background 0.1s",
                  }}>
                    <span style={{
                      fontSize: 11, fontFamily: T.fontMono, color: T.textDim,
                      letterSpacing: "0.01em",
                    }}>
                      {product.sku}
                    </span>
                  </td>

                  {/* Your Price */}
                  <td style={{
                    padding: "12px 16px",
                    background: isHovered ? "rgba(10,26,38,0.8)" : T.yourColBg,
                    borderBottom: `1px solid ${T.border}`,
                    borderLeft: `2px solid ${T.yourColBorder}`,
                    borderRight: `1px solid ${T.border}`,
                    transition: "background 0.1s",
                  }}>
                    <span style={{
                      fontSize: 14, fontWeight: 600, fontFamily: T.fontMono,
                      color: T.cyan, letterSpacing: "-0.01em",
                    }}>
                      {fmtPrice(product.yourPrice)}
                    </span>
                  </td>

                  {/* Competitor cells */}
                  {visibleComps.map((comp) => {
                    const cp = product.competitors[comp.id];
                    const hasData = cp?.price != null;
                    const style = getCellStyle(cp?.diffPct ?? null);
                    const isColHovered = hoveredCol === comp.id;

                    return (
                      <td
                        key={comp.id}
                        onMouseEnter={() => setHoveredCol(comp.id)}
                        onMouseLeave={() => setHoveredCol(null)}
                        style={{
                          padding: hasData ? "10px 14px" : "12px 14px",
                          background: isColHovered
                            ? `color-mix(in srgb, ${style.bg} 85%, rgba(255,255,255,0.03))`
                            : isHovered
                            ? `color-mix(in srgb, ${style.bg} 90%, rgba(255,255,255,0.03))`
                            : style.bg,
                          borderBottom: `1px solid ${T.border}`,
                          borderRight: `1px solid ${T.border}`,
                          transition: "background 0.1s",
                          textAlign: hasData ? "left" : "center",
                        }}
                      >
                        {hasData ? (
                          <>
                            <div style={{
                              fontSize: 13, fontFamily: T.fontMono, fontWeight: 500,
                              color: style.text, lineHeight: 1.3,
                            }}>
                              {fmtPrice(cp.price!)}
                            </div>
                            <div style={{ marginTop: 4 }}>
                              <DiffBadge diffPct={cp.diffPct!} />
                            </div>
                          </>
                        ) : (
                          <span style={{
                            fontSize: 14, color: T.textDim, fontFamily: T.fontMono,
                          }}>
                            —
                          </span>
                        )}
                      </td>
                    );
                  })}

                  {/* Hover action */}
                  <td style={{
                    padding: "12px 8px",
                    background: isHovered ? "#151A21" : (rowIdx % 2 === 1 ? "#0D1016" : T.bgPanel),
                    borderBottom: `1px solid ${T.border}`,
                    transition: "background 0.1s",
                    textAlign: "center",
                  }}>
                    <span style={{
                      opacity: isHovered ? 1 : 0,
                      transition: "opacity 0.15s",
                      fontSize: 11, fontFamily: T.fontSans, fontWeight: 500,
                      color: T.cyan, whiteSpace: "nowrap", cursor: "pointer",
                    }}>
                      View →
                    </span>
                  </td>
                </tr>
              );
            })}

            {/* ── SUMMARY / AVERAGES ROW ── */}
            <tr>
              <td style={{
                position: "sticky", left: 0, zIndex: 10,
                padding: "12px 16px",
                background: "rgba(255,255,255,0.025)",
                borderTop: `1px solid ${T.borderHover}`,
                borderRight: `1px solid ${T.border}`,
              }}>
                <span style={{
                  fontSize: 11, fontWeight: 600, fontFamily: T.fontSans,
                  color: T.textMuted, letterSpacing: "0.04em", textTransform: "uppercase",
                }}>
                  Averages
                </span>
              </td>
              <td style={{
                padding: "12px 12px",
                background: "rgba(255,255,255,0.025)",
                borderTop: `1px solid ${T.borderHover}`,
                borderRight: `1px solid ${T.border}`,
              }} />
              <td style={{
                padding: "12px 16px",
                background: "rgba(10,26,38,0.6)",
                borderTop: `1px solid ${T.borderHover}`,
                borderLeft: `2px solid ${T.yourColBorder}`,
                borderRight: `1px solid ${T.border}`,
              }}>
                <span style={{
                  fontSize: 11, fontFamily: T.fontMono, color: T.cyan, fontWeight: 600,
                }}>
                  REF
                </span>
              </td>
              {visibleComps.map((comp) => {
                const avg = averages[comp.id];
                const style = getCellStyle(avg);
                return (
                  <td key={comp.id} style={{
                    padding: "12px 14px",
                    background: style.bg,
                    borderTop: `1px solid ${T.borderHover}`,
                    borderRight: `1px solid ${T.border}`,
                  }}>
                    {avg != null ? (
                      <DiffBadge diffPct={Math.round(avg * 10) / 10} />
                    ) : (
                      <span style={{ fontSize: 14, color: T.textDim, fontFamily: T.fontMono }}>—</span>
                    )}
                  </td>
                );
              })}
              <td style={{
                background: "rgba(255,255,255,0.025)",
                borderTop: `1px solid ${T.borderHover}`,
              }} />
            </tr>
          </tbody>
        </table>
      </div>

      {/* ═══════════════ PAGINATION ═══════════════ */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginTop: 16, flexWrap: "wrap", gap: 12,
      }}>
        <span style={{
          fontSize: 12, fontFamily: T.fontMono, color: T.textDim,
        }}>
          Showing {pageStart + 1}–{pageEnd} of {totalProducts} products
        </span>

        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button
            onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
            style={{
              padding: "6px 12px", borderRadius: 6,
              border: `1px solid ${T.border}`,
              background: "transparent",
              color: currentPage === 1 ? T.textDim : T.textMuted,
              fontSize: 12, fontFamily: T.fontSans, fontWeight: 500,
              cursor: currentPage === 1 ? "default" : "pointer",
              transition: "all 0.15s", opacity: currentPage === 1 ? 0.5 : 1,
            }}
          >
            Previous
          </button>

          {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
            <button
              key={page}
              onClick={() => setCurrentPage(page)}
              style={{
                width: 32, height: 32, borderRadius: 6,
                border: `1px solid ${page === currentPage ? T.cyanBorder : T.border}`,
                background: page === currentPage ? T.cyanDim : "transparent",
                color: page === currentPage ? T.cyan : T.textMuted,
                fontSize: 12, fontFamily: T.fontMono, fontWeight: 600,
                cursor: "pointer", transition: "all 0.15s",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              {page}
            </button>
          ))}

          <button
            onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
            style={{
              padding: "6px 12px", borderRadius: 6,
              border: `1px solid ${T.border}`,
              background: "transparent",
              color: currentPage === totalPages ? T.textDim : T.textMuted,
              fontSize: 12, fontFamily: T.fontSans, fontWeight: 500,
              cursor: currentPage === totalPages ? "default" : "pointer",
              transition: "all 0.15s", opacity: currentPage === totalPages ? 0.5 : 1,
            }}
          >
            Next
          </button>
        </div>
      </div>

      {/* ═══════════════ TOAST ═══════════════ */}
      <Toast
        message={`✓ ${toastMessage}`}
        visible={toastVisible}
        onDone={() => setToastVisible(false)}
      />

      {/* Spin animation for loader */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default CompetitorComparisonMatrix;
