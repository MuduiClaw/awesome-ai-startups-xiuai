import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { FundingBadge } from "./FundingBadge";
import { ProductIcon } from "./ProductIcon";
import { formatCurrency, formatPricingModel, localized } from "@/lib/utils";
import type { ProductIndexEntry, Locale } from "@/lib/types";

interface ProductCardProps {
  product: ProductIndexEntry;
  locale: Locale;
  categoryLabel?: string;
}

const pricingVariant: Record<string, "success" | "info" | "warning" | "purple" | "default"> = {
  free: "success",
  "open-source": "success",
  freemium: "info",
  "free-trial": "info",
  paid: "warning",
  enterprise: "purple",
  "usage-based": "warning",
};

const modalityIcon: Record<string, string> = {
  text: "\u2328",
  image: "\uD83D\uDDBC",
  audio: "\uD83C\uDFB5",
  video: "\uD83C\uDFA5",
  code: "\u2328",
  "3d": "\uD83D\uDCBF",
  multimodal: "\u2726",
};

const platformIcon: Record<string, string> = {
  web: "\uD83C\uDF10",
  ios: "\uD83C\uDF4E",
  android: "\uD83E\uDD16",
  desktop: "\uD83D\uDDA5",
  mobile: "\uD83D\uDCF1",
  "self-hosted": "\uD83D\uDD27",
  api: "\u2699",
};

export function ProductCard({ product, locale, categoryLabel }: ProductCardProps) {
  const name = localized(product, locale, "name");
  const description = localized(product, locale, "description");
  const isDeprecated = product.status === "deprecated" || product.status === "discontinued";

  return (
    <Link href={`/${locale}/products/${product.slug}`}>
      <Card hover className={`h-full flex flex-col ${isDeprecated ? "opacity-60" : ""}`}>
        {/* Header: Icon + Name + Pricing */}
        <div className="flex items-start gap-3">
          <ProductIcon iconUrl={product.icon_url} name={name} size="sm" />
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-semibold text-lg truncate">{name}</h3>
              {product.pricing_model && (
                <Badge
                  variant={pricingVariant[product.pricing_model] || "default"}
                  className="shrink-0 text-[10px]"
                >
                  {formatPricingModel(product.pricing_model)}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              {product.company_name && (
                <span className="text-xs text-muted-foreground truncate">{product.company_name}</span>
              )}
              {product.open_source && (
                <Badge variant="success" className="text-[10px] px-1.5 py-0">OSS</Badge>
              )}
              {product.api_available && (
                <Badge variant="info" className="text-[10px] px-1.5 py-0">API</Badge>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        <p className="text-sm text-muted-foreground mt-2 line-clamp-2 flex-grow">
          {description}
        </p>

        {/* Modalities + Platforms row */}
        {((product.modalities && product.modalities.length > 0) ||
          (product.platforms && product.platforms.length > 0)) && (
          <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
            {product.modalities && product.modalities.length > 0 && (
              <span className="flex items-center gap-1" title={product.modalities.join(", ")}>
                {product.modalities.slice(0, 4).map((m) => (
                  <span key={m} className="inline-block" title={m}>
                    {modalityIcon[m] || m}
                  </span>
                ))}
              </span>
            )}
            {product.modalities && product.modalities.length > 0 &&
             product.platforms && product.platforms.length > 0 && (
              <span className="text-border">|</span>
            )}
            {product.platforms && product.platforms.length > 0 && (
              <span className="flex items-center gap-1" title={product.platforms.join(", ")}>
                {product.platforms.slice(0, 3).map((p) => (
                  <span key={p} className="inline-block" title={p}>
                    {platformIcon[p] || p}
                  </span>
                ))}
              </span>
            )}
          </div>
        )}

        {/* Category + Tags + Funding */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge variant="primary" className="text-[10px]">
            {categoryLabel || product.category.replace(/-/g, " ")}
          </Badge>
          {product.tags && product.tags.slice(0, 2).map((tag) => (
            <Badge key={tag} className="text-[10px]">{tag.replace(/-/g, " ")}</Badge>
          ))}
          {product.last_round && <FundingBadge round={product.last_round} />}
        </div>

        {/* Footer: Country + Funding/Status */}
        <div className="mt-3 pt-3 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            {product.country_code && (
              <img
                src={`https://flagcdn.com/16x12/${product.country_code.toLowerCase()}.png`}
                alt={product.country}
                className="w-4 h-3 object-cover rounded-sm"
                loading="lazy"
              />
            )}
            {product.country}
          </span>
          <span className="font-medium">
            {product.total_raised_usd > 0
              ? formatCurrency(product.total_raised_usd)
              : isDeprecated
                ? product.status
                : product.has_free_tier
                  ? "\u2713 Free Tier"
                  : product.status !== "active"
                    ? product.status
                    : ""}
          </span>
        </div>
      </Card>
    </Link>
  );
}
