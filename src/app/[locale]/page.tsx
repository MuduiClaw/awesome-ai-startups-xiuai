import { getAllProducts, getCategories, getCategoryCounts } from "@/lib/data";
import { getDictionary } from "@/lib/i18n";
import { ProductGrid } from "@/components/product/ProductGrid";
import type { Locale } from "@/lib/types";

export const revalidate = 3600;

const INITIAL_PAGE_SIZE = 24;

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const dict = await getDictionary(locale as Locale);
  const { products, total } = getAllProducts();
  const categories = getCategories();
  const categoryCounts = getCategoryCounts();

  // Only embed the first page in HTML — additional pages load via /api/products
  const initialProducts = products.slice(0, INITIAL_PAGE_SIZE);

  return (
    <div>
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4">{dict.home.hero_title}</h1>
        <p className="text-lg text-muted-foreground">
          {dict.home.hero_subtitle.replace("{count}", String(total))}
        </p>
      </div>
      <ProductGrid
        initialProducts={initialProducts}
        totalProducts={total}
        categories={categories}
        categoryCounts={categoryCounts}
        locale={locale as Locale}
        dict={dict}
      />
    </div>
  );
}
