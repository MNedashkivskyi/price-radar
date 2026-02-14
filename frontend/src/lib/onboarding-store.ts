"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { Product, Competitor } from "./api";

/**
 * Mapping key format: "productId:competitorDomain"
 * e.g. "42:amazon.com" → "https://amazon.com/dp/B09V3KXJPB"
 *
 * This allows one URL per product per competitor.
 */
interface OnboardingState {
  currentStep: number;
  isOnboardingComplete: boolean;
  // Step 1
  isConnected: boolean;
  importJobId: string | null;
  importProgress: number;
  importedCount: number;
  totalCount: number;
  products: Product[];
  // Step 2
  competitors: Competitor[];
  // Step 3  —  key = "productId:competitorDomain", value = URL
  mappings: Map<string, string>;
}

const STORAGE_KEY = "pr_onboarding";

let state: OnboardingState = {
  currentStep: 1,
  isOnboardingComplete: false,
  isConnected: false,
  importJobId: null,
  importProgress: 0,
  importedCount: 0,
  totalCount: 0,
  products: [],
  competitors: [],
  mappings: new Map(),
};

const listeners = new Set<() => void>();

function emitChange() {
  listeners.forEach((l) => l());
  persist();
}

function persist() {
  if (typeof window === "undefined") return;
  const serializable = {
    currentStep: state.currentStep,
    isOnboardingComplete: state.isOnboardingComplete,
    isConnected: state.isConnected,
    products: state.products,
    competitors: state.competitors,
    mappings: Array.from(state.mappings.entries()),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable));
}

function restore() {
  if (typeof window === "undefined") return;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    // Migrate: old single competitor -> array
    let competitors: Competitor[] = data.competitors ?? [];
    if (!Array.isArray(competitors) && data.competitor) {
      competitors = [data.competitor];
    }
    // Migrate: old numeric-keyed mappings (productId -> url) to string-keyed
    let mappings: [string, string][] = [];
    if (Array.isArray(data.mappings)) {
      mappings = data.mappings.map(([k, v]: [number | string, string]) => [
        String(k),
        v,
      ]);
    }
    state = {
      ...state,
      currentStep: data.currentStep ?? 1,
      isOnboardingComplete: data.isOnboardingComplete ?? false,
      isConnected: data.isConnected ?? false,
      products: data.products ?? [],
      competitors,
      mappings: new Map(mappings),
    };
  } catch {
    // Ignore parse errors
  }
}

restore();

/** Derive step completion from actual data, not from a manual flag. */
function isStepComplete(step: number): boolean {
  switch (step) {
    case 1:
      return state.products.length > 0;
    case 2:
      return state.competitors.length > 0;
    case 3:
      return state.mappings.size > 0;
    default:
      return false;
  }
}

/** Count unique product IDs that have at least one mapping. */
function countMappedProducts(): number {
  const productIds = new Set<string>();
  for (const key of state.mappings.keys()) {
    const pid = key.split(":")[0];
    productIds.add(pid);
  }
  return productIds.size;
}

export function useOnboarding() {
  const snap = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => state
  );

  // Derived completion — always reflects actual data
  const step1Complete = isStepComplete(1);
  const step2Complete = isStepComplete(2);
  const step3Complete = isStepComplete(3);
  const mappedProductCount = countMappedProducts();

  const setStep = useCallback((step: number) => {
    state = { ...state, currentStep: step };
    emitChange();
  }, []);

  const setConnected = useCallback((connected: boolean) => {
    state = { ...state, isConnected: connected };
    emitChange();
  }, []);

  const setImportProgress = useCallback(
    (progress: number, imported: number, total: number) => {
      state = {
        ...state,
        importProgress: progress,
        importedCount: imported,
        totalCount: total,
      };
      emitChange();
    },
    []
  );

  const setImportJobId = useCallback((jobId: string | null) => {
    state = { ...state, importJobId: jobId };
    emitChange();
  }, []);

  const setProducts = useCallback((products: Product[]) => {
    state = { ...state, products };
    emitChange();
  }, []);

  const addCompetitor = useCallback((competitor: Competitor) => {
    // Prevent duplicates by domain
    const exists = state.competitors.some(
      (c) => c.domain === competitor.domain
    );
    if (exists) return;
    state = { ...state, competitors: [...state.competitors, competitor] };
    emitChange();
  }, []);

  const removeCompetitor = useCallback((domain: string) => {
    // Also remove mappings for this competitor
    const next = new Map(state.mappings);
    for (const key of next.keys()) {
      if (key.endsWith(`:${domain}`)) {
        next.delete(key);
      }
    }
    state = {
      ...state,
      competitors: state.competitors.filter((c) => c.domain !== domain),
      mappings: next,
    };
    emitChange();
  }, []);

  /** Set a mapping for a specific product + competitor. */
  const setMapping = useCallback(
    (productId: number, competitorDomain: string, url: string) => {
      const key = `${productId}:${competitorDomain}`;
      const next = new Map(state.mappings);
      if (url) {
        next.set(key, url);
      } else {
        next.delete(key);
      }
      state = { ...state, mappings: next };
      emitChange();
    },
    []
  );

  /** Get the URL for a specific product + competitor. */
  const getMapping = useCallback(
    (productId: number, competitorDomain: string): string => {
      return state.mappings.get(`${productId}:${competitorDomain}`) || "";
    },
    []
  );

  const setBulkMappings = useCallback(
    (entries: [number, string, string][]) => {
      // entries: [productId, competitorDomain, url]
      const next = new Map(state.mappings);
      entries.forEach(([pid, domain, url]) => {
        const key = `${pid}:${domain}`;
        if (url) next.set(key, url);
      });
      state = { ...state, mappings: next };
      emitChange();
    },
    []
  );

  const completeOnboarding = useCallback(() => {
    state = { ...state, isOnboardingComplete: true };
    emitChange();
  }, []);

  const reset = useCallback(() => {
    state = {
      currentStep: 1,
      isOnboardingComplete: false,
      isConnected: false,
      importJobId: null,
      importProgress: 0,
      importedCount: 0,
      totalCount: 0,
      products: [],
      competitors: [],
      mappings: new Map(),
    };
    emitChange();
  }, []);

  return {
    ...snap,
    step1Complete,
    step2Complete,
    step3Complete,
    mappedProductCount,
    setStep,
    setConnected,
    setImportProgress,
    setImportJobId,
    setProducts,
    addCompetitor,
    removeCompetitor,
    setMapping,
    getMapping,
    setBulkMappings,
    completeOnboarding,
    reset,
  };
}
