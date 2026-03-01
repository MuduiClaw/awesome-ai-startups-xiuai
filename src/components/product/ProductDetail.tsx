import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { FundingBadge } from "./FundingBadge";
import { ProductIcon } from "./ProductIcon";
import { formatCurrency, formatPricingModel, formatSlug, formatSlugLocalized, formatNumber, localized, localizeCountry } from "@/lib/utils";
import type { ProductDetail as ProductDetailType, Locale, PlatformAvailability } from "@/lib/types";
import type { Dictionary } from "@/lib/dict";

interface ProductDetailProps {
  product: ProductDetailType;
  locale: Locale;
  dict: Dictionary;
  categoryLabel?: string;
}

// ─── Modality & Platform display maps ────────────────────────────────
const modalityDisplay: Record<string, { icon: string; en: string; zh: string }> = {
  text: { icon: "\u2328\uFE0F", en: "Text", zh: "文本" },
  image: { icon: "\uD83D\uDDBC\uFE0F", en: "Image", zh: "图像" },
  audio: { icon: "\uD83C\uDFB5", en: "Audio", zh: "音频" },
  video: { icon: "\uD83C\uDFA5", en: "Video", zh: "视频" },
  code: { icon: "\uD83D\uDCBB", en: "Code", zh: "代码" },
  "3d": { icon: "\uD83D\uDCBF", en: "3D", zh: "3D" },
  multimodal: { icon: "\u2726", en: "Multimodal", zh: "多模态" },
};

const platformDisplay: Record<string, { icon: string; en: string; zh: string }> = {
  web: { icon: "\uD83C\uDF10", en: "Web", zh: "网页端" },
  ios: { icon: "\uD83C\uDF4E", en: "iOS", zh: "iOS" },
  android: { icon: "\uD83E\uDD16", en: "Android", zh: "安卓" },
  desktop: { icon: "\uD83D\uDDA5\uFE0F", en: "Desktop", zh: "桌面端" },
  mobile: { icon: "\uD83D\uDCF1", en: "Mobile", zh: "移动端" },
  "self-hosted": { icon: "\uD83D\uDD27", en: "Self-Hosted", zh: "自部署" },
  api: { icon: "\u2699\uFE0F", en: "API", zh: "API" },
};

const languageZhMap: Record<string, string> = {
  "English": "英语", "Chinese": "中文", "Spanish": "西班牙语",
  "French": "法语", "German": "德语", "Japanese": "日语",
  "Korean": "韩语", "Portuguese": "葡萄牙语", "Russian": "俄语",
  "Italian": "意大利语", "Dutch": "荷兰语", "Arabic": "阿拉伯语",
  "Hindi": "印地语", "Turkish": "土耳其语", "Polish": "波兰语",
  "Swedish": "瑞典语", "Thai": "泰语", "Vietnamese": "越南语",
  "Indonesian": "印尼语", "Malay": "马来语", "Czech": "捷克语",
  "Romanian": "罗马尼亚语", "Danish": "丹麦语", "Finnish": "芬兰语",
  "Norwegian": "挪威语", "Hebrew": "希伯来语", "Ukrainian": "乌克兰语",
  "Hungarian": "匈牙利语", "Greek": "希腊语", "Bengali": "孟加拉语",
};

const pricingVariant: Record<string, "success" | "info" | "warning" | "purple" | "default"> = {
  free: "success",
  "open-source": "success",
  freemium: "info",
  "free-trial": "info",
  paid: "warning",
  enterprise: "purple",
  "usage-based": "warning",
};

// ─── Section component ───────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <h2 className="font-semibold text-lg mb-4">{title}</h2>
      {children}
    </Card>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between items-start gap-4">
      <dt className="text-muted-foreground shrink-0">{label}</dt>
      <dd className="font-medium text-right">{children}</dd>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────
