"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { ProductCard } from "./ProductCard";
import { Pagination } from "@/components/ui/Pagination";
import { Button } from "@/components/ui/Button";
import { localized } from "@/lib/utils";
import type { ProductIndexEntry, Locale, Category } from "@/lib/types";
import type { HomeDict } from "@/lib/dict";

interface ProductGridProps {
  initialProducts: ProductIndexEntry[];
  totalProducts: number;
  categories: Category[];
  categoryCounts: Record<string, number>;
  locale: Locale;
  dict: { home: HomeDict };
}

const ITEMS_PER_PAGE = 12;

export function ProductGrid({
  initialProducts,
  totalProducts,
  categories,
  categoryCounts,
  locale,
  dict,
}: ProductGridProps) {
  const [allProducts, setAllProducts] = useState<ProductIndexEntry[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"funding" | "name">("funding");
  const [currentPage, setCurrentPage] = useState(1);

  // The working dataset: full dataset once loaded, otherwise initial page
  const products = allProducts ?? initialProducts;
  const isFullDataLoaded = allProducts !== null;

  // Lazy-load the full dataset from the static JSON file
  const loadFullData = useCallback(() => {
    if (allProducts || isLoading) return;
    setIsLoading(true);
    fetch("/data/products-lite.json")
      .then((res) => res.json())
      .then((data: ProductIndexEntry[]) => {
        setAllProducts(data);
        setIsLoading(false);
      })
      .catch(() => {
        setIsLoading(false);
      });
  }, [allProducts, isLoading]);

  // Start loading when user interacts (filter, sort, or page 2+)
  useEffect(() => {
    // Preload on idle after initial render
    if (typeof window !== "undefined" && "requestIdleCallback" in window) {
      const id = window.requestIdleCallback(() => loadFullData(), { timeout: 3000 });
      return () => window.cancelIdleCallback(id);
    } else {
      const timer = setTimeout(loadFullData, 1500);
      return () => clearTimeout(timer);
    }
  }, [loadFullData]);

  const categoryMap = useMemo(
    () => new Map(categories.map((c) => [c.id, c])),
    [categories],
  );

  const filtered = useMemo(() => {
    let result = products;

    if (selectedCategory) {
      result = result.filter((p) => p.category === selectedCategory);
    }

    if (sortBy === "name") {
      result = [...result].sort((a, b) => a.name.localeCompare(b.name));
    }
    // Default "funding" sort is already applied from the SQL query

    return result;
  }, [products, selectedCategory, sortBy]);

  const totalPages = Math.ceil(filtered.length / ITEMS_PER_PAGE);
  const paged = filtered.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  const handleCategoryChange = (cat: string | null) => {
    if (!isFullDataLoaded) loadFullData();
    setSelectedCategory(cat);
    setCurrentPage(1);
  };

  const handleSortChange = (s: "funding" | "name") => {
    if (!isFullDataLoaded && s === "name") loadFullData();
    setSortBy(s);
  };

  const handlePageChange = (page: number) => {
    if (!isFullDataLoaded) loadFullData();
    setCurrentPage(page);
  };

  return (
    <div>
      {/* Category filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        <Button
          variant={selectedCategory === null ? "default" : "outline"}
          size="sm"
          onClick={() => handleCategoryChange(null)}
        >
          {dict.home.filter_all} ({totalProducts})
        </Button>
        {categories.map((cat) => {
          const count = categoryCounts[cat.id] || 0;
          if (count === 0) return null;
          const label = localized(cat, locale, "name");
          return (
            <Button
              key={cat.id}
              variant={selectedCategory === cat.id ? "default" : "outline"}
              size="sm"
              onClick={() => handleCategoryChange(cat.id)}
            >
              {label} ({count})
            </Button>
          );
        })}
      </div>

      {/* Sort controls */}
      <div className="flex items-center gap-2 mb-6 text-sm">
        <span className="text-muted-foreground">{dict.home.sort_by}:</span>
        {(["funding", "name"] as const).map((s) => (
          <Button
            key={s}
            variant={sortBy === s ? "default" : "ghost"}
            size="sm"
            onClick={() => handleSortChange(s)}
          >
            {dict.home[`sort_${s}`]}
          </Button>
        ))}
        {isLoading && (
          <span className="text-xs text-muted-foreground animate-pulse ml-2">
            Loading...
          </span>
        )}
      </div>

      {/* Grid */}
      {paged.length === 0 ? (
        <p className="text-center text-muted-foreground py-12">{dict.home.no_results}</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {paged.map((product) => {
            const cat = categoryMap.get(product.category);
            const catLabel = cat ? localized(cat, locale, "name") : undefined;
            return (
              <ProductCard key={product.slug} product={product} locale={locale} categoryLabel={catLabel} />
            );
          })}
        </div>
      )}

      <Pagination
        currentPage={currentPage}
        totalPages={isFullDataLoaded ? totalPages : Math.ceil(totalProducts / ITEMS_PER_PAGE)}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
