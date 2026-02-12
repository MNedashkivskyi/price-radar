"use client";

import { useOnboarding } from "@/lib/onboarding-store";
import { WizardLayout } from "./wizard-layout";
import { StepImportProducts } from "./step-import-products";
import { StepAddCompetitor } from "./step-add-competitor";
import { StepMapUrls } from "./step-map-urls";

export function OnboardingWizard() {
  const { currentStep } = useOnboarding();

  return (
    <WizardLayout>
      {currentStep === 1 && <StepImportProducts />}
      {currentStep === 2 && <StepAddCompetitor />}
      {currentStep === 3 && <StepMapUrls />}
    </WizardLayout>
  );
}
