"use client";

import { useOnboarding } from "@/lib/onboarding-store";
import { WizardLayout } from "./wizard-layout";
import { StepImportProducts } from "./step-import-products";
import { StepAddCompetitor } from "./step-add-competitor";
import { StepMapUrls } from "./step-map-urls";
import { StepComplete } from "./step-complete";

export function OnboardingWizard() {
  const { currentStep } = useOnboarding();

  // Step 4 = completion screen — render without the wizard chrome
  if (currentStep === 4) {
    return (
      <div className="min-h-screen bg-background">
        <div className="fixed inset-0 pointer-events-none">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-primary/5 rounded-full blur-3xl" />
        </div>
        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-24">
          <StepComplete />
        </div>
      </div>
    );
  }

  return (
    <WizardLayout>
      {currentStep === 1 && <StepImportProducts />}
      {currentStep === 2 && <StepAddCompetitor />}
      {currentStep === 3 && <StepMapUrls />}
    </WizardLayout>
  );
}
