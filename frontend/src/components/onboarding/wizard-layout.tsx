"use client";

import { motion } from "framer-motion";
import { Check, Package, Users, Link2, Save } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useOnboarding } from "@/lib/onboarding-store";

const steps = [
  { number: 1, title: "Import Products", icon: Package },
  { number: 2, title: "Add Competitor", icon: Users },
  { number: 3, title: "Map URLs", icon: Link2 },
] as const;

interface WizardLayoutProps {
  children: React.ReactNode;
}

export function WizardLayout({ children }: WizardLayoutProps) {
  const { currentStep, completedSteps, setStep } = useOnboarding();

  const canNavigateTo = (step: number) => {
    if (step <= currentStep) return true;
    if (completedSteps.has(step - 1)) return true;
    return false;
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Gradient background accent */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-primary/5 rounded-full blur-3xl" />
      </div>

      <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        {/* Header */}
        <header className="text-center mb-8 sm:mb-12">
          <div className="inline-flex items-center gap-2 text-primary font-semibold text-lg mb-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Package className="w-4 h-4" />
            </div>
            Price Radar
          </div>
          <p className="text-muted-foreground text-sm">
            Set up your competitive pricing intelligence in minutes
          </p>
        </header>

        {/* Progress stepper */}
        <nav aria-label="Onboarding progress" className="mb-10 sm:mb-14">
          <ol className="flex items-center justify-center gap-0">
            {steps.map((step, i) => {
              const isActive = currentStep === step.number;
              const isCompleted = completedSteps.has(step.number);
              const isClickable = canNavigateTo(step.number);
              const Icon = step.icon;

              return (
                <li key={step.number} className="flex items-center">
                  <button
                    onClick={() => isClickable && setStep(step.number)}
                    disabled={!isClickable}
                    className={cn(
                      "flex items-center gap-2.5 px-4 py-2.5 rounded-xl transition-all duration-300 group",
                      isActive && "bg-primary/10",
                      isClickable && !isActive && "hover:bg-muted cursor-pointer",
                      !isClickable && "opacity-50 cursor-not-allowed"
                    )}
                    aria-current={isActive ? "step" : undefined}
                  >
                    <div
                      className={cn(
                        "relative w-9 h-9 rounded-xl flex items-center justify-center text-sm font-medium transition-all duration-300 shrink-0",
                        isCompleted && "bg-success text-white",
                        isActive && !isCompleted && "bg-primary text-white shadow-md shadow-primary/25",
                        !isActive && !isCompleted && "bg-muted text-muted-foreground"
                      )}
                    >
                      {isCompleted ? (
                        <motion.div
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ type: "spring", stiffness: 300, damping: 20 }}
                        >
                          <Check className="w-4 h-4" />
                        </motion.div>
                      ) : (
                        <Icon className="w-4 h-4" />
                      )}
                    </div>
                    <div className="hidden sm:block text-left">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                        Step {step.number}
                      </div>
                      <div
                        className={cn(
                          "text-sm font-medium transition-colors",
                          isActive ? "text-foreground" : "text-muted-foreground"
                        )}
                      >
                        {step.title}
                      </div>
                    </div>
                  </button>

                  {i < steps.length - 1 && (
                    <div className="w-8 sm:w-16 h-px bg-border mx-1 sm:mx-2">
                      <motion.div
                        className="h-full bg-primary"
                        initial={{ width: "0%" }}
                        animate={{
                          width: completedSteps.has(step.number) ? "100%" : "0%",
                        }}
                        transition={{ duration: 0.4, ease: "easeOut" }}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Step content */}
        <main>
          <motion.div
            key={currentStep}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            {children}
          </motion.div>
        </main>

        {/* Footer */}
        <footer className="mt-10 flex items-center justify-center">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground text-xs gap-1.5"
            onClick={() => {
              // Already persisted automatically
            }}
          >
            <Save className="w-3.5 h-3.5" />
            Progress saved automatically
          </Button>
        </footer>
      </div>
    </div>
  );
}
