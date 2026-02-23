"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { SearchBar } from "@/components/search/SearchBar";
import { SearchResults } from "@/components/search/SearchResults";
import { FilterPanel } from "@/components/search/FilterPanel";
import type { ProductIndexEntry, Locale, Category } from "@/lib/types";
import type { Dictionary } from "@/lib/dict";

interface SearchPageClientProps {
  categories: Category[];
  countries: string[];
  locale: Locale;
  dict: Dictionary;
}

interface SearchResponse {
  results: ProductIndexEntry[];
  total: number;
}

export function SearchPageClient({
  categories,
  countries,
  locale,
  dict,
}: SearchPageClientProps) {
  const [results, setResults] = useState<ProductIndexEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchResults = useCallback(
    async (q: string, category: string | null, country: string | null) => {
      // Abort any in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsLoading(true);
      try {
        const params = new URLSearchParams({ limit: "50" });
        if (q.trim()) params.set("q", q.trim());
        if (category) params.set("category", category);
        if (country) params.set("country", country);

        const res = await fetch(`/api/search?${params}`, {
          signal: controller.signal,
        });
        const data: SearchResponse = await res.json();
        setResults(data.results);
        setHasSearched(true);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  // Debounced search on query/filter changes
  useEffect(() => {
    // Only search when there's a query or a filter applied
    if (!query.trim() && !selectedCategory && !selectedCountry) {
      setResults([]);
      setHasSearched(false);
      return;
    }

    const timer = setTimeout(() => {
      fetchResults(query, selectedCategory, selectedCountry);
    }, 300);
    return () => clearTimeout(timer);
  }, [query, selectedCategory, selectedCountry, fetchResults]);

  const handleSearch = useCallback((q: string) => {
    setQuery(q);
  }, []);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">{dict.search.title}</h1>

      <div className="mb-6">
        <SearchBar
          placeholder={dict.search.placeholder}
          onSearch={handleSearch}
        />
      </div>

      <div className="mb-6">
        <FilterPanel
          categories={categories}
          countries={countries}
          selectedCategory={selectedCategory}
          selectedCountry={selectedCountry}
          onCategoryChange={setSelectedCategory}
          onCountryChange={setSelectedCountry}
          locale={locale}
          dict={dict}
        />
      </div>

      {isLoading ? (
        <p className="text-center text-muted-foreground py-12 animate-pulse">Loading...</p>
      ) : hasSearched ? (
        <SearchResults
          results={results}
          locale={locale}
          categories={categories}
          noResultsText={dict.search.no_results}
          resultsText={dict.search.results}
        />
      ) : null}
    </div>
  );
}
