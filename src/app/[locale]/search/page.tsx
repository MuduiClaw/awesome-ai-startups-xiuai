import { getCategories } from "@/lib/data";
import { getDictionary } from "@/lib/i18n";
import { SearchPageClient } from "./SearchPageClient";
import type { Locale } from "@/lib/types";

export const revalidate = 3600;

export default async function SearchPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const dict = await getDictionary(locale as Locale);
  const categories = getCategories();

  // Products are loaded client-side from /data/products-lite.json
  // instead of being embedded in the HTML (saves ~17 MB per page)
  return (
    <SearchPageClient
      categories={categories}
      locale={locale as Locale}
      dict={dict}
    />
  );
}
