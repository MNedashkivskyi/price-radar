"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users,
  Globe,
  Link2,
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  Sparkles,
  Building2,
  X,
  Plus,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useOnboarding } from "@/lib/onboarding-store";
import { cn, extractDomain, isValidUrl } from "@/lib/utils";
import { createCompetitor, detectCompetitor } from "@/lib/api";

type Mode = "form" | "url";

const competitorSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  domain: z
    .string()
    .min(1, "Domain is required")
    .regex(
      /^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$/,
      "Enter a valid domain (e.g., amazon.com)"
    ),
});

type CompetitorFormData = z.infer<typeof competitorSchema>;

export function StepAddCompetitor() {
  const store = useOnboarding();
  const { toast } = useToast();
  const [mode, setMode] = useState<Mode>("form");
  const [urlInput, setUrlInput] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [detectedInfo, setDetectedInfo] = useState<{
    name: string;
    domain: string;
    logo_url?: string;
  } | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset: resetForm,
    formState: { errors },
  } = useForm<CompetitorFormData>({
    resolver: zodResolver(competitorSchema),
    defaultValues: { name: "", domain: "" },
  });

  const watchedName = watch("name");
  const watchedDomain = watch("domain");

  const handleUrlDetect = async () => {
    if (!urlInput.trim() || !isValidUrl(urlInput)) return;

    setIsDetecting(true);
    setDetectedInfo(null);

    try {
      const result = await detectCompetitor(urlInput);
      setDetectedInfo(result);
      setValue("name", result.name);
      setValue("domain", result.domain);
    } catch {
      const domain = extractDomain(urlInput);
      const name = domain.split(".")[0];
      const capitalized = name.charAt(0).toUpperCase() + name.slice(1);
      setDetectedInfo({ name: capitalized, domain });
      setValue("name", capitalized);
      setValue("domain", domain);
    } finally {
      setIsDetecting(false);
    }
  };

  const handleUrlPaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData("text");
    if (isValidUrl(pasted)) {
      setUrlInput(pasted);
      setTimeout(() => {
        const domain = extractDomain(pasted);
        const name = domain.split(".")[0];
        const capitalized = name.charAt(0).toUpperCase() + name.slice(1);
        setDetectedInfo({ name: capitalized, domain });
        setValue("name", capitalized);
        setValue("domain", domain);
      }, 100);
    }
  };

  const clearForm = () => {
    resetForm({ name: "", domain: "" });
    setUrlInput("");
    setDetectedInfo(null);
  };

  const onSubmit = async (data: CompetitorFormData) => {
    // Check if already added
    if (store.competitors.some((c) => c.domain === data.domain)) {
      toast({ type: "error", title: `${data.domain} is already added` });
      return;
    }

    setIsSubmitting(true);
    try {
      const competitor = await createCompetitor({
        name: data.name,
        domain: data.domain,
        logo_url: detectedInfo?.logo_url,
      });
      store.addCompetitor(competitor);
      toast({ type: "success", title: `${data.name} added` });
      clearForm();
    } catch {
      // Store locally if API fails
      store.addCompetitor({
        id: 0,
        shop_id: 0,
        name: data.name,
        domain: data.domain,
        logo_url: detectedInfo?.logo_url || null,
        status: "pending",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      toast({ type: "info", title: `${data.name} saved locally` });
      clearForm();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemove = (domain: string) => {
    store.removeCompetitor(domain);
  };

  const handleBack = () => {
    store.setStep(1);
  };

  const handleContinue = () => {
    store.setStep(3);
  };

  const examples = [
    { name: "Amazon", domain: "amazon.com" },
    { name: "Walmart", domain: "walmart.com" },
    { name: "Target", domain: "target.com" },
    { name: "Best Buy", domain: "bestbuy.com" },
  ];

  const hasCompetitors = store.competitors.length > 0;

  return (
    <div className="max-w-2xl mx-auto">
      {/* Hero */}
      <div className="text-center mb-8">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-5"
        >
          <Users className="w-8 h-8 text-primary" />
        </motion.div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">
          Add your competitors
        </h1>
        <p className="text-muted-foreground text-base max-w-md mx-auto">
          Add one or more competitors to track their prices against yours
        </p>
      </div>

      {/* Already-added competitors list */}
      <AnimatePresence>
        {hasCompetitors && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-6"
          >
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
              {store.competitors.length} competitor{store.competitors.length !== 1 ? "s" : ""} added
            </p>
            <div className="space-y-2">
              {store.competitors.map((comp, i) => (
                <motion.div
                  key={comp.domain}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  transition={{ delay: i * 0.05 }}
                  className="flex items-center gap-3 p-3 rounded-xl bg-muted/30 border border-border/30"
                >
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center text-primary font-bold text-sm shrink-0">
                    {comp.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{comp.name}</p>
                    <p className="text-xs text-muted-foreground">{comp.domain}</p>
                  </div>
                  <Badge variant="success" className="shrink-0 text-[10px]">
                    Added
                  </Badge>
                  <button
                    type="button"
                    onClick={() => handleRemove(comp.domain)}
                    className="p-1.5 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                    aria-label={`Remove ${comp.name}`}
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Add another competitor section */}
      <Card className="p-6 sm:p-8 border-border/50 bg-card/50 backdrop-blur-sm">
        {hasCompetitors && (
          <div className="flex items-center gap-2 mb-6">
            <Plus className="w-4 h-4 text-primary" />
            <p className="text-sm font-medium">Add another competitor</p>
          </div>
        )}

        {/* Mode selector */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={() => setMode("form")}
            className={cn(
              "flex-1 p-3 rounded-xl border text-left transition-all duration-200",
              mode === "form"
                ? "border-primary/50 bg-primary/5"
                : "border-border/50 bg-card/50 hover:border-border"
            )}
          >
            <div className="flex items-center gap-2.5">
              <div
                className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center",
                  mode === "form" ? "bg-primary/10" : "bg-muted"
                )}
              >
                <Building2
                  className={cn(
                    "w-3.5 h-3.5",
                    mode === "form" ? "text-primary" : "text-muted-foreground"
                  )}
                />
              </div>
              <div>
                <p className="text-sm font-medium">Enter details</p>
                <p className="text-xs text-muted-foreground">Name + domain</p>
              </div>
            </div>
          </button>
          <button
            onClick={() => setMode("url")}
            className={cn(
              "flex-1 p-3 rounded-xl border text-left transition-all duration-200",
              mode === "url"
                ? "border-primary/50 bg-primary/5"
                : "border-border/50 bg-card/50 hover:border-border"
            )}
          >
            <div className="flex items-center gap-2.5">
              <div
                className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center",
                  mode === "url" ? "bg-primary/10" : "bg-muted"
                )}
              >
                <Sparkles
                  className={cn(
                    "w-3.5 h-3.5",
                    mode === "url" ? "text-primary" : "text-muted-foreground"
                  )}
                />
              </div>
              <div>
                <p className="text-sm font-medium">Paste a URL</p>
                <p className="text-xs text-muted-foreground">
                  {"We'll figure it out"}
                </p>
              </div>
            </div>
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          <AnimatePresence mode="wait">
            {mode === "url" && (
              <motion.div
                key="url-mode"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="space-y-4"
              >
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Competitor product URL
                  </label>
                  <div className="flex gap-3">
                    <Input
                      placeholder="https://competitor.com/products/example"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      onPaste={handleUrlPaste}
                      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleUrlDetect())}
                      icon={<Link2 className="w-4 h-4" />}
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={handleUrlDetect}
                      loading={isDetecting}
                      disabled={!urlInput.trim()}
                    >
                      Detect
                    </Button>
                  </div>
                </div>

                {detectedInfo && (
                  <motion.div
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center gap-3 p-3 rounded-lg bg-success/5 border border-success/20"
                  >
                    <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{detectedInfo.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {detectedInfo.domain}
                      </p>
                    </div>
                    {detectedInfo.logo_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={detectedInfo.logo_url}
                        alt=""
                        className="w-8 h-8 rounded-md"
                      />
                    )}
                  </motion.div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Manual form fields */}
          <div className={cn(mode === "url" && detectedInfo ? "pt-2 border-t border-border/50" : "")}>
            {mode === "url" && detectedInfo && (
              <p className="text-xs text-muted-foreground mb-4">
                Confirm or edit the detected details below
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label htmlFor="comp-name" className="block text-sm font-medium mb-2">
                  Competitor name
                </label>
                <Input
                  id="comp-name"
                  placeholder="e.g., Amazon"
                  {...register("name")}
                  error={errors.name?.message}
                  icon={<Building2 className="w-4 h-4" />}
                />
              </div>
              <div>
                <label htmlFor="comp-domain" className="block text-sm font-medium mb-2">
                  Domain
                </label>
                <Input
                  id="comp-domain"
                  placeholder="e.g., amazon.com"
                  {...register("domain")}
                  error={errors.domain?.message}
                  icon={<Globe className="w-4 h-4" />}
                />
              </div>
            </div>
          </div>

          {/* Quick-add examples (only when form is empty and no competitors yet) */}
          {!watchedName && !watchedDomain && !hasCompetitors && (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Popular competitors
              </p>
              <div className="flex flex-wrap gap-2">
                {examples.map((ex) => (
                  <button
                    key={ex.domain}
                    type="button"
                    onClick={() => {
                      setValue("name", ex.name);
                      setValue("domain", ex.domain);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                  >
                    <Globe className="w-3 h-3" />
                    {ex.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Add button */}
          <div className="flex justify-end">
            <Button
              type="submit"
              loading={isSubmitting}
              disabled={!watchedName || !watchedDomain}
            >
              <Plus className="w-4 h-4" />
              Add Competitor
            </Button>
          </div>
        </form>
      </Card>

      {/* Bottom navigation */}
      <div className="flex items-center justify-between mt-8">
        <Button variant="ghost" onClick={handleBack}>
          <ArrowLeft className="w-4 h-4" />
          Back
        </Button>
        <Button
          size="lg"
          onClick={handleContinue}
          disabled={!hasCompetitors}
        >
          Continue to Map URLs
          <ArrowRight className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
