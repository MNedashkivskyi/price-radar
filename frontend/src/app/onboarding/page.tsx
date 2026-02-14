"use client";

import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard";
import { ToastProvider } from "@/components/ui/toast";

export default function OnboardingPage() {
  return (
    <ToastProvider>
      <OnboardingWizard />
    </ToastProvider>
  );
}
