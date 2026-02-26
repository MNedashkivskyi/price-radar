"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Package,
  Users,
  Link2,
  ArrowRight,
  Sparkles,
  BarChart3,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/components/auth/auth-provider";
import { useOnboarding } from "@/lib/onboarding-store";
import { formatNumber } from "@/lib/utils";

export function StepComplete() {
  const store = useOnboarding();
  const { recheck } = useAuth();
  const router = useRouter();
  const [showConfetti, setShowConfetti] = useState(false);

  useEffect(() => {
    // Brief delay before showing the celebration effect
    const timer = setTimeout(() => setShowConfetti(true), 300);
    return () => clearTimeout(timer);
  }, []);

  const stats = [
    {
      icon: Package,
      label: "Products imported",
      value: formatNumber(store.products.length),
      color: "text-blue-500",
      bg: "bg-blue-500/10",
    },
    {
      icon: Users,
      label: "Competitors tracked",
      value: String(store.competitors.length),
      color: "text-violet-500",
      bg: "bg-violet-500/10",
    },
    {
      icon: Link2,
      label: "URLs mapped",
      value: formatNumber(store.mappings.size),
      color: "text-emerald-500",
      bg: "bg-emerald-500/10",
    },
  ];

  return (
    <div className="max-w-xl mx-auto text-center">
      {/* Celebration hero */}
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 15, delay: 0.1 }}
        className="relative inline-flex items-center justify-center w-20 h-20 rounded-3xl bg-success/10 mb-6"
      >
        <CheckCircle2 className="w-10 h-10 text-success" />
        {showConfetti && (
          <>
            {[...Array(6)].map((_, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 1, scale: 0 }}
                animate={{
                  opacity: 0,
                  scale: 1,
                  x: Math.cos((i * Math.PI * 2) / 6) * 50,
                  y: Math.sin((i * Math.PI * 2) / 6) * 50,
                }}
                transition={{ duration: 0.6, delay: 0.2 + i * 0.05 }}
                className="absolute"
              >
                <Sparkles className="w-3.5 h-3.5 text-primary" />
              </motion.div>
            ))}
          </>
        )}
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2">
          {"You're all set!"}
        </h1>
        <p className="text-muted-foreground text-base max-w-sm mx-auto mb-8">
          Price Radar is now configured and ready to start tracking competitor prices for you.
        </p>
      </motion.div>

      {/* Summary stats */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.45 }}
        className="mb-8"
      >
        <Card className="p-6 border-border/50 bg-card/50 backdrop-blur-sm">
          <div className="grid grid-cols-3 gap-4">
            {stats.map((stat, i) => {
              const Icon = stat.icon;
              return (
                <motion.div
                  key={stat.label}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 + i * 0.1 }}
                  className="flex flex-col items-center gap-2"
                >
                  <div
                    className={`w-10 h-10 rounded-xl ${stat.bg} flex items-center justify-center`}
                  >
                    <Icon className={`w-5 h-5 ${stat.color}`} />
                  </div>
                  <div>
                    <p className="text-xl font-bold">{stat.value}</p>
                    <p className="text-xs text-muted-foreground">{stat.label}</p>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </Card>
      </motion.div>

      {/* What happens next */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7 }}
        className="mb-8"
      >
        <Card className="p-5 border-border/50 bg-card/50 backdrop-blur-sm text-left">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
            What happens next
          </p>
          <ul className="space-y-3">
            {[
              {
                icon: BarChart3,
                title: "Price monitoring begins",
                desc: "We'll start crawling competitor URLs and collecting pricing data automatically.",
              },
              {
                icon: Sparkles,
                title: "Dashboard insights",
                desc: "View price comparisons, trends, and alerts from your dashboard.",
              },
            ].map((item, i) => {
              const Icon = item.icon;
              return (
                <li key={i} className="flex gap-3">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                    <Icon className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">{item.desc}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      </motion.div>

      {/* CTA */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.85 }}
      >
        <Button
          size="lg"
          className="w-full sm:w-auto min-w-[200px]"
          onClick={async () => {
            // Refresh auth state so the route guard knows onboarding
            // is now complete, preventing the redirect loop.
            await recheck();
            router.push("/dashboard");
          }}
        >
          Go to Dashboard
          <ArrowRight className="w-4 h-4" />
        </Button>
      </motion.div>
    </div>
  );
}
