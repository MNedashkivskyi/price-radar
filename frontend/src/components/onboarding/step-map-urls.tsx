"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Link2,
  Search,
  Upload,
  Download,
  ArrowLeft,
  ArrowRight,
  X,
  FileSpreadsheet,
  ImageIcon,
  ExternalLink,
  Rocket,
} from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import Papa from "papaparse";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/components/ui/toast";
import { useOnboarding } from "@/lib/onboarding-store";
import { cn, isValidUrl, formatNumber } from "@/lib/utils";
import { bulkCreateMappings } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const ROW_HEIGHT = 64;

export function StepMapUrls() {
  const store = useOnboarding();
  const { toast } = useToast();
  const [searchQuery, setSearchQuery] = useState("");
  const [editingProductId, setEditingProductId] = useState<number | null>(null);
  const [urlDraft, setUrlDraft] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [showCsvUpload, setShowCsvUpload] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvErrors, setCsvErrors] = useState<{ row: number; message: string }[]>([]);
  const [csvPreview, setCsvPreview] = useState<{ product_id: number; url: string; title?: string }[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const products = store.products;
  const mappedCount = store.mappings.size;
  const totalCount = products.length;

  const filteredProducts = useMemo(() => {
    if (!searchQuery.trim()) return products;
    const q = searchQuery.toLowerCase();
    return products.filter(
      (p) =>
        p.title.toLowerCase().includes(q) ||
        p.handle.toLowerCase().includes(q) ||
        p.shopify_product_id.includes(q)
    );
  }, [products, searchQuery]);

  const rowVirtualizer = useVirtualizer({
    count: filteredProducts.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  const competitorNames = store.competitors.map((c) => c.name).join(", ");

  const handleEditUrl = (productId: number) => {
    setEditingProductId(productId);
    setUrlDraft(store.mappings.get(productId) || "");
    setTimeout(() => urlInputRef.current?.focus(), 50);
  };

  const handleSaveUrl = (productId: number) => {
    if (urlDraft.trim() && !isValidUrl(urlDraft.trim())) {
      toast({ type: "error", title: "Invalid URL format" });
      return;
    }
    store.setMapping(productId, urlDraft.trim());
    setEditingProductId(null);
    setUrlDraft("");
  };

  const handlePaste = (e: React.ClipboardEvent, productId: number) => {
    const pasted = e.clipboardData.getData("text").trim();
    if (isValidUrl(pasted)) {
      store.setMapping(productId, pasted);
      setEditingProductId(null);
      setUrlDraft("");
      toast({ type: "success", title: "URL mapped" });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, productId: number) => {
    if (e.key === "Enter") {
      handleSaveUrl(productId);
    } else if (e.key === "Escape") {
      setEditingProductId(null);
      setUrlDraft("");
    }
  };

  // CSV handling
  const handleCsvFile = useCallback(
    (file: File) => {
      setCsvFile(file);
      setCsvErrors([]);
      setCsvPreview([]);

      Papa.parse(file, {
        header: true,
        skipEmptyLines: true,
        complete: (results) => {
          const errors: { row: number; message: string }[] = [];
          const preview: { product_id: number; url: string; title?: string }[] = [];

          results.data.forEach((row: unknown, i: number) => {
            const r = row as Record<string, string>;
            const productId = parseInt(r.product_id || r.id || "", 10);
            const url = (r.competitor_url || r.url || "").trim();

            if (!productId || isNaN(productId)) {
              errors.push({ row: i + 2, message: "Missing or invalid product_id" });
              return;
            }
            if (!url) {
              errors.push({ row: i + 2, message: "Missing competitor_url" });
              return;
            }
            if (!isValidUrl(url)) {
              errors.push({ row: i + 2, message: `Invalid URL: ${url}` });
              return;
            }

            const product = products.find((p) => p.id === productId);
            preview.push({
              product_id: productId,
              url,
              title: product?.title,
            });
          });

          setCsvPreview(preview);
          setCsvErrors(errors);
        },
      });
    },
    [products]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file && (file.type === "text/csv" || file.name.endsWith(".csv"))) {
        handleCsvFile(file);
      } else {
        toast({ type: "error", title: "Please upload a CSV file" });
      }
    },
    [handleCsvFile, toast]
  );

  const handleCsvImport = () => {
    const entries: [number, string][] = csvPreview.map((row) => [
      row.product_id,
      row.url,
    ]);
    store.setBulkMappings(entries);
    setCsvFile(null);
    setCsvPreview([]);
    setCsvErrors([]);
    setShowCsvUpload(false);
    toast({
      type: "success",
      title: `${entries.length} mappings imported from CSV`,
    });
  };

  const downloadTemplate = () => {
    const headers = "product_id,competitor_url\n";
    const rows = products
      .slice(0, 5)
      .map((p) => `${p.id},https://competitor.com/products/${p.handle}`)
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "price-radar-mappings-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFinish = async () => {
    if (mappedCount === 0) {
      toast({ type: "error", title: "Map at least one product to continue" });
      return;
    }

    setIsSaving(true);
    try {
      // For each competitor, submit the mappings
      const allMappings = Array.from(store.mappings.entries()).flatMap(
        ([productId, url]) =>
          store.competitors
            .filter((c) => c.id > 0)
            .map((c) => ({
              product_id: productId,
              competitor_id: c.id,
              url,
            }))
      );

      if (allMappings.length > 0) {
        await bulkCreateMappings(allMappings);
      }

      toast({ type: "success", title: "Onboarding complete! Mappings saved." });
    } catch {
      toast({
        type: "info",
        title: "Onboarding complete!",
        description: "Mappings saved locally",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleBack = () => {
    store.setStep(2);
  };

  const progressPct = totalCount > 0 ? Math.round((mappedCount / totalCount) * 100) : 0;

  return (
    <div className="max-w-3xl mx-auto">
      {/* Hero */}
      <div className="text-center mb-8">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-5"
        >
          <Link2 className="w-8 h-8 text-primary" />
        </motion.div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">
          Match products to competitor listings
        </h1>
        <p className="text-muted-foreground text-base max-w-md mx-auto">
          {competitorNames
            ? `Add competitor URLs for ${competitorNames}`
            : "Add competitor URLs for the products you want to track"}
        </p>
      </div>

      {/* Progress + Actions bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div className="flex-1 min-w-0 w-full sm:w-auto">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-muted-foreground">
              <span className="text-foreground font-medium">{mappedCount}</span>{" "}
              of {formatNumber(totalCount)} products mapped
            </span>
            <span className="text-muted-foreground">{progressPct}%</span>
          </div>
          <Progress value={progressPct} className="h-2" />
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowCsvUpload(!showCsvUpload)}
          >
            <Upload className="w-3.5 h-3.5" />
            CSV Import
          </Button>
          <Button variant="outline" size="sm" onClick={downloadTemplate}>
            <Download className="w-3.5 h-3.5" />
            Template
          </Button>
        </div>
      </div>

      {/* CSV Upload Zone */}
      <AnimatePresence>
        {showCsvUpload && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-6 overflow-hidden"
          >
            <Card className="p-6 border-border/50 bg-card/50 backdrop-blur-sm">
              {!csvFile ? (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragOver(true);
                  }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  className={cn(
                    "border-2 border-dashed rounded-xl p-8 text-center transition-colors",
                    isDragOver
                      ? "border-primary bg-primary/5"
                      : "border-border/50 hover:border-border"
                  )}
                >
                  <FileSpreadsheet className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                  <p className="text-sm font-medium mb-1">
                    Drop your CSV file here
                  </p>
                  <p className="text-xs text-muted-foreground mb-4">
                    or click to browse. Expected columns: product_id, competitor_url
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Browse Files
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleCsvFile(file);
                    }}
                  />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <FileSpreadsheet className="w-5 h-5 text-primary" />
                      <div>
                        <p className="text-sm font-medium">{csvFile.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {csvPreview.length} valid rows
                          {csvErrors.length > 0 && `, ${csvErrors.length} errors`}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => {
                        setCsvFile(null);
                        setCsvPreview([]);
                        setCsvErrors([]);
                      }}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>

                  {csvErrors.length > 0 && (
                    <div className="p-3 rounded-lg bg-destructive/5 border border-destructive/20">
                      <p className="text-xs font-medium text-destructive mb-2">
                        {csvErrors.length} errors found:
                      </p>
                      <div className="max-h-24 overflow-y-auto space-y-1">
                        {csvErrors.slice(0, 5).map((err, i) => (
                          <p key={i} className="text-xs text-muted-foreground">
                            Row {err.row}: {err.message}
                          </p>
                        ))}
                        {csvErrors.length > 5 && (
                          <p className="text-xs text-muted-foreground">
                            +{csvErrors.length - 5} more errors
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  {csvPreview.length > 0 && (
                    <>
                      <div className="max-h-40 overflow-y-auto rounded-lg border border-border/50">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-border/50 bg-muted/30">
                              <th className="text-left p-2 font-medium">Product</th>
                              <th className="text-left p-2 font-medium">URL</th>
                            </tr>
                          </thead>
                          <tbody>
                            {csvPreview.slice(0, 10).map((row, i) => (
                              <tr
                                key={i}
                                className="border-b border-border/20 last:border-0"
                              >
                                <td className="p-2 text-muted-foreground">
                                  {row.title || `#${row.product_id}`}
                                </td>
                                <td className="p-2 text-muted-foreground truncate max-w-48">
                                  {row.url}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <Button size="sm" onClick={handleCsvImport}>
                        Import {csvPreview.length} Mappings
                      </Button>
                    </>
                  )}
                </div>
              )}
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Search */}
      <div className="mb-4">
        <Input
          placeholder="Search products by name, handle, or SKU..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          icon={<Search className="w-4 h-4" />}
        />
      </div>

      {/* Product mapping list — virtualized */}
      <Card className="border-border/50 bg-card/50 backdrop-blur-sm overflow-hidden">
        {filteredProducts.length === 0 ? (
          <div className="p-12 text-center">
            <Link2 className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              {products.length === 0
                ? "No products imported yet. Go back to Step 1 to import products."
                : "No products match your search."}
            </p>
          </div>
        ) : (
          <div
            ref={scrollContainerRef}
            className="max-h-[480px] overflow-y-auto"
          >
            <div
              style={{
                height: `${rowVirtualizer.getTotalSize()}px`,
                width: "100%",
                position: "relative",
              }}
            >
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const product = filteredProducts[virtualRow.index];
                const mappedUrl = store.mappings.get(product.id);
                const isEditing = editingProductId === product.id;

                return (
                  <div
                    key={product.id}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <div
                      className={cn(
                        "flex items-center gap-3 px-3 sm:px-4 h-full border-b border-border/20",
                        isEditing && "bg-muted/20"
                      )}
                    >
                      {/* Product image */}
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

                      {/* Product info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">
                          {product.title}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-muted-foreground">
                            ${product.our_price.toFixed(2)}
                          </span>
                          {mappedUrl && !isEditing && (
                            <Badge variant="success" className="text-[10px] py-0">
                              Mapped
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* URL input / display */}
                      <div className="flex items-center gap-2 flex-1 max-w-sm">
                        {isEditing ? (
                          <div className="flex gap-2 w-full">
                            <Input
                              ref={urlInputRef}
                              placeholder="https://competitor.com/product/..."
                              value={urlDraft}
                              onChange={(e) => setUrlDraft(e.target.value)}
                              onPaste={(e) => handlePaste(e, product.id)}
                              onKeyDown={(e) => handleKeyDown(e, product.id)}
                              className="text-xs h-8"
                            />
                            <Button
                              size="sm"
                              className="h-8 px-3"
                              onClick={() => handleSaveUrl(product.id)}
                            >
                              Save
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-8 px-2"
                              onClick={() => {
                                setEditingProductId(null);
                                setUrlDraft("");
                              }}
                            >
                              <X className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        ) : mappedUrl ? (
                          <button
                            onClick={() => handleEditUrl(product.id)}
                            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground truncate max-w-full transition-colors group"
                          >
                            <ExternalLink className="w-3 h-3 shrink-0 opacity-50 group-hover:opacity-100" />
                            <span className="truncate">{mappedUrl}</span>
                          </button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 text-xs text-muted-foreground"
                            onClick={() => handleEditUrl(product.id)}
                          >
                            + Add URL
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Card>

      {filteredProducts.length < products.length && products.length > 0 && (
        <p className="text-center text-xs text-muted-foreground mt-3">
          Showing {filteredProducts.length} of {formatNumber(products.length)} products
        </p>
      )}

      {/* Bottom actions */}
      <div className="flex items-center justify-between mt-8">
        <Button variant="ghost" onClick={handleBack}>
          <ArrowLeft className="w-4 h-4" />
          Back
        </Button>
        <Button
          size="lg"
          onClick={handleFinish}
          loading={isSaving}
          disabled={mappedCount === 0}
        >
          <Rocket className="w-4 h-4" />
          Finish Setup ({mappedCount} mapped)
          <ArrowRight className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
