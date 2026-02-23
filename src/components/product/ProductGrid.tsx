"use client";

import { useState, useMemo, useCallback } from "react";
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

interface PageResponse {
  total: number;
  products: ProductIndexEntry[];
  page: number;
  totalPages: number;
}

export function ProductGrid({
  initialProducts,
  totalProducts,
  categories,
  categoryCounts,
  locale,
  dict,
}: ProductGridProps) {
  const [products, setProducts] = useState<ProductIndexEntry[]>(initialProducts);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"funding" | "name">("funding");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalFiltered, setTotalFiltered] = useState(totalProducts);
  const totalPages = Math.ceil(totalFiltered / ITEMS_PER_PAGE);

  const fetchPage = useCallback(
    async (page: number, category: string | null, sort: "funding" | "name") => {
      setIsLoading(true);
      try {
        const params = new URLSearchParams({
          page: String(page),
          limit: String(ITEMS_PER_PAGE),
        });
        if (category) params.set("category", category);
        if (sort === "name") params.set("sort", "name");

        const res = await fetch(`/api/products?${params}`);
        const data: PageResponse = await res.json();
        setProducts(data.products);
        setTotalFiltered(data.total);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const categoryMap = useMemo(
    () => new Map(categories.map((c) => [c.id, c])),
    [categories],
  );

  const handleCategoryChange = (cat: string | null) => {
    setSelectedCategory(cat);
    setCurrentPage(1);
    fetchPage(1, cat, sortBy);
  };

  const handleSortChange = (s: "funding" | "name") => {
    setSortBy(s);
    setCurrentPage(1);
    fetchPage(1, selectedCategory, s);
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    fetchPage(page, selectedCategory, sortBy);
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
      {products.length === 0 ? (
        <p className="text-center text-muted-foreground py-12">{dict.home.no_results}</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((product) => {
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
        totalPages={totalPages}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
