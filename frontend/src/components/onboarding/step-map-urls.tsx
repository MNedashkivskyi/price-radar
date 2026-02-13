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
  CheckCircle2,
} from "lucide-react";
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

export function StepMapUrls() {
  const store = useOnboarding();
  const { toast } = useToast();
  const [searchQuery, setSearchQuery] = useState("");
  const [editingKey, setEditingKey] = useState<string | null>(null); // "productId:domain"
  const [urlDraft, setUrlDraft] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [showCsvUpload, setShowCsvUpload] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvErrors, setCsvErrors] = useState<{ row: number; message: string }[]>([]);
  const [csvPreview, setCsvPreview] = useState<{ product_id: number; url: string; competitor_domain: string; title?: string }[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);

  const products = store.products;
  const competitors = store.competitors;
  const totalSlots = products.length * competitors.length;
  const filledSlots = store.mappings.size;
  const mappedProductCount = store.mappedProductCount;

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

  const handleEditUrl = (productId: number, domain: string) => {
    const key = `${productId}:${domain}`;
    setEditingKey(key);
    setUrlDraft(store.getMapping(productId, domain));
    setTimeout(() => urlInputRef.current?.focus(), 50);
  };

  const handleSaveUrl = (productId: number, domain: string) => {
    if (urlDraft.trim() && !isValidUrl(urlDraft.trim())) {
      toast({ type: "error", title: "Invalid URL format" });
      return;
    }
    store.setMapping(productId, domain, urlDraft.trim());
    setEditingKey(null);
    setUrlDraft("");
  };

  const handlePaste = (e: React.ClipboardEvent, productId: number, domain: string) => {
    const pasted = e.clipboardData.getData("text").trim();
    if (isValidUrl(pasted)) {
      store.setMapping(productId, domain, pasted);
      setEditingKey(null);
      setUrlDraft("");
      toast({ type: "success", title: "URL mapped" });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, productId: number, domain: string) => {
    if (e.key === "Enter") {
      handleSaveUrl(productId, domain);
    } else if (e.key === "Escape") {
      setEditingKey(null);
      setUrlDraft("");
    }
  };

  // CSV handling — expects product_id,competitor_domain,competitor_url
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
          const preview: { product_id: number; url: string; competitor_domain: string; title?: string }[] = [];

          results.data.forEach((row: unknown, i: number) => {
            const r = row as Record<string, string>;
            const productId = parseInt(r.product_id || r.id || "", 10);
            const url = (r.competitor_url || r.url || "").trim();
            // Default to first competitor if no domain column
            const domain = (r.competitor_domain || r.domain || competitors[0]?.domain || "").trim();

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
              competitor_domain: domain,
              title: product?.title,
            });
          });

          setCsvPreview(preview);
          setCsvErrors(errors);
        },
      });
    },
    [products, competitors]
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
    const entries: [number, string, string][] = csvPreview.map((row) => [
      row.product_id,
      row.competitor_domain,
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
    const headers = "product_id,competitor_domain,competitor_url\n";
    const rows = products
      .slice(0, 3)
      .flatMap((p) =>
        competitors.map(
          (c) => `${p.id},${c.domain},https://${c.domain}/products/${p.handle}`
        )
      )
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
    if (store.mappings.size === 0) {
      toast({ type: "error", title: "Map at least one product to continue" });
      return;
    }

    setIsSaving(true);
    try {
      const allMappings = Array.from(store.mappings.entries())
        .map(([key, url]) => {
          const [pidStr, ...domainParts] = key.split(":");
          const domain = domainParts.join(":");
          const competitor = competitors.find((c) => c.domain === domain);
          return {
            product_id: parseInt(pidStr, 10),
            competitor_id: competitor?.id || 0,
            url,
          };
        })
        .filter((m) => m.competitor_id > 0);

      if (allMappings.length > 0) {
        await bulkCreateMappings(allMappings);
      }

      store.completeOnboarding();
      store.setStep(4);
      toast({ type: "success", title: "Setup complete! Mappings saved." });
    } catch {
      // Still complete even if API fails — data is saved locally
      store.completeOnboarding();
      store.setStep(4);
      toast({
        type: "info",
        title: "Setup complete!",
        description: "Mappings saved locally — will sync when connected",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleBack = () => {
    store.setStep(2);
  };

  const progressPct = totalSlots > 0 ? Math.round((filledSlots / totalSlots) * 100) : 0;

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
          For each product, add the competitor URL where you want to track pricing
        </p>
      </div>

      {/* Progress + Actions bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div className="flex-1 min-w-0 w-full sm:w-auto">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-muted-foreground">
              <span className="text-foreground font-medium">{mappedProductCount}</span>{" "}
              of {formatNumber(products.length)} products have URLs
              {competitors.length > 1 && (
                <span className="text-muted-foreground/60"> · {filledSlots} total mappings</span>
              )}
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
                    Columns: product_id, competitor_domain, competitor_url
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
                              <th className="text-left p-2 font-medium">Competitor</th>
                              <th className="text-left p-2 font-medium">URL</th>
                            </tr>
                          </thead>
                          <tbody>
                            {csvPreview.slice(0, 10).map((row, i) => (
                              <tr key={i} className="border-b border-border/20 last:border-0">
                                <td className="p-2 text-muted-foreground">
                                  {row.title || `#${row.product_id}`}
                                </td>
                                <td className="p-2 text-muted-foreground">{row.competitor_domain}</td>
                                <td className="p-2 text-muted-foreground truncate max-w-40">{row.url}</td>
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

      {/* Product mapping list */}
      <Card className="border-border/50 bg-card/50 backdrop-blur-sm overflow-hidden">
        {filteredProducts.length === 0 ? (
          <div className="p-12 text-center">
            <Link2 className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              {products.length === 0
                ? "No products imported yet. Go back to Step 1."
                : "No products match your search."}
            </p>
          </div>
        ) : (
          <div className="max-h-[520px] overflow-y-auto divide-y divide-border/20">
            {filteredProducts.map((product) => {
              const productMappedCount = competitors.filter(
                (c) => !!store.getMapping(product.id, c.domain)
              ).length;
              const allMapped = productMappedCount === competitors.length;

              return (
                <div key={product.id} className="p-3 sm:p-4">
                  {/* Product header */}
                  <div className="flex items-center gap-3 mb-2">
                    <div className="w-9 h-9 rounded-lg bg-muted/50 flex items-center justify-center shrink-0 overflow-hidden">
                      {product.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={product.image_url} alt="" className="w-full h-full object-cover" />
                      ) : (
                        <ImageIcon className="w-4 h-4 text-muted-foreground/50" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{product.title}</p>
                      <span className="text-xs text-muted-foreground">${product.our_price.toFixed(2)}</span>
                    </div>
                    {allMapped && (
                      <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
                    )}
                    {productMappedCount > 0 && !allMapped && (
                      <Badge variant="outline" className="text-[10px] shrink-0">
                        {productMappedCount}/{competitors.length}
                      </Badge>
                    )}
                  </div>

                  {/* One URL row per competitor */}
                  <div className="space-y-1.5 ml-12">
                    {competitors.map((comp) => {
                      const key = `${product.id}:${comp.domain}`;
                      const mappedUrl = store.getMapping(product.id, comp.domain);
                      const isEditing = editingKey === key;

                      return (
                        <div key={key} className="flex items-center gap-2">
                          <span className="text-[10px] text-muted-foreground w-20 truncate shrink-0" title={comp.domain}>
                            {comp.name}
                          </span>
                          {isEditing ? (
                            <div className="flex gap-1.5 flex-1">
                              <Input
                                ref={urlInputRef}
                                placeholder={`https://${comp.domain}/product/...`}
                                value={urlDraft}
                                onChange={(e) => setUrlDraft(e.target.value)}
                                onPaste={(e) => handlePaste(e, product.id, comp.domain)}
                                onKeyDown={(e) => handleKeyDown(e, product.id, comp.domain)}
                                className="text-xs h-7"
                              />
                              <Button
                                size="sm"
                                className="h-7 px-2 text-xs"
                                onClick={() => handleSaveUrl(product.id, comp.domain)}
                              >
                                Save
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-1.5"
                                onClick={() => { setEditingKey(null); setUrlDraft(""); }}
                              >
                                <X className="w-3 h-3" />
                              </Button>
                            </div>
                          ) : mappedUrl ? (
                            <button
                              onClick={() => handleEditUrl(product.id, comp.domain)}
                              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground truncate flex-1 transition-colors group"
                            >
                              <ExternalLink className="w-3 h-3 shrink-0 opacity-50 group-hover:opacity-100" />
                              <span className="truncate">{mappedUrl}</span>
                            </button>
                          ) : (
                            <button
                              onClick={() => handleEditUrl(product.id, comp.domain)}
                              className="text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors"
                            >
                              + Add URL
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
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
          disabled={store.mappings.size === 0}
        >
          <Rocket className="w-4 h-4" />
          Finish Setup ({mappedProductCount} products mapped)
          <ArrowRight className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
