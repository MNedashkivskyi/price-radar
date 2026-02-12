"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { Product, Competitor, CompetitorMapping } from "./api";

interface OnboardingState {
  currentStep: number;
  completedSteps: Set<number>;
  // Step 1
  isConnected: boolean;
  importJobId: string | null;
  importProgress: number;
  importedCount: number;
  totalCount: number;
  products: Product[];
  // Step 2
  competitor: Competitor | null;
  // Step 3
  mappings: Map<number, string>; // productId -> url
}

const STORAGE_KEY = "pr_onboarding";

let state: OnboardingState = {
  currentStep: 1,
  completedSteps: new Set(),
  isConnected: false,
  importJobId: null,
  importProgress: 0,
  importedCount: 0,
  totalCount: 0,
  products: [],
  competitor: null,
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
    completedSteps: Array.from(state.completedSteps),
    isConnected: state.isConnected,
    products: state.products,
    competitor: state.competitor,
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
    state = {
      ...state,
      currentStep: data.currentStep ?? 1,
      completedSteps: new Set(data.completedSteps ?? []),
      isConnected: data.isConnected ?? false,
      products: data.products ?? [],
      competitor: data.competitor ?? null,
      mappings: new Map(data.mappings ?? []),
    };
  } catch {
    // Ignore parse errors
  }
}

// Initialize from storage
restore();

export function useOnboarding() {
  const snap = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => state
  );

  const setStep = useCallback((step: number) => {
    state = { ...state, currentStep: step };
    emitChange();
  }, []);

  const completeStep = useCallback((step: number) => {
    const next = new Set(state.completedSteps);
    next.add(step);
    state = { ...state, completedSteps: next };
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

  const setCompetitor = useCallback((competitor: Competitor | null) => {
    state = { ...state, competitor };
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
      completedSteps: new Set(),
      isConnected: false,
      importJobId: null,
      importProgress: 0,
      importedCount: 0,
      totalCount: 0,
      products: [],
      competitor: null,
      mappings: new Map(),
    };
    emitChange();
  }, []);

  return {
    ...snap,
    setStep,
    completeStep,
    setConnected,
    setImportProgress,
    setImportJobId,
    setProducts,
    setCompetitor,
    setMapping,
    setBulkMappings,
    reset,
  };
}
