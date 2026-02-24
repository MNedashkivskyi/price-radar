"use client";

import { useEffect } from "react";
import { DashboardLayout } from "@/components/dashboard/dashboard-layout";
import { setToken } from "@/lib/api";

export default function Layout({ children }: { children: React.ReactNode }) {
  // When arriving from Shopify OAuth re-auth the URL contains ?token=<jwt>.
  // Store it and strip the query parameter so the dashboard loads normally.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
      setToken(token);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  return <DashboardLayout>{children}</DashboardLayout>;
}
