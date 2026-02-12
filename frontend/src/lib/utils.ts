import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat().format(n);
}

export function extractDomain(url: string): string {
  try {
    const u = new URL(url.startsWith("http") ? url : `https://${url}`);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function isValidUrl(str: string): boolean {
  try {
    const url = new URL(str.startsWith("http") ? str : `https://${str}`);
    return !!url.hostname.includes(".");
  } catch {
    return false;
  }
}

export function isValidDomain(str: string): boolean {
  return /^[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,}$/.test(str);
}
