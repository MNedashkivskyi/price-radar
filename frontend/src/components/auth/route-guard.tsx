"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";

/**
 * Loading spinner shown while auth status is being resolved.
 * Prevents flash-of-wrong-content and premature redirects.
 */
function AuthLoading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

// ── RequireAuth ───────────────────────────────────────────────────

/**
 * Guard for routes that require completed onboarding (e.g. /dashboard/*).
 *
 * Supports two modes:
 *   - **Connected**: authenticated via JWT + backend says onboarding done
 *   - **Demo**: no JWT, but local onboarding store says complete
 *
 * Redirect logic:
 *   - Still loading → show spinner (no premature redirect)
 *   - Onboarding complete (either source) → render children
 *   - Onboarding NOT complete → redirect to /onboarding
 *
 * The key fix: we wait for the auth provider to finish its check
 * (which includes token refresh) BEFORE making any redirect decision.
 * This eliminates the race condition that caused the infinite loop.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, onboardingComplete } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return; // Wait for auth resolution

    // Onboarding not done (regardless of auth status) → go to wizard
    if (!onboardingComplete) {
      router.replace("/onboarding");
    }
  }, [status, onboardingComplete, router]);

  if (status === "loading") return <AuthLoading />;
  if (!onboardingComplete) return <AuthLoading />;

  return <>{children}</>;
}

// ── RequireOnboarding ─────────────────────────────────────────────

/**
 * Guard for the /onboarding route.
 *
 * Redirect logic:
 *   - Onboarding already complete (backend or local) → /dashboard
 *   - Otherwise → render children (show onboarding wizard)
 *
 * This guard ensures /onboarding is ONLY shown to users who genuinely
 * need it, regardless of token or auth state.
 */
export function RequireOnboarding({ children }: { children: React.ReactNode }) {
  const { status, onboardingComplete } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;

    // Already onboarded → go straight to dashboard.
    if (onboardingComplete) {
      router.replace("/dashboard");
    }
  }, [status, onboardingComplete, router]);

  if (status === "loading") return <AuthLoading />;

  // If already onboarded, show loading while redirect happens
  if (onboardingComplete) return <AuthLoading />;

  return <>{children}</>;
}
