"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { Product, Competitor } from "./api";

interface OnboardingState {
  currentStep: number;
  // Step 1
  isConnected: boolean;
  importJobId: string | null;
  importProgress: number;
  importedCount: number;
  totalCount: number;
  products: Product[];
  // Step 2
  competitors: Competitor[];
  // Step 3
  mappings: Map<number, string>; // productId -> url
}

const STORAGE_KEY = "pr_onboarding";

let state: OnboardingState = {
  currentStep: 1,
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
    state = {
      ...state,
      currentStep: data.currentStep ?? 1,
      isConnected: data.isConnected ?? false,
      products: data.products ?? [],
      competitors,
      mappings: new Map(data.mappings ?? []),
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
    state = {
      ...state,
      competitors: state.competitors.filter((c) => c.domain !== domain),
    };
    emitChange();
  }, []);

  const setMapping = useCallback((productId: number, url: string) => {
    const next = new Map(state.mappings);
    if (url) {
      next.set(productId, url);
    } else {
      next.delete(productId);
    }
    state = { ...state, mappings: next };
    emitChange();
  }, []);

  const setBulkMappings = useCallback(
    (entries: [number, string][]) => {
      const next = new Map(state.mappings);
      entries.forEach(([id, url]) => {
        if (url) next.set(id, url);
      });
      state = { ...state, mappings: next };
      emitChange();
    },
    []
  );

  const reset = useCallback(() => {
    state = {
      currentStep: 1,
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
    setStep,
    setConnected,
    setImportProgress,
    setImportJobId,
    setProducts,
    addCompetitor,
    removeCompetitor,
    setMapping,
    setBulkMappings,
    reset,
  };
}
