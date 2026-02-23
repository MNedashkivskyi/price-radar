"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import {
  X,
  Download,
  Check,
  AlertTriangle,
  RefreshCw,
  Copy,
  FileSpreadsheet,
  FileText,
  Loader2,
  ChevronDown,
  Trash2,
} from "lucide-react";

/* ═══════════════════════════════════════════════
   CONSTANTS & TYPES
   ═══════════════════════════════════════════════ */

const C = {
  bg: "#090B0F",
  panel: "#0C0F14",
  panelBorder: "rgba(255,255,255,0.05)",
  cardBorder: "rgba(255,255,255,0.08)",
  queued: "#4A5166",
  processing: "#00D4FF",
  complete: "#3DD68C",
  failed: "#FF6B6B",
  warning: "#F0A429",
  csv: "#3DD68C",
  xlsx: "#1D6F42",
  text: "#E2E8F0",
  textLight: "#CBD5E1",
  muted: "#8B92A5",
  timestamp: "#4A5166",
  rowHover: "rgba(255,255,255,0.03)",
};

const FM = "'JetBrains Mono', 'Fira Code', ui-monospace, monospace";
const FS = "'DM Sans', 'Inter', ui-sans-serif, system-ui, sans-serif";

type ExportFormat = "csv" | "xlsx";
type JobStatus = "queued" | "processing" | "complete" | "failed";
type ExportType = "products" | "comparison-matrix" | "price-history";
type TabFilter = "all" | "active" | "completed" | "failed";

interface ExportJob {
  id: string;
  type: ExportType;
  name: string;
  scope: string;
  status: JobStatus;
  progress: number;
  rowCount: number;
  fileSize: number;
  format: ExportFormat;
  createdAt: number;
  completedAt?: number;
  downloadUrl?: string;
  downloaded: boolean;
  error?: string;
  queuePosition?: number;
  email: string;
  filters: string[];
}

interface Toast {
  id: string;
  type: "started" | "complete" | "instant" | "failed";
  title: string;
  body: string;
  jobId?: string;
  createdAt: number;
  duration: number;
  paused: boolean;
}

/* ═══════════════════════════════════════════════
   MOCK DATA
   ═══════════════════════════════════════════════ */

function generateMockJobs(): ExportJob[] {
  const now = Date.now();
  return [
    {
      id: "EXP-2851",
      type: "comparison-matrix",
      name: "Comparison Matrix — Electronics · 3 Competitors",
      scope: "Electronics category, 3 competitors selected",
      status: "queued",
      progress: 0,
      rowCount: 3210,
      fileSize: 4200000,
      format: "xlsx",
      createdAt: now - 45000,
      downloaded: false,
      queuePosition: 2,
      email: "analyst@company.com",
      filters: ["Electronics", "TechDirect Pro", "PriceWars Global", "MegaMart"],
    },
    {
      id: "EXP-2850",
      type: "products",
      name: "Products Export — All Categories",
      scope: "All products with price history",
      status: "processing",
      progress: 34,
      rowCount: 7410,
      fileSize: 8900000,
      format: "csv",
      createdAt: now - 180000,
      downloaded: false,
      email: "analyst@company.com",
      filters: ["All categories", "Price history 30d"],
    },
    {
      id: "EXP-2849",
      type: "comparison-matrix",
      name: "Comparison Matrix — Audio · 5 Competitors",
      scope: "Audio & Headphones, all competitors",
      status: "processing",
      progress: 78,
      rowCount: 2847,
      fileSize: 3200000,
      format: "csv",
      createdAt: now - 420000,
      downloaded: false,
      email: "analyst@company.com",
      filters: ["Audio", "Headphones"],
    },
    {
      id: "EXP-2848",
      type: "products",
      name: "Products Export — Smart Home Devices",
      scope: "Smart Home category, current prices + metadata",
      status: "complete",
      progress: 100,
      rowCount: 1503,
      fileSize: 1800000,
      format: "xlsx",
      createdAt: now - 300000,
      completedAt: now - 280000,
      downloadUrl: "#mock-download-2848",
      downloaded: false,
      email: "analyst@company.com",
      filters: ["Smart Home"],
    },
    {
      id: "EXP-2845",
      type: "comparison-matrix",
      name: "Comparison Matrix — Full Catalog",
      scope: "All products, all competitors",
      status: "complete",
      progress: 100,
      rowCount: 12450,
      fileSize: 18700000,
      format: "csv",
      createdAt: now - 7200000,
      completedAt: now - 7020000,
      downloadUrl: "#mock-download-2845",
      downloaded: false,
      email: "analyst@company.com",
      filters: ["Full catalog"],
    },
    {
      id: "EXP-2842",
      type: "price-history",
      name: "Price History — Sony WH-1000XM5 · 90 days",
      scope: "Single product, 90-day history",
      status: "complete",
      progress: 100,
      rowCount: 450,
      fileSize: 89000,
      format: "csv",
      createdAt: now - 86400000,
      completedAt: now - 86380000,
      downloadUrl: "#mock-download-2842",
      downloaded: true,
      email: "analyst@company.com",
      filters: ["SKU: SNY-WH1000XM5"],
    },
    {
      id: "EXP-2840",
      type: "products",
      name: "Products Export — Laptops · With History",
      scope: "Laptops, 30-day price history included",
      status: "failed",
      progress: 42,
      rowCount: 5280,
      fileSize: 0,
      format: "xlsx",
      createdAt: now - 3600000,
      downloaded: false,
      error: "Timeout: Export job exceeded 5 minute limit.\nRows processed: 2,218 / 5,280 before failure.\nSuggestion: Try exporting with filters to reduce dataset size.",
      email: "analyst@company.com",
      filters: ["Laptops", "Price history 30d"],
    },
    {
      id: "EXP-2838",
      type: "comparison-matrix",
      name: "Comparison Matrix — Phones · 2 Competitors",
      scope: "Phones category, Samsung + Apple comparison",
      status: "complete",
      progress: 100,
      rowCount: 890,
      fileSize: 1200000,
      format: "csv",
      createdAt: now - 86400000 * 2,
      completedAt: now - 86400000 * 2 + 60000,
      downloadUrl: "#mock-download-2838",
      downloaded: true,
      email: "analyst@company.com",
      filters: ["Phones", "Samsung", "Apple"],
    },
  ];
}

