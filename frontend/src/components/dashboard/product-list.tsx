"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  ImageIcon,
  Link2,
  ExternalLink,
  Tag,
  X,
  Package,
  Users,
  Plus,
  Check,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast, ToastProvider } from "@/components/ui/toast";
import {
  listProducts,
  listCompetitors,
  createMapping,
  detectCompetitor,
  type Product,
  type Competitor,
  type ListProductsParams,
} from "@/lib/api";
import { cn, formatNumber, isValidUrl } from "@/lib/utils";

type SortBy = "title" | "our_price" | "created_at" | "competitors_tracked";
type SortOrder = "asc" | "desc";

const PAGE_SIZE = 25;

function ProductListInner() {
  const { toast } = useToast();

  // Data state
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [initialLoad, setInitialLoad] = useState(true);

  // Filter/sort/pagination state
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("created_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

  // Quick-add competitor URL state
  const [quickAddProductId, setQuickAddProductId] = useState<number | null>(null);
  const [quickAddUrl, setQuickAddUrl] = useState("");
  const [quickAddCompetitorId, setQuickAddCompetitorId] = useState<number | null>(null);
  const [quickAddSaving, setQuickAddSaving] = useState(false);
  const quickAddInputRef = useRef<HTMLInputElement>(null);

  // Search debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [tagFilter, sortBy, sortOrder]);

  // Fetch products
  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params: ListProductsParams = {
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (debouncedSearch) params.search = debouncedSearch;
      if (tagFilter) params.tag = tagFilter;

      const data = await listProducts(params);
      setProducts(data.products);
      setTotal(data.total);
      setAllTags(data.all_tags);
    } catch {
      toast({ type: "error", title: "Failed to load products" });
    } finally {
      setLoading(false);
      setInitialLoad(false);
    }
  }, [page, debouncedSearch, tagFilter, sortBy, sortOrder, toast]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  // Fetch competitors once
  useEffect(() => {
    listCompetitors()
      .then(setCompetitors)
      .catch(() => {});
  }, []);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // Sort toggle
  const handleSort = (column: SortBy) => {
    if (sortBy === column) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortOrder(column === "title" ? "asc" : "desc");
    }
  };

  const SortIcon = ({ column }: { column: SortBy }) => {
    if (sortBy !== column) return <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />;
    return sortOrder === "asc" ? (
      <ArrowUp className="w-3.5 h-3.5 text-primary" />
    ) : (
      <ArrowDown className="w-3.5 h-3.5 text-primary" />
    );
  };

  // Quick-add competitor URL
  const openQuickAdd = (productId: number) => {
    setQuickAddProductId(productId);
    setQuickAddUrl("");
    setQuickAddCompetitorId(competitors.length === 1 ? competitors[0].id : null);
    setTimeout(() => quickAddInputRef.current?.focus(), 50);
  };

  const closeQuickAdd = () => {
    setQuickAddProductId(null);
    setQuickAddUrl("");
    setQuickAddCompetitorId(null);
  };

  const handleQuickAddSave = async () => {
    if (!quickAddProductId || !quickAddUrl.trim() || !quickAddCompetitorId) return;
    if (!isValidUrl(quickAddUrl.trim())) {
      toast({ type: "error", title: "Enter a valid URL" });
      return;
    }

    setQuickAddSaving(true);
    try {
      await createMapping({
        product_id: quickAddProductId,
        competitor_id: quickAddCompetitorId,
        url: quickAddUrl.trim(),
      });
      toast({ type: "success", title: "Competitor URL added" });
      closeQuickAdd();
      fetchProducts(); // refresh to update competitor count
    } catch {
      toast({ type: "error", title: "Failed to add mapping" });
    } finally {
      setQuickAddSaving(false);
    }
  };

  const handleQuickAddPaste = async (e: React.ClipboardEvent) => {
    const url = e.clipboardData.getData("text").trim();
    if (!isValidUrl(url)) return;

    // Auto-detect competitor from URL
    if (!quickAddCompetitorId) {
      try {
        const detected = await detectCompetitor(url);
        const match = competitors.find((c) => c.domain === detected.domain);
        if (match) {
          setQuickAddCompetitorId(match.id);
        }
      } catch {
        // Ignore detection errors
      }
    }
  };

  // Format relative time
  const formatRelativeTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div>
      {/* Page header */}
      <div className="mb-6 sm:mb-8">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-1">
          Products
        </h1>
        <p className="text-muted-foreground text-sm">
          {total > 0
            ? `${formatNumber(total)} products across your catalog`
            : "Manage and track your product catalog"}
        </p>
      </div>

      {/* Controls bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        {/* Search */}
        <div className="flex-1 min-w-0">
          <Input
            placeholder="Search products by title or handle..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            icon={<Search className="w-4 h-4" />}
          />
        </div>

        {/* Tag filter */}
        {allTags.length > 0 && (
          <div className="w-full sm:w-48">
            <Select
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              icon={<Tag className="w-4 h-4" />}
            >
              <option value="">All tags</option>
              {allTags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>

      {/* Active filter chips */}
      {(debouncedSearch || tagFilter) && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs text-muted-foreground">Filters:</span>
          {debouncedSearch && (
            <Badge
              variant="secondary"
              className="gap-1 cursor-pointer hover:bg-secondary/60"
              onClick={() => setSearch("")}
            >
              <Search className="w-3 h-3" />
              {debouncedSearch}
              <X className="w-3 h-3" />
            </Badge>
          )}
          {tagFilter && (
            <Badge
              variant="secondary"
              className="gap-1 cursor-pointer hover:bg-secondary/60"
              onClick={() => setTagFilter("")}
            >
              <Tag className="w-3 h-3" />
              {tagFilter}
              <X className="w-3 h-3" />
            </Badge>
          )}
        </div>
      )}

      {/* Data table */}
      <Card className="border-border/50 bg-card/50 backdrop-blur-sm overflow-hidden">
        {/* Table header */}
        <div className="hidden md:grid grid-cols-[1fr_120px_140px_140px] gap-4 px-4 py-3 border-b border-border/30 bg-muted/20">
          <button
            onClick={() => handleSort("title")}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors text-left"
          >
            Product
            <SortIcon column="title" />
          </button>
          <button
            onClick={() => handleSort("our_price")}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors text-right justify-end"
          >
            Price
            <SortIcon column="our_price" />
          </button>
          <button
            onClick={() => handleSort("competitors_tracked")}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors text-center justify-center"
          >
            Competitors
            <SortIcon column="competitors_tracked" />
          </button>
          <button
            onClick={() => handleSort("created_at")}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors text-right justify-end"
          >
            Updated
            <SortIcon column="created_at" />
          </button>
        </div>

        {/* Loading skeleton */}
        {initialLoad && (
          <div className="divide-y divide-border/20">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="px-4 py-4 flex items-center gap-4">
                <Skeleton className="w-10 h-10 rounded-lg shrink-0" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-3 w-24" />
                </div>
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-12" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!initialLoad && products.length === 0 && (
          <div className="p-16 text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-muted/50 mb-4">
              <Package className="w-7 h-7 text-muted-foreground/50" />
            </div>
            <p className="text-sm font-medium mb-1">
              {debouncedSearch || tagFilter
                ? "No products match your filters"
                : "No products yet"}
            </p>
            <p className="text-xs text-muted-foreground max-w-xs mx-auto">
              {debouncedSearch || tagFilter
                ? "Try adjusting your search or removing filters."
                : "Import products from Shopify or add them manually to get started."}
            </p>
          </div>
        )}

        {/* Product rows */}
        {!initialLoad && products.length > 0 && (
          <div className={cn("divide-y divide-border/20", loading && "opacity-60 pointer-events-none")}>
            {products.map((product) => (
              <div key={product.id}>
                {/* Main row */}
                <div className="grid grid-cols-1 md:grid-cols-[1fr_120px_140px_140px] gap-2 md:gap-4 px-4 py-3.5 items-center hover:bg-muted/10 transition-colors group">
                  {/* Product info */}
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-muted/50 flex items-center justify-center shrink-0 overflow-hidden">
                      {product.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={product.image_url}
                          alt=""
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <ImageIcon className="w-4 h-4 text-muted-foreground/50" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {product.title}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {product.tags && (
                          <div className="flex gap-1 overflow-hidden">
                            {product.tags
                              .split(",")
                              .slice(0, 2)
                              .map((t) => t.trim())
                              .filter(Boolean)
                              .map((t) => (
                                <button
                                  key={t}
                                  onClick={() => setTagFilter(t)}
                                  className="text-[10px] px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors truncate max-w-[80px]"
                                  title={t}
                                >
                                  {t}
                                </button>
                              ))}
                            {product.tags.split(",").length > 2 && (
                              <span className="text-[10px] text-muted-foreground/50">
                                +{product.tags.split(",").length - 2}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Price */}
                  <div className="text-right">
                    <span className="text-sm font-medium tabular-nums">
                      ${product.our_price.toFixed(2)}
                    </span>
                    {product.currency !== "USD" && (
                      <span className="text-[10px] text-muted-foreground ml-0.5">
                        {product.currency}
                      </span>
                    )}
                  </div>

                  {/* Competitors tracked */}
                  <div className="flex items-center justify-center gap-2">
                    {product.competitors_tracked > 0 ? (
                      <Badge variant="success" className="text-[10px] px-2 py-0.5">
                        <Users className="w-3 h-3 mr-1" />
                        {product.competitors_tracked} tracked
                      </Badge>
                    ) : (
                      <button
                        onClick={() => openQuickAdd(product.id)}
                        className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-primary transition-colors"
                      >
                        <Plus className="w-3 h-3" />
                        Add URL
                      </button>
                    )}
                  </div>

                  {/* Last updated */}
                  <div className="text-right flex items-center justify-end gap-2">
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeTime(product.updated_at)}
                    </span>
                    {/* Quick-add button (shown on hover for tracked products) */}
                    {product.competitors_tracked > 0 && (
                      <button
                        onClick={() => openQuickAdd(product.id)}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-muted"
                        title="Add competitor URL"
                      >
                        <Plus className="w-3.5 h-3.5 text-muted-foreground" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Quick-add competitor URL inline form */}
                <AnimatePresence>
                  {quickAddProductId === product.id && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-3.5 flex flex-col sm:flex-row gap-2 ml-0 md:ml-[52px]">
                        {/* Competitor selector */}
                        {competitors.length > 1 && (
                          <Select
                            value={quickAddCompetitorId?.toString() || ""}
                            onChange={(e) =>
                              setQuickAddCompetitorId(
                                e.target.value ? parseInt(e.target.value, 10) : null
                              )
                            }
                            className="w-full sm:w-44 h-8 text-xs"
                          >
                            <option value="">Select competitor</option>
                            {competitors.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </Select>
                        )}

                        {/* URL input */}
                        <div className="flex gap-1.5 flex-1">
                          <Input
                            ref={quickAddInputRef}
                            placeholder={
                              competitors.length > 0
                                ? `https://${competitors[0]?.domain || "competitor.com"}/product/...`
                                : "Competitor product URL"
                            }
                            value={quickAddUrl}
                            onChange={(e) => setQuickAddUrl(e.target.value)}
                            onPaste={handleQuickAddPaste}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleQuickAddSave();
                              if (e.key === "Escape") closeQuickAdd();
                            }}
                            className="text-xs h-8"
                            icon={<Link2 className="w-3.5 h-3.5" />}
                          />
                          <Button
                            size="sm"
                            className="h-8 px-3 text-xs"
                            onClick={handleQuickAddSave}
                            disabled={
                              !quickAddUrl.trim() ||
                              !quickAddCompetitorId ||
                              quickAddSaving
                            }
                          >
                            {quickAddSaving ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Check className="w-3.5 h-3.5" />
                            )}
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 px-2"
                            onClick={closeQuickAdd}
                          >
                            <X className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, total)} of{" "}
            {formatNumber(total)}
          </p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
              className="h-8 px-2"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>

            {/* Page numbers */}
            {(() => {
              const pages: (number | "...")[] = [];
              const maxVisible = 5;
              if (totalPages <= maxVisible) {
                for (let i = 0; i < totalPages; i++) pages.push(i);
              } else {
                pages.push(0);
                if (page > 2) pages.push("...");
                for (
                  let i = Math.max(1, page - 1);
                  i <= Math.min(totalPages - 2, page + 1);
                  i++
                ) {
                  pages.push(i);
                }
                if (page < totalPages - 3) pages.push("...");
                pages.push(totalPages - 1);
              }
              return pages.map((p, idx) =>
                p === "..." ? (
                  <span
                    key={`ellipsis-${idx}`}
                    className="px-1 text-xs text-muted-foreground"
                  >
                    ...
                  </span>
                ) : (
                  <Button
                    key={p}
                    variant={page === p ? "default" : "ghost"}
                    size="sm"
                    onClick={() => setPage(p)}
                    disabled={loading}
                    className={cn(
                      "h-8 w-8 p-0 text-xs",
                      page === p && "pointer-events-none"
                    )}
                  >
                    {p + 1}
                  </Button>
                )
              );
            })()}

            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1 || loading}
              className="h-8 px-2"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ProductList() {
  return (
    <ToastProvider>
      <ProductListInner />
    </ToastProvider>
  );
}
