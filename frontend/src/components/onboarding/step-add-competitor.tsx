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
  AlertCircle,
  Sparkles,
  Building2,
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
    formState: { errors },
  } = useForm<CompetitorFormData>({
    resolver: zodResolver(competitorSchema),
    defaultValues: {
      name: store.competitor?.name || "",
      domain: store.competitor?.domain || "",
    },
  });

  const watchedName = watch("name");
  const watchedDomain = watch("domain");

  const handleUrlDetect = async () => {
    if (!urlInput.trim() || !isValidUrl(urlInput)) return;

    setIsDetecting(true);
    setDetectedInfo(null);

    try {
      // Try API detection first
      const result = await detectCompetitor(urlInput);
      setDetectedInfo(result);
      setValue("name", result.name);
      setValue("domain", result.domain);
    } catch {
      // Fallback to client-side extraction
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
      // Auto-detect after paste
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

  const onSubmit = async (data: CompetitorFormData) => {
    setIsSubmitting(true);
    try {
      const competitor = await createCompetitor({
        name: data.name,
        domain: data.domain,
        logo_url: detectedInfo?.logo_url,
      });
      store.setCompetitor(competitor);
      store.completeStep(2);
      store.setStep(3);
      toast({ type: "success", title: `${data.name} added as competitor` });
    } catch (err) {
      // Store locally and continue if API fails
      store.setCompetitor({
        id: 0,
        shop_id: 0,
        name: data.name,
        domain: data.domain,
        logo_url: detectedInfo?.logo_url || null,
        status: "pending",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      store.completeStep(2);
      store.setStep(3);
      toast({
        type: "info",
        title: `${data.name} saved locally`,
        description: "Will sync when connected",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleBack = () => {
    store.setStep(1);
  };

  const handleSkip = () => {
    store.completeStep(2);
    store.setStep(3);
  };

  const examples = [
    { name: "Amazon", domain: "amazon.com" },
    { name: "Walmart", domain: "walmart.com" },
    { name: "Target", domain: "target.com" },
    { name: "Best Buy", domain: "bestbuy.com" },
  ];

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
          {"Who's your main competitor?"}
        </h1>
        <p className="text-muted-foreground text-base max-w-md mx-auto">
          Add a competitor to start tracking their prices against yours
        </p>
      </div>

      {/* Mode selector */}
      <div className="flex gap-3 mb-6">
        <button
          onClick={() => setMode("form")}
          className={cn(
            "flex-1 p-4 rounded-xl border text-left transition-all duration-200",
            mode === "form"
              ? "border-primary/50 bg-primary/5"
              : "border-border/50 bg-card/50 hover:border-border"
          )}
        >
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "w-9 h-9 rounded-lg flex items-center justify-center",
                mode === "form" ? "bg-primary/10" : "bg-muted"
              )}
            >
              <Building2
                className={cn(
                  "w-4 h-4",
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
            "flex-1 p-4 rounded-xl border text-left transition-all duration-200",
            mode === "url"
              ? "border-primary/50 bg-primary/5"
              : "border-border/50 bg-card/50 hover:border-border"
          )}
        >
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "w-9 h-9 rounded-lg flex items-center justify-center",
                mode === "url" ? "bg-primary/10" : "bg-muted"
              )}
            >
              <Sparkles
                className={cn(
                  "w-4 h-4",
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

      <Card className="p-6 sm:p-8 border-border/50 bg-card/50 backdrop-blur-sm">
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
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

          {/* Manual form fields (always visible, pre-filled if detected) */}
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

          {/* Examples */}
          {!watchedName && !watchedDomain && (
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

          {/* Preview card */}
          {watchedName && watchedDomain && (
            <motion.div
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-4 rounded-xl bg-muted/30 border border-border/30"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary font-bold text-sm">
                  {watchedName.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{watchedName}</p>
                  <p className="text-xs text-muted-foreground">{watchedDomain}</p>
                </div>
                <Badge variant="outline" className="shrink-0">
                  Ready to add
                </Badge>
              </div>
            </motion.div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            <Button type="button" variant="ghost" onClick={handleBack}>
              <ArrowLeft className="w-4 h-4" />
              Back
            </Button>
            <div className="flex gap-3">
              <Button type="button" variant="ghost" size="sm" onClick={handleSkip} className="text-muted-foreground">
                Skip
              </Button>
              <Button
                type="submit"
                loading={isSubmitting}
                disabled={!watchedName || !watchedDomain}
              >
                Add Competitor
                <ArrowRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </form>
      </Card>
    </div>
  );
}
