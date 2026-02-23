import { NextResponse } from "next/server";
import { getCategories, getCategoryCounts } from "@/lib/data";

export const revalidate = 3600;

export async function GET() {
  const categories = getCategories();
  const counts = getCategoryCounts();

  return NextResponse.json({ categories, counts });
}
