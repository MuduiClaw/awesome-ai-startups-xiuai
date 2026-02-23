import { getCategories, getCountries } from "@/lib/data";
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
  const countries = getCountries();

  return (
    <SearchPageClient
      categories={categories}
      countries={countries}
      locale={locale as Locale}
      dict={dict}
    />
  );
}
