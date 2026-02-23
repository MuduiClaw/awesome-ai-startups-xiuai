import { NextRequest, NextResponse } from "next/server";
import { getProductBySlug } from "@/lib/data";

export const revalidate = 3600;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;

  try {
    const product = getProductBySlug(slug);
    return NextResponse.json(product);
  } catch {
    return NextResponse.json({ error: "Product not found" }, { status: 404 });
  }
}
