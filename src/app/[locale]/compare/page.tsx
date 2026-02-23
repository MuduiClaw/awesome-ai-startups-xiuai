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

  // Products are searched client-side via /api/search
  return (
    <ComparePageClient
      locale={locale as Locale}
      dict={dict}
    />
  );
}
