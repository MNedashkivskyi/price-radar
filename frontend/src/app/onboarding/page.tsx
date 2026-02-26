"use client";

import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard";
import { RequireOnboarding } from "@/components/auth/route-guard";
import { ToastProvider } from "@/components/ui/toast";

export default function OnboardingPage() {
  return (
    <RequireOnboarding>
      <ToastProvider>
        <OnboardingWizard />
      </ToastProvider>
    </RequireOnboarding>
  );
}
