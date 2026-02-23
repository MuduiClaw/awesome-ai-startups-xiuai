"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatCurrency, formatRound, localized } from "@/lib/utils";
import type { ProductIndexEntry, Locale } from "@/lib/types";
import type { Dictionary } from "@/lib/dict";

interface ComparePageClientProps {
  locale: Locale;
  dict: Dictionary;
}

interface SearchResponse {
  results: ProductIndexEntry[];
  total: number;
}

export function ComparePageClient({ locale, dict }: ComparePageClientProps) {
  const [selected, setSelected] = useState<ProductIndexEntry[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState<ProductIndexEntry[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const t = dict.product;
  const c = dict.compare;

  const selectedSlugs = useMemo(() => selected.map((p) => p.slug), [selected]);

  // Use a ref so the effect callback always sees the latest slugs
  // without needing selectedSlugs in the dependency array
  const selectedSlugsRef = useRef(selectedSlugs);
  selectedSlugsRef.current = selectedSlugs;

  // Debounced search via API
  useEffect(() => {
    if (!searchTerm.trim()) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsSearching(true);
      try {
        const params = new URLSearchParams({
          q: searchTerm.trim(),
          limit: "10",
        });
        const res = await fetch(`/api/search?${params}`, {
          signal: controller.signal,
        });
        const data: SearchResponse = await res.json();
        // Filter out already-selected products
        setSearchResults(
          data.results.filter((p) => !selectedSlugsRef.current.includes(p.slug)).slice(0, 5),
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchTerm]);

  const addProduct = useCallback(
    (product: ProductIndexEntry) => {
      if (selected.length < 3 && !selectedSlugs.includes(product.slug)) {
        setSelected([...selected, product]);
        setSearchTerm("");
        setSearchResults([]);
      }
    },
    [selected, selectedSlugs],
  );

  const removeProduct = (slug: string) => {
    setSelected(selected.filter((s) => s.slug !== slug));
  };

  const compareFields = [
    { key: "category", label: t.category, render: (p: ProductIndexEntry) => p.category.replace(/-/g, " ") },
    { key: "product_type", label: t.product_type, render: (p: ProductIndexEntry) => p.product_type || c.no_data },
    { key: "country", label: t.country, render: (p: ProductIndexEntry) => p.country },
    { key: "city", label: t.city, render: (p: ProductIndexEntry) => p.city },
    { key: "total_raised", label: t.total_raised, render: (p: ProductIndexEntry) => p.total_raised_usd ? formatCurrency(p.total_raised_usd) : c.no_data },
    { key: "valuation", label: t.valuation, render: (p: ProductIndexEntry) => p.valuation_usd ? formatCurrency(p.valuation_usd) : c.no_data },
    { key: "last_round", label: t.last_round, render: (p: ProductIndexEntry) => p.last_round ? formatRound(p.last_round) : c.no_data },
    { key: "employees", label: t.employees, render: (p: ProductIndexEntry) => p.employee_count_range || c.no_data },
    { key: "open_source", label: t.open_source, render: (p: ProductIndexEntry) => p.open_source ? t.yes : t.no },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">{c.title}</h1>

      {selected.length < 3 && (
        <div className="mb-6 relative">
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={c.add_product}
            className="w-full max-w-md rounded-lg border border-border bg-background px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          {searchResults.length > 0 && (
            <div className="absolute top-full left-0 mt-1 w-full max-w-md bg-background border border-border rounded-lg shadow-lg z-10">
              {searchResults.map((p) => (
                <button
                  key={p.slug}
                  onClick={() => addProduct(p)}
                  className="block w-full text-left px-4 py-2 text-sm hover:bg-muted transition-colors"
                >
                  {localized(p, locale, "name")}
                </button>
              ))}
            </div>
          )}
          {isSearching && searchTerm.trim() && searchResults.length === 0 && (
            <div className="absolute top-full left-0 mt-1 w-full max-w-md bg-background border border-border rounded-lg shadow-lg z-10 p-3 text-sm text-muted-foreground animate-pulse">
              Loading...
            </div>
          )}
        </div>
      )}

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6">
          {selected.map((p) => (
            <Badge key={p.slug} variant="primary">
              {localized(p, locale, "name")}
              <button
                onClick={() => removeProduct(p.slug)}
                className="ml-2 hover:text-red-500"
              >
                x
              </button>
            </Badge>
          ))}
        </div>
      )}

      {selected.length >= 2 ? (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-3 px-4 font-medium text-muted-foreground">
                    {c.field}
                  </th>
                  {selected.map((p) => (
                    <th key={p.slug} className="text-left py-3 px-4 font-semibold">
                      {localized(p, locale, "name")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareFields.map((field) => (
                  <tr key={field.key} className="border-b border-border last:border-0">
                    <td className="py-3 px-4 text-muted-foreground">{field.label}</td>
                    {selected.map((p) => (
                      <td key={p.slug} className="py-3 px-4">
                        {field.render(p)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <p className="text-center text-muted-foreground py-12">
          {c.select_prompt}
        </p>
      )}
    </div>
  );
}
