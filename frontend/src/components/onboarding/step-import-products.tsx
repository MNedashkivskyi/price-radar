"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Package,
  ShoppingBag,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  AlertCircle,
  ExternalLink,
  ImageIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useOnboarding } from "@/lib/onboarding-store";
import { cn, formatNumber } from "@/lib/utils";
import {
  importProducts,
  getImportStatus,
  listProducts,
  getShopifyInstallUrl,
  setToken,
} from "@/lib/api";

type Phase = "connect" | "importing" | "success" | "error";

export function StepImportProducts() {
  const store = useOnboarding();
  const { toast } = useToast();
  const [phase, setPhase] = useState<Phase>(
    store.isConnected && store.products.length > 0 ? "success" : "connect"
  );
  const [shopDomain, setShopDomain] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Check for token in URL (OAuth callback)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
      setToken(token);
      store.setConnected(true);
      // Clean URL
      window.history.replaceState({}, "", window.location.pathname);
      handleStartImport();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = () => {
    if (!shopDomain.trim()) return;
    setIsConnecting(true);
    const url = getShopifyInstallUrl(shopDomain.trim());
    window.location.href = url;
  };

  const handleStartImport = async () => {
    setIsImporting(true);
    setError(null);
    setPhase("importing");

    try {
      const result = await importProducts();

      if (result.status === "started" && result.job_id) {
        // Async import - poll for progress
        store.setImportJobId(result.job_id);
        store.setImportProgress(0, 0, result.product_count || 0);
        startPolling(result.job_id, result.product_count || 0);
      } else if (result.status === "completed" && result.stats) {
        // Sync import - completed immediately
        const total = result.stats.created + result.stats.updated;
        store.setImportProgress(100, total, total);
        await loadProducts();
        setPhase("success");
        toast({ type: "success", title: `${formatNumber(total)} products imported!` });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setPhase("error");
    } finally {
      setIsImporting(false);
    }
  };

  const startPolling = useCallback(
    (jobId: string, total: number) => {
      if (pollRef.current) clearInterval(pollRef.current);

      pollRef.current = setInterval(async () => {
        try {
          const status = await getImportStatus(jobId);
          const progress = status.progress || 0;
          const imported = Math.round((progress / 100) * total);
          store.setImportProgress(progress, imported, total);

          if (status.status === "SUCCESS") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            store.setImportProgress(100, total, total);
            await loadProducts();
            setPhase("success");
            toast({ type: "success", title: `${formatNumber(total)} products imported!` });
          } else if (status.status === "FAILURE") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setError(status.message || "Import failed");
            setPhase("error");
          }
        } catch {
          // Continue polling on network errors
        }
      }, 1500);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const loadProducts = async () => {
    try {
      const data = await listProducts(0, 50);
      store.setProducts(data.products);
    } catch {
      // Products will load on next visit
    }
  };

  const handleContinue = () => {
    store.setStep(2);
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Hero */}
      <div className="text-center mb-8">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-5"
        >
          <Package className="w-8 h-8 text-primary" />
        </motion.div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">
          {"Let's import your products"}
        </h1>
        <p className="text-muted-foreground text-base max-w-md mx-auto">
          Connect your Shopify store to get started with competitive price tracking
        </p>
      </div>

      <AnimatePresence mode="wait">
        {/* Connect Phase */}
        {phase === "connect" && (
          <motion.div
            key="connect"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <Card className="p-6 sm:p-8 border-border/50 bg-card/50 backdrop-blur-sm">
              <div className="space-y-6">
                <div>
                  <label
                    htmlFor="shop-domain"
                    className="block text-sm font-medium mb-2"
                  >
                    Your Shopify store domain
                  </label>
                  <div className="flex gap-3">
                    <Input
                      id="shop-domain"
                      placeholder="mystore.myshopify.com"
                      value={shopDomain}
                      onChange={(e) => setShopDomain(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleConnect()}
                      icon={<ShoppingBag className="w-4 h-4" />}
                      className="flex-1"
                    />
                    <Button
                      size="lg"
                      onClick={handleConnect}
                      loading={isConnecting}
                      disabled={!shopDomain.trim()}
                      className="shrink-0"
                    >
                      Connect
                      <ExternalLink className="w-4 h-4" />
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {"You'll be redirected to Shopify to authorize the connection"}
                  </p>
                </div>

                {/* Mock preview of what will be imported */}
                <div className="pt-4 border-t border-border/50">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                    What we&apos;ll import
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {["Product titles & descriptions", "Pricing & variants", "Product images", "SKUs & handles", "Tags & categories", "Inventory status"].map(
                      (item) => (
                        <div
                          key={item}
                          className="flex items-center gap-2 text-sm text-muted-foreground"
                        >
                          <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
                          {item}
                        </div>
                      )
                    )}
                  </div>
                </div>
              </div>
            </Card>
          </motion.div>
        )}

        {/* Importing Phase */}
        {phase === "importing" && (
          <motion.div
            key="importing"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <Card className="p-6 sm:p-8 border-border/50 bg-card/50 backdrop-blur-sm">
              <div className="space-y-6">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                    >
                      <RefreshCw className="w-5 h-5 text-primary" />
                    </motion.div>
                  </div>
                  <div>
                    <h3 className="font-semibold">Importing products...</h3>
                    <p className="text-sm text-muted-foreground">
                      {store.importedCount > 0
                        ? `${formatNumber(store.importedCount)} / ${formatNumber(store.totalCount)} products`
                        : "Connecting to your store..."}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Progress
                    value={store.importProgress}
                    className="h-3"
                    indicatorClassName="bg-gradient-to-r from-primary to-primary/80"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{Math.round(store.importProgress)}% complete</span>
                    <span>
                      {formatNumber(store.importedCount)} of{" "}
                      {formatNumber(store.totalCount)}
                    </span>
                  </div>
                </div>

                {/* Skeleton preview */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="p-3 rounded-lg bg-muted/50">
                      <Skeleton className="w-full h-20 rounded-md mb-2" />
                      <Skeleton className="h-3 w-3/4 mb-1" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </motion.div>
        )}

        {/* Success Phase */}
        {phase === "success" && (
          <motion.div
            key="success"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <Card className="p-6 sm:p-8 border-success/20 bg-card/50 backdrop-blur-sm">
              <div className="space-y-6">
                <div className="text-center">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{
                      type: "spring",
                      stiffness: 300,
                      damping: 20,
                      delay: 0.1,
                    }}
                    className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-success/10 mb-4"
                  >
                    <CheckCircle2 className="w-7 h-7 text-success" />
                  </motion.div>
                  <h3 className="text-lg font-semibold mb-1">
                    {formatNumber(
                      store.products.length || store.importedCount
                    )}{" "}
                    products imported!
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    Your product catalog is ready for price tracking
                  </p>
                </div>

                {/* Product preview grid */}
                {store.products.length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 max-h-72 overflow-y-auto pr-1">
                    {store.products.slice(0, 9).map((product, i) => (
                      <motion.div
                        key={product.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.05 }}
                        className="p-3 rounded-lg bg-muted/30 border border-border/30"
                      >
                        <div className="w-full h-16 rounded-md bg-muted/50 flex items-center justify-center mb-2 overflow-hidden">
                          {product.image_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={product.image_url}
                              alt={product.title}
                              className="w-full h-full object-cover rounded-md"
                            />
                          ) : (
                            <ImageIcon className="w-5 h-5 text-muted-foreground/50" />
                          )}
                        </div>
                        <p className="text-xs font-medium truncate">
                          {product.title}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          ${product.our_price.toFixed(2)}
                        </p>
                      </motion.div>
                    ))}
                  </div>
                )}

                {store.products.length > 9 && (
                  <p className="text-center text-xs text-muted-foreground">
                    +{formatNumber(store.products.length - 9)} more products
                  </p>
                )}

                <Button
                  size="lg"
                  className="w-full"
                  onClick={handleContinue}
                >
                  Continue to Add Competitor
                  <ArrowRight className="w-4 h-4" />
                </Button>
              </div>
            </Card>
          </motion.div>
        )}

        {/* Error Phase */}
        {phase === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <Card className="p-6 sm:p-8 border-destructive/20 bg-card/50 backdrop-blur-sm">
              <div className="space-y-4 text-center">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-destructive/10 mb-2">
                  <AlertCircle className="w-7 h-7 text-destructive" />
                </div>
                <h3 className="text-lg font-semibold">Import Failed</h3>
                <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                  {error || "Something went wrong during the import. Please try again."}
                </p>
                <div className="flex gap-3 justify-center">
                  <Button variant="outline" onClick={() => setPhase("connect")}>
                    Start Over
                  </Button>
                  <Button onClick={handleStartImport} loading={isImporting}>
                    <RefreshCw className="w-4 h-4" />
                    Retry Import
                  </Button>
                </div>
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}