export function ProductDetail({ product, locale, dict, categoryLabel }: ProductDetailProps) {
  const t = dict.product;
  const name = localized(product, locale, "name");
  const description = localized(product, locale, "description");
  const company = product.company;
  const isDeprecated = product.status === "deprecated" || product.status === "discontinued";

  return (
    <div className="max-w-5xl mx-auto">
      {/* Back link */}
      <Link
        href={`/${locale}`}
        className="text-sm text-primary hover:underline mb-6 inline-block"
      >
        &larr; {t.back_to_list}
      </Link>

      {/* ─── Hero Section ─────────────────────────────────────────── */}
      <div className={`mb-8 ${isDeprecated ? "opacity-70" : ""}`}>
        <div className="flex flex-col sm:flex-row items-start gap-6">
          <ProductIcon iconUrl={product.icon_url} name={name} size="lg" />
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h1 className="text-3xl font-bold">{name}</h1>
                {company?.name && (
                  <p className="text-muted-foreground mt-1">
                    {t.company_name}: {company.name}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {product.product_url && (
                  <a
                    href={product.product_url}
                    className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                  >
                    {t.visit_product}
                  </a>
                )}
                {company?.website && company.website !== product.product_url && (
                  <a
                    href={company.website}
                    className="rounded-lg border border-border px-4 py-2.5 text-sm font-medium hover:bg-muted transition-colors"
                  >
                    {t.visit_company}
                  </a>
                )}
              </div>
            </div>
            <p className="text-muted-foreground mt-3 text-base leading-relaxed">{description}</p>
          </div>
        </div>
      </div>

      {/* ─── Quick Stats Bar ──────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 mb-8">
        <Badge variant="primary">
          {categoryLabel || product.category.replace(/-/g, " ")}
        </Badge>
        {product.sub_category && (
          <Badge variant="outline">{formatSlugLocalized(product.sub_category, locale)}</Badge>
        )}
        {product.product_type && product.product_type !== "other" && (
          <Badge>{formatSlugLocalized(product.product_type, locale)}</Badge>
        )}
        {product.pricing?.model && (
          <Badge variant={pricingVariant[product.pricing.model] || "default"}>
            {formatPricingModel(product.pricing.model, locale)}
          </Badge>
        )}
        {product.pricing?.has_free_tier && (
          <Badge variant="success">{t.free_tier}: \u2713</Badge>
        )}
        {product.open_source && <Badge variant="success">{t.open_source}</Badge>}
        {product.api_available && <Badge variant="info">{t.api_available}</Badge>}
        {product.status && product.status !== "active" && (
          <Badge variant="warning">{product.status}</Badge>
        )}
      </div>

      {/* ─── Modalities & Platforms Chips ──────────────────────────── */}
      {((product.modalities && product.modalities.length > 0) ||
        (product.platforms && product.platforms.length > 0)) && (
        <div className="flex flex-wrap items-center gap-4 mb-8 text-sm">
          {product.modalities && product.modalities.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground font-medium">{t.modalities}:</span>
              <div className="flex gap-1.5">
                {product.modalities.map((m) => {
                  const d = modalityDisplay[m];
                  return (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs"
                    >
                      {d?.icon || ""} {d ? d[locale] : formatSlugLocalized(m, locale)}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
          {product.platforms && product.platforms.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground font-medium">{t.platforms}:</span>
              <div className="flex gap-1.5">
                {product.platforms.map((p) => {
                  const d = platformDisplay[p];
                  return (
                    <span
                      key={p}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs"
                    >
                      {d?.icon || ""} {d ? d[locale] : formatSlugLocalized(p, locale)}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ─── Main Grid ────────────────────────────────────────────── */}
      <div className="grid gap-6 md:grid-cols-2">

        {/* Overview Card */}
        <Section title={t.overview}>
          <dl className="space-y-3 text-sm">
            {product.product_type && (
              <InfoRow label={t.product_type}>
                {formatSlugLocalized(product.product_type, locale)}
              </InfoRow>
            )}
            {product.status && (
              <InfoRow label={t.status}>
                <span className="capitalize">{product.status}</span>
              </InfoRow>
            )}
            {company?.founded_year && (
              <InfoRow label={t.founded}>{company.founded_year}</InfoRow>
            )}
            {company?.headquarters && (
              <InfoRow label={t.headquarters}>
                {company.headquarters.city}
                {company.headquarters.state && `, ${company.headquarters.state}`}
                , {locale === "zh"
                    ? (company.headquarters.country_zh || localizeCountry(company.headquarters.country, locale))
                    : company.headquarters.country}
              </InfoRow>
            )}
            {company?.employee_count_range && (
              <InfoRow label={t.employees}>{company.employee_count_range}</InfoRow>
            )}
            {product.release_date && (
              <InfoRow label={t.release_date}>{product.release_date}</InfoRow>
            )}
            {product.license && (
              <InfoRow label={t.license}>{product.license}</InfoRow>
            )}
          </dl>
        </Section>

        {/* Funding Card */}
        {company?.funding && (
          <Section title={t.funding}>
            <dl className="space-y-3 text-sm">
              {company.funding.total_raised_usd !== undefined && company.funding.total_raised_usd > 0 && (
                <InfoRow label={t.total_raised}>
                  <span className="text-lg font-bold text-primary">
                    {formatCurrency(company.funding.total_raised_usd)}
                  </span>
                </InfoRow>
              )}
              {company.funding.last_round && (
                <InfoRow label={t.last_round}>
                  <FundingBadge round={company.funding.last_round} />
                </InfoRow>
              )}
              {company.funding.last_round_date && (
                <InfoRow label={t.last_round_date}>
                  {company.funding.last_round_date}
                </InfoRow>
              )}
              {company.funding.valuation_usd !== undefined && company.funding.valuation_usd > 0 && (
                <InfoRow label={t.valuation}>
                  {formatCurrency(company.funding.valuation_usd)}
                </InfoRow>
              )}
              {company.funding.investors && company.funding.investors.length > 0 && (
                <div>
                  <dt className="text-muted-foreground mb-2 text-sm">{t.investors}</dt>
                  <dd className="flex flex-wrap gap-1.5">
                    {company.funding.investors.map((inv) => (
                      <Badge key={inv} variant="outline">{inv}</Badge>
                    ))}
                  </dd>
                </div>
              )}
            </dl>
          </Section>
        )}

        {/* Technical Details Card */}
        {(product.architecture || product.parameter_count || product.context_window ||
          product.api_available || product.repository_url || product.github_stars) && (
          <Section title={t.technical}>
            <dl className="space-y-3 text-sm">
              {product.architecture && (
                <InfoRow label={t.architecture}>{product.architecture}</InfoRow>
              )}
              {product.parameter_count && (
                <InfoRow label={t.parameters}>{product.parameter_count}</InfoRow>
              )}
              {product.context_window && product.context_window > 0 && (
                <InfoRow label={t.context_window}>
                  {formatNumber(product.context_window)} tokens
                </InfoRow>
              )}
              {product.api_available && (
                <InfoRow label={t.api_available}>
                  {product.api_docs_url ? (
                    <a href={product.api_docs_url} className="text-primary hover:underline">
                      {t.api_docs}
                    </a>
                  ) : (
                    t.yes
                  )}
                </InfoRow>
              )}
              {product.repository_url && (
                <InfoRow label={t.repository}>
                  <a href={product.repository_url} className="text-primary hover:underline truncate max-w-[200px] inline-block">
                    {product.repository_url.replace(/^https?:\/\/(www\.)?/, "")}
                  </a>
                </InfoRow>
              )}
              {product.github_stars && product.github_stars > 0 && (
                <InfoRow label={t.github_stars}>
                  \u2B50 {formatNumber(product.github_stars)}
                </InfoRow>
              )}
            </dl>
          </Section>
        )}

        {/* Use Cases & Target Audience Card */}
        {((product.use_cases && product.use_cases.length > 0) ||
          (product.target_audience && product.target_audience.length > 0)) && (
          <Section title={t.use_cases}>
            <div className="space-y-4">
              {product.target_audience && product.target_audience.length > 0 && (
                <div>
                  <h3 className="text-sm text-muted-foreground mb-2">{t.target_audience}</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {product.target_audience.map((a, i) => (
                      <Badge key={a} variant="purple">
                        {locale === "zh" && product.target_audience_zh?.[i]
                          ? product.target_audience_zh[i]
                          : formatSlugLocalized(a, locale)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {product.use_cases && product.use_cases.length > 0 && (
                <div>
                  <h3 className="text-sm text-muted-foreground mb-2">{t.use_cases}</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {product.use_cases.slice(0, 12).map((uc, i) => (
                      <Badge key={uc}>
                        {locale === "zh" && product.use_cases_zh?.[i]
                          ? product.use_cases_zh[i]
                          : formatSlugLocalized(uc, locale)}
                      </Badge>
                    ))}
                    {product.use_cases.length > 12 && (
                      <Badge variant="outline">+{product.use_cases.length - 12}</Badge>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Competitors Card */}
        {product.competitors && product.competitors.length > 0 && (
          <Section title={t.competitors}>
            <div className="flex flex-wrap gap-2">
              {product.competitors.map((comp) => (
                <Link
                  key={comp}
                  href={`/${locale}/products/${comp}`}
                  className="inline-flex items-center rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted transition-colors"
                >
                  {formatSlugLocalized(comp, locale)}
                </Link>
              ))}
            </div>
          </Section>
        )}

        {/* Hiring & Team Card */}
        {product.hiring && (product.hiring.is_hiring || product.hiring.tech_stack?.length) && (
          <Section title={t.hiring}>
            <div className="space-y-4 text-sm">
              {product.hiring.is_hiring !== undefined && (
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full ${product.hiring.is_hiring ? "bg-green-500" : "bg-gray-400"}`} />
                  <span className="font-medium">
                    {product.hiring.is_hiring
                      ? `${t.is_hiring} \u2713`
                      : `${t.is_hiring}: ${t.no}`}
                  </span>
                  {product.hiring.careers_url && (
                    <a
                      href={product.hiring.careers_url}
                      className="text-primary hover:underline ml-2"
                    >
                      {t.careers} &rarr;
                    </a>
                  )}
                </div>
              )}
              {product.hiring.tech_stack && product.hiring.tech_stack.length > 0 && (
                <div>
                  <h3 className="text-muted-foreground mb-2">{t.tech_stack}</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {product.hiring.tech_stack.map((tech) => (
                      <Badge key={tech} variant="info">{tech}</Badge>
                    ))}
                  </div>
                </div>
              )}
              {product.hiring.positions && product.hiring.positions.length > 0 && (
                <div>
                  <h3 className="text-muted-foreground mb-2">{t.open_positions}</h3>
                  <ul className="space-y-1.5">
                    {product.hiring.positions.slice(0, 5).map((pos, i) => (
                      <li key={i} className="flex items-center justify-between">
                        {pos.url ? (
                          <a href={pos.url} className="text-primary hover:underline">{pos.title}</a>
                        ) : (
                          <span>{pos.title}</span>
                        )}
                        {pos.location && (
                          <span className="text-muted-foreground text-xs">{pos.location}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Section>
        )}

        {/* Key People Card */}
        {product.key_people && product.key_people.length > 0 && (
          <Section title={t.key_people}>
            <ul className="space-y-3">
              {product.key_people.map((person) => (
                <li key={person.name} className="flex items-center justify-between text-sm">
                  <span className="font-medium">
                    {person.profile_url ? (
                      <a href={person.profile_url} className="text-primary hover:underline">
                        {person.name}
                      </a>
                    ) : (
                      person.name
                    )}
                    {person.is_founder && (
                      <span className="ml-1.5 text-xs text-muted-foreground">({t.founder})</span>
                    )}
                  </span>
                  <span className="text-muted-foreground">{person.title}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* App Store Card */}
        {product.app_store && (product.app_store.apple_store_url || product.app_store.google_play_url) && (
          <Section title={t.app_store}>
            <div className="space-y-3 text-sm">
              {product.app_store.rating && (
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-bold">{product.app_store.rating}</span>
                  <div className="flex">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <span
                        key={star}
                        className={star <= Math.round(product.app_store!.rating!)
                          ? "text-yellow-500"
                          : "text-gray-300"}
                      >
                        \u2605
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {product.app_store.apple_store_url && (
                  <a
                    href={product.app_store.apple_store_url}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors"
                  >
                    \uD83C\uDF4E App Store
                  </a>
                )}
                {product.app_store.google_play_url && (
                  <a
                    href={product.app_store.google_play_url}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors"
                  >
                    \uD83E\uDD16 Google Play
                  </a>
                )}
              </div>
            </div>
          </Section>
        )}

        {/* Platform Availability Card */}
        {product.platform_availability && Object.values(product.platform_availability).some((v) => v != null) && (
          <Section title={t.platform_availability}>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
              {(["web", "ios", "android", "mac", "windows", "linux"] as (keyof PlatformAvailability)[]).map((plat) => {
                const val = product.platform_availability?.[plat];
                if (val == null) return null;
                const icons: Record<string, string> = { web: "\uD83C\uDF10", ios: "\uD83C\uDF4E", android: "\uD83E\uDD16", mac: "\uD83D\uDDA5\uFE0F", windows: "\uD83E\uDE9F", linux: "\uD83D\uDC27" };
                const labels: Record<string, Record<string, string>> = {
                  en: { web: "Web", ios: "iOS", android: "Android", mac: "macOS", windows: "Windows", linux: "Linux" },
                  zh: { web: "网页端", ios: "iOS", android: "安卓", mac: "macOS", windows: "Windows", linux: "Linux" },
                };
                return (
                  <div key={plat} className="flex items-center gap-2">
                    <span>{icons[plat]}</span>
                    <span>{labels[locale][plat]}</span>
                    <span className={val ? "text-green-600" : "text-gray-400"}>{val ? "\u2713" : "\u2717"}</span>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* AI Origin Card */}
        {product.ai_native && product.ai_native.is_native != null && (
          <Section title={t.ai_origin}>
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <Badge variant={product.ai_native.is_native ? "success" : "info"}>
                  {product.ai_native.is_native ? t.ai_native : t.ai_added_later}
                </Badge>
                {product.ai_native.ai_since && (
                  <span className="text-muted-foreground">{t.ai_since}: {product.ai_native.ai_since}</span>
                )}
              </div>
              {product.ai_native.note && (
                <p className="text-muted-foreground">
                  {locale === "zh" && product.ai_native.note_zh ? product.ai_native.note_zh : product.ai_native.note}
                </p>
              )}
            </div>
          </Section>
        )}

        {/* Social Links Card */}
        {company?.social && (
          <Section title={t.social}>
            <div className="flex flex-wrap gap-2">
              {company.social.github && (
                <a href={company.social.github}
                   className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors">
                  GitHub
                </a>
              )}
              {company.social.twitter && (
                <a href={company.social.twitter}
                   className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors">
                  Twitter / X
                </a>
              )}
              {company.social.linkedin && (
                <a href={company.social.linkedin}
                   className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors">
                  LinkedIn
                </a>
              )}
              {company.social.crunchbase && (
                <a href={company.social.crunchbase}
                   className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted transition-colors">
                  Crunchbase
                </a>
              )}
            </div>
          </Section>
        )}

        {/* Supported Languages (if available) */}
        {product.supported_languages && product.supported_languages.length > 0 && (
          <Section title={t.supported_languages}>
            <div className="flex flex-wrap gap-1.5">
              {product.supported_languages.slice(0, 30).map((lang, i) => (
                <Badge key={lang} variant="outline">
                  {locale === "zh"
                    ? (product.supported_languages_zh?.[i] || languageZhMap[lang] || lang)
                    : lang}
                </Badge>
              ))}
              {product.supported_languages.length > 30 && (
                <Badge variant="outline">+{product.supported_languages.length - 30}</Badge>
              )}
            </div>
          </Section>
        )}
      </div>

      {/* ─── Tags Section (full width) ────────────────────────────── */}
      {product.tags && product.tags.length > 0 && (
        <div className="mt-6">
          <Card>
            <h2 className="font-semibold text-lg mb-3">{t.tags}</h2>
            <div className="flex flex-wrap gap-1.5">
              {product.tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ─── Data Sources & Meta (full width footer) ──────────────── */}
      {(product.sources?.length || product.meta?.last_updated) && (
        <div className="mt-6">
          <Card className="bg-muted/30">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs text-muted-foreground">
              <div className="flex flex-wrap items-center gap-3">
                {product.sources && product.sources.length > 0 && (
                  <>
                    <span className="font-medium">{t.data_sources}:</span>
                    {product.sources.map((s, i) => (
                      <a key={i} href={s.url} className="hover:underline">
                        {s.source_name}
                      </a>
                    ))}
                  </>
                )}
              </div>
              <div className="flex items-center gap-4">
                {product.meta?.added_date && (
                  <span>{t.added_date}: {product.meta.added_date}</span>
                )}
                {product.meta?.last_updated && (
                  <span>{t.last_updated}: {product.meta.last_updated}</span>
                )}
                {product.meta?.data_quality_score != null && (
                  <span title="Data quality score">
                    {"\u2605"} {(product.meta.data_quality_score * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
