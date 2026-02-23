import { NextRequest, NextResponse } from "next/server";
import { getAllProducts } from "@/lib/data";
import type { ProductIndexEntry } from "@/lib/types";

export const revalidate = 3600;

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10));
  const limitParam = searchParams.get("limit");
  const category = searchParams.get("category");
  const sort = searchParams.get("sort");

  const { products: allProducts } = getAllProducts();

  let filtered: ProductIndexEntry[] = allProducts;

  if (category) {
    filtered = filtered.filter((p) => p.category === category);
  }

  if (sort === "name") {
    filtered = [...filtered].sort((a, b) => a.name.localeCompare(b.name));
  }
  // Default sort is by funding (already applied from SQL query)

  // Allow "all" to return the full dataset (for compare page)
  if (limitParam === "all") {
    return NextResponse.json({
      total: filtered.length,
      products: filtered,
      page: 1,
      totalPages: 1,
    });
  }

  const limit = Math.min(100, Math.max(1, parseInt(limitParam || "24", 10)));
  const totalPages = Math.ceil(filtered.length / limit);
  const start = (page - 1) * limit;
  const paged = filtered.slice(start, start + limit);

  return NextResponse.json({
    total: filtered.length,
    products: paged,
    page,
    totalPages,
  });
}
