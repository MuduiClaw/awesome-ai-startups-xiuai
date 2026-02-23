import { NextRequest, NextResponse } from "next/server";
import { getAllProducts } from "@/lib/data";
import { createSearchIndex } from "@/lib/search";
import type { ProductIndexEntry } from "@/lib/types";

export const revalidate = 3600;

// Cache the search index across requests within the same serverless instance
let _searchIndex: ReturnType<typeof createSearchIndex> | null = null;
let _allProducts: ProductIndexEntry[] | null = null;

function getSearchIndex() {
  if (!_searchIndex) {
    const { products } = getAllProducts();
    _allProducts = products;
    _searchIndex = createSearchIndex(products);
  }
  return { searchIndex: _searchIndex, allProducts: _allProducts! };
}

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const q = searchParams.get("q") || "";
  const category = searchParams.get("category");
  const country = searchParams.get("country");
  const limit = Math.min(100, Math.max(1, parseInt(searchParams.get("limit") || "50", 10)));

  const { searchIndex, allProducts } = getSearchIndex();

  let results: ProductIndexEntry[];

  if (q.trim()) {
    const searchResults = searchIndex.search(q);
    results = searchResults.map((r) => r.item);
  } else {
    results = allProducts;
  }

  if (category) {
    results = results.filter((p) => p.category === category);
  }

  if (country) {
    results = results.filter((p) => p.country === country);
  }

  const total = results.length;
  const limited = results.slice(0, limit);

  return NextResponse.json({ results: limited, total });
}
