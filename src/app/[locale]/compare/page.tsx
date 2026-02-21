import { getDictionary } from "@/lib/i18n";
import { ComparePageClient } from "./ComparePageClient";
import type { Locale } from "@/lib/types";

export const revalidate = 3600;

export default async function ComparePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const dict = await getDictionary(locale as Locale);

  // Products are loaded client-side from /data/products-lite.json
  return (
    <ComparePageClient
      locale={locale as Locale}
      dict={dict}
    />
  );
}