/* ═══════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════ */

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatRelativeTime(ts: number): string {
  const diff = Date.now() - ts;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) {
    const d = new Date(ts);
    return `Yesterday at ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  return `${days}d ago`;
}

function formatCountdown(expiresAt: number): string {
  const diff = expiresAt - Date.now();
  if (diff <= 0) return "Expired";
  const hrs = Math.floor(diff / 3600000);
  const min = Math.floor((diff % 3600000) / 60000);
  return `${hrs}h ${String(min).padStart(2, "0")}m`;
}

function estimateRows(type: ExportType, options: Record<string, boolean>): number {
  let base = 0;
  if (type === "products") base = 247;
  else if (type === "comparison-matrix") base = 1235;
  else base = 90;

  if (options.priceHistory && type !== "price-history") base *= 30;
  if (options.stockStatus) base = Math.ceil(base * 1.1);
  return base;
}

function estimateFileSize(rows: number, format: ExportFormat): number {
  const perRow = format === "csv" ? 180 : 340;
  return rows * perRow;
}

let toastIdCounter = 0;

/* ═══════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════ */

export function ExportSystem() {
  // --- State ---
  const [jobs, setJobs] = useState<ExportJob[]>(() => generateMockJobs());
  const [activeTab, setActiveTab] = useState<TabFilter>("all");
  const [showExportModal, setShowExportModal] = useState(false);
  const [modalContext, setModalContext] = useState<ExportType>("products");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [exportFormat, setExportFormat] = useState<ExportFormat>("csv");
  const [exportOptions, setExportOptions] = useState<Record<string, boolean>>({
    currentPrices: true,
    priceDiffs: true,
    competitorNames: true,
    priceHistory: false,
    stockStatus: false,
    metadata: false,
  });
  const [historyRange, setHistoryRange] = useState<string>("30d");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [, setTick] = useState(0); // For countdown re-renders

  const modalRef = useRef<HTMLDivElement>(null);

  // --- Countdown ticker ---
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 60000);
    return () => clearInterval(interval);
  }, []);

  // --- Simulated progress for processing jobs ---
  useEffect(() => {
    const interval = setInterval(() => {
      setJobs((prev) =>
        prev.map((job) => {
          if (job.status === "processing") {
            const increment = 1 + Math.random() * 2;
            const newProgress = Math.min(100, job.progress + increment);
            if (newProgress >= 100) {
              addToast("complete", `${job.name}`, `${job.rowCount.toLocaleString()} rows · ${formatBytes(job.fileSize)}`, job.id);
              return {
                ...job,
                status: "complete" as JobStatus,
                progress: 100,
                completedAt: Date.now(),
                downloadUrl: `#mock-download-${job.id}`,
              };
            }
            return { ...job, progress: newProgress };
          }
          return job;
        })
      );
    }, 800);
    return () => clearInterval(interval);
  }, []);

  // --- Simulated queue: auto-start queued job after 3s ---
  useEffect(() => {
    const timer = setTimeout(() => {
      setJobs((prev) =>
        prev.map((job) => (job.status === "queued" ? { ...job, status: "processing" as JobStatus, queuePosition: undefined } : job))
      );
    }, 3000);
    return () => clearTimeout(timer);
  }, []);

  // --- Toast auto-dismiss ---
  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((t) => {
      if (t.paused) return null;
      return setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== t.id));
      }, t.duration);
    });
    return () => timers.forEach((t) => t && clearTimeout(t));
  }, [toasts]);

  // --- Helpers ---
  const addToast = useCallback((type: Toast["type"], title: string, body: string, jobId?: string) => {
    const id = `toast-${++toastIdCounter}`;
    const duration = type === "complete" ? 12000 : type === "failed" ? 10000 : type === "started" ? 6000 : 4000;
    setToasts((prev) => [{ id, type, title, body, jobId, createdAt: Date.now(), duration, paused: false }, ...prev]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pauseToast = useCallback((id: string, paused: boolean) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, paused } : t)));
  }, []);

  // --- Derived data ---
  const estimatedRows = useMemo(() => estimateRows(modalContext, exportOptions), [modalContext, exportOptions]);
  const estimatedSize = useMemo(() => estimateFileSize(estimatedRows, exportFormat), [estimatedRows, exportFormat]);
  const isAsync = estimatedRows > 1000;

  const activeJobCount = useMemo(() => jobs.filter((j) => j.status === "queued" || j.status === "processing").length, [jobs]);

  const filteredJobs = useMemo(() => {
    let filtered = [...jobs];
    if (activeTab === "active") filtered = filtered.filter((j) => j.status === "queued" || j.status === "processing");
    else if (activeTab === "completed") filtered = filtered.filter((j) => j.status === "complete");
    else if (activeTab === "failed") filtered = filtered.filter((j) => j.status === "failed");
    // Sort: active first, then by createdAt
    return filtered.sort((a, b) => {
      const aActive = a.status === "queued" || a.status === "processing" ? 0 : 1;
      const bActive = b.status === "queued" || b.status === "processing" ? 0 : 1;
      if (aActive !== bActive) return aActive - bActive;
      return b.createdAt - a.createdAt;
    });
  }, [jobs, activeTab]);

  const historyJobs = useMemo(
    () => jobs.filter((j) => j.status === "complete" || j.status === "failed").sort((a, b) => b.createdAt - a.createdAt),
    [jobs]
  );

  // --- Actions ---
  const openModal = useCallback((type: ExportType) => {
    setModalContext(type);
    setShowExportModal(true);
    setExportFormat("csv");
    setExportOptions({ currentPrices: true, priceDiffs: true, competitorNames: true, priceHistory: false, stockStatus: false, metadata: false });
  }, []);

  const startExport = useCallback(() => {
    if (!isAsync) {
      // Instant download
      const rows = Array.from({ length: Math.min(estimatedRows, 50) }, (_, i) => `Product ${i + 1},Competitor A,$${(99.99 + i).toFixed(2)},$${(89.99 + i).toFixed(2)},-${(5 + Math.random() * 10).toFixed(1)}%`);
      const csv = "Product,Competitor,Your Price,Their Price,Difference\n" + rows.join("\n");
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const dateStr = new Date().toISOString().slice(0, 10);
      a.download = `${modalContext}-${dateStr}.${exportFormat}`;
      a.click();
      URL.revokeObjectURL(url);
      addToast("instant", "Downloaded", `${modalContext}-${dateStr}.${exportFormat} · ${estimatedRows.toLocaleString()} rows`);
      setShowExportModal(false);
    } else {
      // Async job
      const newId = `EXP-${2852 + jobs.length}`;
      const typeNames: Record<ExportType, string> = {
        products: "Products Export",
        "comparison-matrix": "Comparison Matrix",
        "price-history": "Price History",
      };
      const newJob: ExportJob = {
        id: newId,
        type: modalContext,
        name: `${typeNames[modalContext]} — Custom Export`,
        scope: Object.entries(exportOptions)
          .filter(([, v]) => v)
          .map(([k]) => k)
          .join(", "),
        status: "queued",
        progress: 0,
        rowCount: estimatedRows,
        fileSize: estimatedSize,
        format: exportFormat,
        createdAt: Date.now(),
        downloaded: false,
        queuePosition: 1,
        email: "analyst@company.com",
        filters: [],
      };
      setJobs((prev) => [newJob, ...prev]);
      addToast("started", "Export started", `${typeNames[modalContext]} · ${estimatedRows.toLocaleString()} rows · Processing in background`, newId);
      // Auto-start processing after 2s
      setTimeout(() => {
        setJobs((prev) =>
          prev.map((j) => (j.id === newId ? { ...j, status: "processing" as JobStatus, queuePosition: undefined } : j))
        );
      }, 2000);
      setShowExportModal(false);
    }
  }, [isAsync, estimatedRows, estimatedSize, exportFormat, modalContext, exportOptions, jobs.length, addToast]);

  const retryJob = useCallback((jobId: string) => {
    setJobs((prev) =>
      prev.map((j) => (j.id === jobId ? { ...j, status: "queued" as JobStatus, progress: 0, error: undefined, queuePosition: 1 } : j))
    );
    setTimeout(() => {
      setJobs((prev) =>
        prev.map((j) => (j.id === jobId && j.status === "queued" ? { ...j, status: "processing" as JobStatus, queuePosition: undefined } : j))
      );
    }, 2000);
  }, []);

  const cancelJob = useCallback((jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.id !== jobId));
  }, []);

  const downloadJob = useCallback((jobId: string) => {
    const job = jobs.find((j) => j.id === jobId);
    if (!job) return;
    // Mock download
    const csv = `"Mock CSV data for ${job.name}"\nRow 1\nRow 2\n`;
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${job.type}-${new Date(job.createdAt).toISOString().slice(0, 10)}.${job.format}`;
    a.click();
    URL.revokeObjectURL(url);
    setJobs((prev) => prev.map((j) => (j.id === jobId ? { ...j, downloaded: true } : j)));
  }, [jobs]);

  const copyLink = useCallback((jobId: string) => {
    navigator.clipboard?.writeText(`https://app.priceradar.io/exports/download/${jobId}`);
    setCopiedId(jobId);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const clearCompleted = useCallback(() => {
    setJobs((prev) => prev.filter((j) => j.status !== "complete" && j.status !== "failed"));
  }, []);

  const toggleError = useCallback((jobId: string) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }, []);

  const toggleOption = useCallback((key: string) => {
    setExportOptions((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  /* ═══════════════════════════════════════════════
     STATUS BADGE
     ═══════════════════════════════════════════════ */
  function StatusBadge({ job }: { job: ExportJob }) {
    const statusConfig: Record<JobStatus, { color: string; bg: string; border: string; icon: React.ReactNode; label: string }> = {
      queued: {
        color: C.queued,
        bg: "rgba(74,81,102,0.15)",
        border: "rgba(74,81,102,0.3)",
        icon: <span>⏳</span>,
        label: `Queued${job.queuePosition ? ` · Position ${job.queuePosition}` : ""}`,
      },
      processing: {
        color: C.processing,
        bg: "rgba(0,212,255,0.15)",
        border: "rgba(0,212,255,0.3)",
        icon: <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />,
        label: `Processing · ${Math.floor(job.progress)}%`,
      },
      complete: {
        color: C.complete,
        bg: "rgba(61,214,140,0.15)",
        border: "rgba(61,214,140,0.3)",
        icon: <Check size={12} />,
        label: "Ready · Download available",
      },
      failed: {
        color: C.failed,
        bg: "rgba(255,107,107,0.15)",
        border: "rgba(255,107,107,0.3)",
        icon: <X size={12} />,
        label: "Failed · Retry available",
      },
    };
    const cfg = statusConfig[job.status];
    return (
      <span
        style={{
          fontFamily: FS,
          fontSize: 11,
          fontWeight: 500,
          padding: "3px 8px",
          borderRadius: 4,
          background: cfg.bg,
          border: `1px solid ${cfg.border}`,
          color: cfg.color,
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          whiteSpace: "nowrap",
        }}
      >
        {cfg.icon}
        {cfg.label}
      </span>
    );
  }

  /* ═══════════════════════════════════════════════
     FORMAT PILL
     ═══════════════════════════════════════════════ */
  function FormatPill({ format }: { format: ExportFormat }) {
    const isCSV = format === "csv";
    return (
      <span
        style={{
          fontFamily: FM,
          fontSize: 10,
          fontWeight: 600,
          padding: "2px 6px",
          borderRadius: 3,
          background: isCSV ? "rgba(61,214,140,0.12)" : "rgba(29,111,66,0.15)",
          color: isCSV ? C.csv : C.xlsx,
          border: `1px solid ${isCSV ? "rgba(61,214,140,0.25)" : "rgba(29,111,66,0.3)"}`,
          textTransform: "uppercase",
        }}
      >
        {format}
      </span>
    );
  }

  /* ═══════════════════════════════════════════════
     JOB CARD
     ═══════════════════════════════════════════════ */
  function JobCard({ job }: { job: ExportJob }) {
    const expiresAt = (job.completedAt || 0) + 24 * 3600000;
    const isExpired = job.status === "complete" && Date.now() > expiresAt;

    return (
      <div
        style={{
          background: job.status === "complete" ? "rgba(61,214,140,0.03)" : C.panel,
          border: `1px solid ${C.cardBorder}`,
          borderLeft: job.status === "complete"
            ? `3px solid ${job.downloaded ? "rgba(61,214,140,0.1)" : "rgba(61,214,140,0.3)"}`
            : job.status === "failed"
              ? `3px solid rgba(255,107,107,0.3)`
              : `3px solid transparent`,
          borderRadius: 8,
          padding: 16,
          marginBottom: 10,
          animation: "slideUp 0.3s ease both",
        }}
      >
        {/* Top row: format + name + status */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flex: 1, minWidth: 0 }}>
            <FormatPill format={job.format} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: FS, fontSize: 14, fontWeight: 500, color: C.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {job.name}
              </div>
              <div style={{ fontFamily: FM, fontSize: 11, color: C.muted, marginTop: 3 }}>
                {job.rowCount.toLocaleString()} rows · {formatBytes(job.fileSize)} · {job.format.toUpperCase()}
              </div>
            </div>
          </div>
          <StatusBadge job={job} />
        </div>

        {/* Filter pills */}
        {job.filters.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
            {job.filters.map((f, i) => (
              <span key={i} style={{ fontFamily: FS, fontSize: 10, padding: "1px 6px", borderRadius: 10, background: "rgba(255,255,255,0.04)", color: C.muted, border: `1px solid ${C.panelBorder}` }}>
                {f}
              </span>
            ))}
          </div>
        )}

        {/* Progress bar (processing only) */}
        {job.status === "processing" && (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontFamily: FM, fontSize: 11, color: C.muted }}>
                Processing rows {Math.floor((job.progress / 100) * job.rowCount).toLocaleString()} of {job.rowCount.toLocaleString()}
              </span>
              <span style={{ fontFamily: FM, fontSize: 11, color: C.processing }}>{Math.floor(job.progress)}%</span>
            </div>
            <div style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,0.06)", overflow: "hidden", position: "relative" }}>
              <div
                style={{
                  height: "100%",
                  borderRadius: 2,
                  background: C.processing,
                  width: `${job.progress}%`,
                  transition: "width 0.6s ease",
                  position: "relative",
                  overflow: "hidden",
                }}
              >
                <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent)", animation: "shimmer 1.5s infinite" }} />
              </div>
            </div>
            <div style={{ fontFamily: FM, fontSize: 10, color: C.timestamp, marginTop: 3, textAlign: "right" }}>
              ~{Math.max(1, Math.ceil(((100 - job.progress) / 2) * 0.8))}s remaining
            </div>
          </div>
        )}

        {/* Metadata + actions */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, flexWrap: "wrap", gap: 8 }}>
          <span style={{ fontFamily: FM, fontSize: 11, color: C.timestamp }}>
            Job #{job.id} · Started {formatRelativeTime(job.createdAt)} · by {job.email}
          </span>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {(job.status === "queued" || job.status === "processing") && (
              <button onClick={() => cancelJob(job.id)} style={{ fontFamily: FS, fontSize: 12, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>
                Cancel
              </button>
            )}

            {job.status === "complete" && (
              <>
                <button
                  onClick={() => downloadJob(job.id)}
                  style={{
                    fontFamily: FS,
                    fontSize: 12,
                    fontWeight: 600,
                    padding: "6px 14px",
                    borderRadius: 6,
                    background: job.downloaded ? "rgba(61,214,140,0.08)" : C.complete,
                    color: job.downloaded ? C.complete : "#000",
                    border: job.downloaded ? `1px solid rgba(61,214,140,0.25)` : "none",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    animation: !job.downloaded ? "scalePulse 0.4s ease" : "none",
                    transition: "all 0.15s",
                  }}
                >
                  <Download size={13} />
                  {job.downloaded ? "Downloaded" : "Download"}
                </button>
                <button
                  onClick={() => copyLink(job.id)}
                  style={{ fontFamily: FS, fontSize: 12, color: copiedId === job.id ? C.complete : C.muted, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 3 }}
                >
                  {copiedId === job.id ? <Check size={12} /> : <Copy size={12} />}
                  {copiedId === job.id ? "Copied" : "Copy link"}
                </button>
                {!isExpired && (
                  <span style={{ fontFamily: FM, fontSize: 10, color: C.warning }}>
                    Expires in {formatCountdown(expiresAt)}
                  </span>
                )}
              </>
            )}

            {job.status === "failed" && (
              <>
                <button
                  onClick={() => retryJob(job.id)}
                  style={{ fontFamily: FS, fontSize: 12, padding: "5px 12px", borderRadius: 6, background: "transparent", border: `1px solid rgba(0,212,255,0.3)`, color: C.processing, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}
                >
                  <RefreshCw size={12} />
                  Retry
                </button>
                <button
                  onClick={() => toggleError(job.id)}
                  style={{ fontFamily: FS, fontSize: 12, color: C.muted, background: "none", border: "none", cursor: "pointer" }}
                >
                  {expandedErrors.has(job.id) ? "Hide error" : "View error"}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Error expansion */}
        {job.status === "failed" && expandedErrors.has(job.id) && job.error && (
          <div
            style={{
              marginTop: 12,
              padding: 12,
              background: "#0A0E14",
              borderRadius: 6,
              borderLeft: `3px solid ${C.failed}`,
              fontFamily: FM,
              fontSize: 11,
              color: C.muted,
              whiteSpace: "pre-wrap",
              lineHeight: 1.6,
            }}
          >
            <div style={{ fontFamily: FS, fontSize: 11, fontWeight: 600, color: C.failed, marginBottom: 6 }}>Error details</div>
            {job.error}
          </div>
        )}
      </div>
    );
  }

  /* ═══════════════════════════════════════════════
     RENDER
     ═══════════════════════════════════════════════ */
  return (
    <div style={{ background: C.bg, minHeight: "100vh", color: C.text }}>
      <style>{`
        @keyframes slideUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        @keyframes scalePulse { 0% { transform: scale(1); } 50% { transform: scale(1.05); } 100% { transform: scale(1); } }
        @keyframes toastSlide { from { transform: translateX(calc(100% + 24px)); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
      `}</style>

      {/* ─── PAGE HEADER ─── */}
      <div style={{ padding: "24px 24px 0", display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontFamily: FS, fontSize: 28, fontWeight: 700, color: "#fff", margin: 0 }}>Export Jobs</h1>
            {activeJobCount > 0 && (
              <span style={{ fontFamily: FM, fontSize: 11, padding: "3px 8px", borderRadius: 10, background: "rgba(0,212,255,0.15)", color: C.processing, border: `1px solid rgba(0,212,255,0.3)`, animation: "pulse 2s infinite" }}>
                {activeJobCount} active
              </span>
            )}
          </div>
          <p style={{ fontFamily: FM, fontSize: 13, color: C.muted, marginTop: 4 }}>
            {jobs.length} total exports · {jobs.filter((j) => j.status === "complete").length} ready for download
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={clearCompleted}
            style={{ fontFamily: FS, fontSize: 13, color: C.muted, background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}
          >
            <Trash2 size={14} /> Clear completed
          </button>
          <button
            onClick={() => openModal("products")}
            style={{ fontFamily: FS, fontSize: 13, padding: "8px 16px", borderRadius: 6, background: C.processing, color: "#000", fontWeight: 600, border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
          >
            <Download size={14} /> New Export
          </button>
        </div>
      </div>

      {/* ─── EXPORT TYPE QUICK ACTIONS ─── */}
      <div style={{ padding: "16px 24px", display: "flex", gap: 10, flexWrap: "wrap" }}>
        {([
          { type: "products" as ExportType, label: "Products List", icon: <FileText size={14} />, desc: "All tracked products" },
          { type: "comparison-matrix" as ExportType, label: "Comparison Matrix", icon: <FileSpreadsheet size={14} />, desc: "Product × competitor grid" },
          { type: "price-history" as ExportType, label: "Price History", icon: <FileSpreadsheet size={14} />, desc: "Single product timeline" },
        ]).map(({ type, label, icon, desc }) => (
          <button
            key={type}
            onClick={() => openModal(type)}
            style={{
              fontFamily: FS,
              fontSize: 13,
              padding: "12px 16px",
              borderRadius: 8,
              background: C.panel,
              border: `1px solid ${C.cardBorder}`,
              color: C.text,
              cursor: "pointer",
              textAlign: "left",
              display: "flex",
              alignItems: "center",
              gap: 10,
              transition: "all 0.15s",
              minWidth: 200,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(0,212,255,0.3)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.cardBorder; }}
          >
            <div style={{ color: C.processing }}>{icon}</div>
            <div>
              <div style={{ fontWeight: 500 }}>{label}</div>
              <div style={{ fontSize: 11, color: C.muted, marginTop: 1 }}>{desc}</div>
            </div>
          </button>
        ))}
      </div>

      {/* ─── FILTER TABS ─── */}
      <div style={{ padding: "0 24px 16px", display: "flex", gap: 0, borderBottom: `1px solid ${C.panelBorder}` }}>
        {([
          { key: "all" as TabFilter, label: "All" },
          { key: "active" as TabFilter, label: `Active (${activeJobCount})` },
          { key: "completed" as TabFilter, label: "Completed" },
          { key: "failed" as TabFilter, label: "Failed" },
        ]).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              fontFamily: FS,
              fontSize: 13,
              fontWeight: 500,
              padding: "8px 16px",
              color: activeTab === key ? C.processing : C.muted,
              background: "none",
              border: "none",
              borderBottom: activeTab === key ? `2px solid ${C.processing}` : "2px solid transparent",
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ─── JOB CARDS ─── */}
      <div style={{ padding: "16px 24px" }}>
        {filteredJobs.length === 0 ? (
          <div style={{ textAlign: "center", padding: "60px 24px" }}>
            <Download size={40} color={C.timestamp} style={{ margin: "0 auto 12px", display: "block", opacity: 0.4 }} />
            <p style={{ fontFamily: FS, fontSize: 15, color: C.muted }}>No export jobs in this category</p>
            <p style={{ fontFamily: FS, fontSize: 12, color: C.timestamp, marginTop: 4 }}>Start a new export to see it here</p>
          </div>
        ) : (
          filteredJobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
      </div>

      {/* ─── EXPORT HISTORY TABLE ─── */}
      {historyJobs.length > 0 && (
        <div style={{ padding: "0 24px 40px" }}>
          <h2 style={{ fontFamily: FS, fontSize: 16, fontWeight: 600, color: C.text, margin: "24px 0 12px" }}>Export History</h2>
          <div style={{ background: C.panel, borderRadius: 8, border: `1px solid ${C.panelBorder}`, overflow: "hidden" }}>
            {/* Table header */}
            <div style={{ display: "flex", padding: "10px 16px", borderBottom: `1px solid ${C.panelBorder}`, gap: 0 }}>
              {["Job ID", "Export Type", "Rows", "Format", "Status", "Date", "Action"].map((h, i) => (
                <div
                  key={h}
                  style={{
                    fontFamily: FS,
                    fontSize: 11,
                    fontWeight: 600,
                    color: C.timestamp,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    width: i === 0 ? 90 : i === 1 ? "1fr" : i === 2 ? 80 : i === 3 ? 60 : i === 4 ? 90 : i === 5 ? 120 : 80,
                    flex: i === 1 ? 1 : "none",
                    flexShrink: 0,
                    textAlign: i === 2 ? "right" : "left",
                    paddingRight: 8,
                  }}
                >
                  {h}
                </div>
              ))}
            </div>
            {/* Table rows */}
            {historyJobs.map((job) => (
              <div
                key={job.id}
                style={{
                  display: "flex",
                  padding: "10px 16px",
                  borderBottom: `1px solid ${C.panelBorder}`,
                  alignItems: "center",
                  gap: 0,
                  transition: "background 0.1s",
                  cursor: "default",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = C.rowHover; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                <div style={{ width: 90, flexShrink: 0, fontFamily: FM, fontSize: 11, color: C.muted, paddingRight: 8 }}>#{job.id}</div>
                <div style={{ flex: 1, fontFamily: FS, fontSize: 12, color: C.textLight, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingRight: 8 }} title={job.name}>
                  {job.name}
                </div>
                <div style={{ width: 80, flexShrink: 0, fontFamily: FM, fontSize: 11, color: C.muted, textAlign: "right", paddingRight: 8 }}>
                  {job.rowCount.toLocaleString()}
                </div>
                <div style={{ width: 60, flexShrink: 0, paddingRight: 8 }}>
                  <FormatPill format={job.format} />
                </div>
                <div style={{ width: 90, flexShrink: 0, display: "flex", alignItems: "center", gap: 5, paddingRight: 8 }}>
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: job.status === "complete" ? C.complete : C.failed,
                      display: "inline-block",
                    }}
                  />
                  <span style={{ fontFamily: FS, fontSize: 11, color: job.status === "complete" ? C.complete : C.failed }}>
                    {job.status === "complete" ? "Complete" : "Failed"}
                  </span>
                </div>
                <div style={{ width: 120, flexShrink: 0, fontFamily: FM, fontSize: 11, color: C.timestamp, paddingRight: 8 }}>
                  {formatRelativeTime(job.createdAt)}
                </div>
                <div style={{ width: 80, flexShrink: 0 }}>
                  <button
                    onClick={() => {
                      if (job.status === "complete") downloadJob(job.id);
                      else retryJob(job.id);
                    }}
                    style={{ fontFamily: FS, fontSize: 11, color: C.processing, background: "none", border: "none", cursor: "pointer" }}
                  >
                    {job.status === "complete" ? "Re-export" : "Retry"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
         EXPORT MODAL
         ═══════════════════════════════════════════════ */}
      {showExportModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            backdropFilter: "blur(4px)",
            zIndex: 100,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            animation: "fadeIn 0.15s ease",
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowExportModal(false); }}
        >
          <div
            ref={modalRef}
            style={{
              background: C.panel,
              border: `1px solid ${C.cardBorder}`,
              borderRadius: 12,
              width: "100%",
              maxWidth: 520,
              maxHeight: "90vh",
              overflowY: "auto",
              padding: 24,
              animation: "slideUp 0.2s ease",
            }}
          >
            {/* Modal header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
              <div>
                <h2 style={{ fontFamily: FS, fontSize: 20, fontWeight: 700, color: "#fff", margin: 0 }}>Export Data</h2>
                <p style={{ fontFamily: FS, fontSize: 13, color: C.muted, marginTop: 3 }}>
                  Exporting: {modalContext === "products" ? "Products List" : modalContext === "comparison-matrix" ? "Comparison Matrix" : "Price History"}
                </p>
              </div>
              <button onClick={() => setShowExportModal(false)} style={{ background: "none", border: "none", cursor: "pointer", color: C.muted, padding: 4 }}>
                <X size={18} />
              </button>
            </div>

            {/* Format selection */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ fontFamily: FS, fontSize: 12, fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.04em", display: "block", marginBottom: 8 }}>
                File Format
              </label>
              <div style={{ display: "flex", gap: 10 }}>
                {([
                  { fmt: "csv" as ExportFormat, icon: <FileText size={20} />, label: "CSV", sub: "Compatible with Excel, Google Sheets, any tool", color: C.csv },
                  { fmt: "xlsx" as ExportFormat, icon: <FileSpreadsheet size={20} />, label: "Excel (.xlsx)", sub: "Native Excel format with formatting preserved", color: C.xlsx },
                ]).map(({ fmt, icon, label, sub, color }) => (
                  <button
                    key={fmt}
                    onClick={() => setExportFormat(fmt)}
                    style={{
                      flex: 1,
                      padding: 14,
                      borderRadius: 8,
                      background: exportFormat === fmt ? `${color}08` : "transparent",
                      border: `1px solid ${exportFormat === fmt ? `${color}66` : C.panelBorder}`,
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "all 0.15s",
                    }}
                  >
                    <div style={{ color, marginBottom: 6 }}>{icon}</div>
                    <div style={{ fontFamily: FM, fontSize: 14, fontWeight: 600, color: C.text }}>{label}</div>
                    <div style={{ fontFamily: FS, fontSize: 11, color: C.muted, marginTop: 3 }}>{sub}</div>
                    <div style={{ fontFamily: FM, fontSize: 10, color: C.timestamp, marginTop: 6 }}>
                      ~{formatBytes(estimateFileSize(estimatedRows, fmt))} estimated
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Scope options (not for price-history) */}
            {modalContext !== "price-history" && (
              <div style={{ marginBottom: 20 }}>
                <label style={{ fontFamily: FS, fontSize: 12, fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.04em", display: "block", marginBottom: 8 }}>
                  Include Data
                </label>
                {([
                  { key: "currentPrices", label: "Current prices" },
                  { key: "priceDiffs", label: "Price differences (%)" },
                  { key: "competitorNames", label: "Competitor names" },
                  { key: "priceHistory", label: "Price history (last 30 days)" },
                  { key: "stockStatus", label: "Stock status" },
                  { key: "metadata", label: "Product metadata (category, tags, SKU)" },
                ]).map(({ key, label }) => (
                  <label
                    key={key}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "7px 0",
                      fontFamily: FS,
                      fontSize: 13,
                      color: C.textLight,
                      cursor: "pointer",
                    }}
                  >
                    <div
                      onClick={() => toggleOption(key)}
                      style={{
                        width: 18,
                        height: 18,
                        borderRadius: 4,
                        border: `1.5px solid ${exportOptions[key] ? C.processing : "rgba(255,255,255,0.15)"}`,
                        background: exportOptions[key] ? "rgba(0,212,255,0.15)" : "transparent",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        transition: "all 0.15s",
                        cursor: "pointer",
                        flexShrink: 0,
                      }}
                    >
                      {exportOptions[key] && <Check size={12} color={C.processing} />}
                    </div>
                    {label}
                    {key === "priceHistory" && exportOptions[key] && (
                      <span style={{ fontFamily: FM, fontSize: 10, color: C.warning, marginLeft: "auto" }}>+rows</span>
                    )}
                  </label>
                ))}
              </div>
            )}

            {/* Date range (price-history) */}
            {modalContext === "price-history" && (
              <div style={{ marginBottom: 20 }}>
                <label style={{ fontFamily: FS, fontSize: 12, fontWeight: 600, color: C.muted, textTransform: "uppercase", letterSpacing: "0.04em", display: "block", marginBottom: 8 }}>
                  Date Range
                </label>
                <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${C.panelBorder}` }}>
                  {["7d", "30d", "60d", "90d"].map((r) => (
                    <button
                      key={r}
                      onClick={() => setHistoryRange(r)}
                      style={{
                        fontFamily: FM,
                        fontSize: 12,
                        padding: "6px 14px",
                        background: historyRange === r ? "rgba(0,212,255,0.15)" : "transparent",
                        color: historyRange === r ? C.processing : C.muted,
                        border: "none",
                        borderRight: `1px solid ${C.panelBorder}`,
                        cursor: "pointer",
                        textTransform: "uppercase",
                      }}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Row count estimate */}
            <div style={{ textAlign: "center", padding: "20px 0", borderTop: `1px solid ${C.panelBorder}`, borderBottom: `1px solid ${C.panelBorder}`, margin: "16px 0" }}>
              <div style={{ fontFamily: FS, fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Estimated export size</div>
              <div style={{ fontFamily: FM, fontSize: 28, fontWeight: 700, color: "#fff" }}>
                {estimatedRows.toLocaleString()} <span style={{ fontSize: 14, color: C.muted, fontWeight: 400 }}>rows</span>
              </div>
              <div style={{ fontFamily: FM, fontSize: 13, color: C.muted, marginTop: 2 }}>~{formatBytes(estimatedSize)}</div>

              {isAsync ? (
                <div style={{ marginTop: 12, padding: "8px 12px", borderRadius: 6, background: "rgba(240,164,41,0.08)", border: `1px solid rgba(240,164,41,0.2)`, display: "inline-flex", flexDirection: "column", gap: 3, alignItems: "center" }}>
                  <span style={{ fontFamily: FS, fontSize: 12, color: C.warning, display: "flex", alignItems: "center", gap: 5 }}>
                    <AlertTriangle size={13} /> Large export — will process in background
                  </span>
                  <span style={{ fontFamily: FS, fontSize: 11, color: C.muted }}>
                    You&apos;ll receive an email with a download link when ready
                  </span>
                  <span style={{ fontFamily: FM, fontSize: 11, color: C.timestamp }}>→ analyst@company.com</span>
                </div>
              ) : (
                <div style={{ marginTop: 12, padding: "6px 12px", borderRadius: 6, background: "rgba(61,214,140,0.08)", border: `1px solid rgba(61,214,140,0.2)`, display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <Check size={13} color={C.complete} />
                  <span style={{ fontFamily: FS, fontSize: 12, color: C.complete }}>Small export — instant download</span>
                </div>
              )}
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 16 }}>
              <button
                onClick={() => setShowExportModal(false)}
                style={{ fontFamily: FS, fontSize: 13, color: C.muted, background: "none", border: "none", cursor: "pointer", padding: "8px 14px" }}
              >
                Cancel
              </button>
              <button
                onClick={startExport}
                style={{
                  fontFamily: FS,
                  fontSize: 14,
                  fontWeight: 600,
                  padding: isAsync ? "10px 32px" : "10px 20px",
                  borderRadius: 6,
                  background: C.processing,
                  color: "#000",
                  border: "none",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  flex: isAsync ? 1 : "none",
                  justifyContent: "center",
                }}
              >
                <Download size={15} />
                Start Export
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
         TOAST NOTIFICATIONS
         ═══════════════════════════════════════════════ */}
      <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 200, display: "flex", flexDirection: "column", gap: 8, maxWidth: 380 }}>
        {toasts.map((toast) => {
          const colorMap: Record<Toast["type"], string> = {
            started: C.processing,
            complete: C.complete,
            instant: C.complete,
            failed: C.failed,
          };
          const iconMap: Record<Toast["type"], React.ReactNode> = {
            started: <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />,
            complete: <Check size={16} />,
            instant: <Check size={16} />,
            failed: <X size={16} />,
          };
          const accent = colorMap[toast.type];

          return (
            <div
              key={toast.id}
              style={{
                background: "#1A2332",
                border: `1px solid rgba(255,255,255,0.08)`,
                borderRadius: 8,
                borderLeft: `4px solid ${accent}`,
                padding: "12px 14px",
                animation: "toastSlide 0.3s ease",
                boxShadow: toast.type === "complete" ? "0 0 20px rgba(61,214,140,0.15)" : "0 4px 20px rgba(0,0,0,0.3)",
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
              }}
              onMouseEnter={() => pauseToast(toast.id, true)}
              onMouseLeave={() => pauseToast(toast.id, false)}
            >
              <div style={{ color: accent, flexShrink: 0, marginTop: 1 }}>{iconMap[toast.type]}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: FS, fontSize: 13, fontWeight: 600, color: C.text }}>{toast.title}</div>
                <div style={{ fontFamily: FS, fontSize: 12, color: C.muted, marginTop: 2 }}>{toast.body}</div>
                {toast.type === "started" && (
                  <button
                    onClick={() => { setActiveTab("active"); removeToast(toast.id); }}
                    style={{ fontFamily: FS, fontSize: 11, color: C.processing, background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 4 }}
                  >
                    Track progress →
                  </button>
                )}
                {toast.type === "complete" && toast.jobId && (
                  <button
                    onClick={() => { downloadJob(toast.jobId!); removeToast(toast.id); }}
                    style={{
                      fontFamily: FS,
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "4px 10px",
                      borderRadius: 4,
                      background: C.complete,
                      color: "#000",
                      border: "none",
                      cursor: "pointer",
                      marginTop: 6,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <Download size={11} /> Download now
                  </button>
                )}
                {toast.type === "failed" && toast.jobId && (
                  <button
                    onClick={() => { retryJob(toast.jobId!); removeToast(toast.id); }}
                    style={{ fontFamily: FS, fontSize: 11, color: C.processing, background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 4 }}
                  >
                    Retry
                  </button>
                )}
              </div>
              <button onClick={() => removeToast(toast.id)} style={{ background: "none", border: "none", cursor: "pointer", color: C.timestamp, padding: 0, flexShrink: 0 }}>
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
