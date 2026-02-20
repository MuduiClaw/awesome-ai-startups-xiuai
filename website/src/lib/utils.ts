export function formatCurrency(amount: number): string {
  if (amount >= 1_000_000_000) {
    return `$${(amount / 1_000_000_000).toFixed(1)}B`;
  }
  if (amount >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(0)}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return `$${amount}`;
}

export function formatRound(round: string): string {
  const map: Record<string, string> = {
    "pre-seed": "Pre-Seed",
    seed: "Seed",
    "series-a": "Series A",
    "series-b": "Series B",
    "series-c": "Series C",
    "series-d": "Series D",
    "series-e": "Series E",
    "series-f": "Series F",
    growth: "Growth",
    ipo: "IPO",
    unknown: "Unknown",
  };
  return map[round] || round;
}

export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/** Resolve a bilingual field based on locale. Falls back to the base field. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function localized(item: any, locale: "en" | "zh", field: string = "name"): string {
  if (locale === "zh") {
    const zhValue = item[`${field}_zh`];
    if (typeof zhValue === "string" && zhValue) return zhValue;
  }
  return (item[field] as string) ?? "";
}

/** Format a pricing model string for display. */
export function formatPricingModel(model: string): string {
  const map: Record<string, string> = {
    free: "Free",
    freemium: "Freemium",
    "free-trial": "Free Trial",
    paid: "Paid",
    enterprise: "Enterprise",
    "open-source": "Open Source",
    "usage-based": "Usage-Based",
  };
  return map[model] || model;
}

/** Format a slug-style string to title case for display. */
export function formatSlug(slug: string): string {
  return slug
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Format a number with K/M/B suffix. */
export function formatNumber(num: number): string {
  if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(0)}K`;
  return String(num);
}
