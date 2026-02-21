import { getProductBySlug, getAllSlugs, getCategories } from "@/lib/data";
import { getDictionary, locales } from "@/lib/i18n";
import { ProductDetail } from "@/components/product/ProductDetail";
import { localized } from "@/lib/utils";
import type { Locale } from "@/lib/types";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

// ISR: regenerate cached pages every hour
export const revalidate = 3600;
// Allow slugs not in generateStaticParams to be rendered on-demand
export const dynamicParams = true;

// Pre-render only the top 1000 products at build time (by funding desc).
// The rest are generated on-demand via ISR when first visited.
const BUILD_TIME_LIMIT = 1000;

export function generateStaticParams() {
  const slugs = getAllSlugs().slice(0, BUILD_TIME_LIMIT);
  const params: { locale: string; slug: string }[] = [];
  for (const locale of locales) {
    for (const slug of slugs) {
      params.push({ locale, slug });
    }
  }
  return params;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  const product = getProductBySlug(slug);
  const name = localized(product, locale as Locale, "name");
  const description = localized(product, locale as Locale, "description");
  return {
    title: `${name} - AI Product Data`,
    description,
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;

  let product;
  try {
    product = getProductBySlug(slug);
  } catch {
    notFound();
  }

  const dict = await getDictionary(locale as Locale);
  const categories = getCategories();
  const cat = categories.find((c) => c.id === product.category);
  const categoryLabel = cat ? localized(cat, locale as Locale, "name") : undefined;

  return <ProductDetail product={product} locale={locale as Locale} dict={dict} categoryLabel={categoryLabel} />;
}
