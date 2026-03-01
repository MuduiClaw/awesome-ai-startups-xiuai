import fs from "fs";
import path from "path";
import type {
  ProductDetail,
  ProductIndex,
  ProductIndexEntry,
  Stats,
  Category,
  TagsData,
} from "./types";

const DATA_DIR = path.join(process.cwd(), "data");
const PRODUCTS_DIR = path.join(DATA_DIR, "products");
const DB_PATH = path.join(DATA_DIR, "products.db");

// ---------------------------------------------------------------------------
// SQLite singleton (lazy-opened once per build)
// ---------------------------------------------------------------------------

type Database = import("better-sqlite3").Database;
let _db: Database | null = null;

function getDb(): Database | null {
  if (_db) return _db;
  if (!fs.existsSync(DB_PATH)) return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const BetterSqlite3 = require("better-sqlite3");
    _db = new BetterSqlite3(DB_PATH, { readonly: true }) as Database;
    return _db;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Row → typed entry conversion
// ---------------------------------------------------------------------------

interface RawIndexRow {
  slug: string;
  name: string;
  name_zh: string | null;
  description: string | null;
  description_zh: string | null;
  icon_url: string | null;
  category: string | null;
  tags_json: string | null;
  open_source: number | null;
  status: string | null;
  company_name: string | null;
  country: string | null;
  country_code: string | null;
  total_raised_usd: number | null;
  last_round: string | null;
  pricing_model: string | null;
  has_free_tier: number | null;
  modalities_json: string | null;
  platforms_json: string | null;
  api_available: number | null;
}

function rowToIndexEntry(row: RawIndexRow): ProductIndexEntry {
  // Parse tags but limit to 3 for card display
  const allTags: string[] = row.tags_json ? safeParse(row.tags_json, []) : [];
  const tags = allTags.length > 0 ? allTags.slice(0, 3) : undefined;

  // Parse modalities/platforms — these are small arrays (2-4 items)
  const modalities: string[] = row.modalities_json ? safeParse(row.modalities_json, []) : [];
  const platforms: string[] = row.platforms_json ? safeParse(row.platforms_json, []) : [];

  return {
    slug: row.slug,
    name: row.name,
    name_zh: row.name_zh || undefined,
    description: row.description ?? "",
    description_zh: row.description_zh || undefined,
    product_url: "",
    icon_url: row.icon_url || undefined,
    product_type: "",
    category: row.category ?? "",
    tags,
    open_source: row.open_source ? true : undefined,
    status: row.status ?? "active",
    company_name: row.company_name ?? "",
    company_url: "",
    country: row.country ?? "",
    country_code: row.country_code ?? "",
    city: "",
    total_raised_usd: row.total_raised_usd ?? 0,
    last_round: row.last_round ?? "",
    valuation_usd: 0,
    employee_count_range: "",
    pricing_model: row.pricing_model || undefined,
    has_free_tier: row.has_free_tier ? true : undefined,
    modalities: modalities.length > 0 ? modalities : undefined,
    platforms: platforms.length > 0 ? platforms : undefined,
    api_available: row.api_available ? true : undefined,
  };
}

function safeParse<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}

// ---------------------------------------------------------------------------
// Row → ProductDetail conversion (for individual product pages)
// ---------------------------------------------------------------------------

interface RawProductRow {
  slug: string;
  name: string;
  name_zh: string | null;
  description: string | null;
  description_zh: string | null;
  product_url: string | null;
  icon_url: string | null;
  product_type: string | null;
  category: string | null;
  sub_category: string | null;
  status: string | null;
  open_source: number | null;
  license: string | null;
  repository_url: string | null;
  company_name: string | null;
  company_name_zh: string | null;
  company_url: string | null;
  company_website: string | null;
  company_founded_year: number | null;
  company_hq_city: string | null;
  company_hq_country: string | null;
  company_hq_country_zh: string | null;
  company_hq_country_code: string | null;
  company_employee_count_range: string | null;
  funding_total_raised_usd: number | null;
  funding_last_round: string | null;
  funding_last_round_date: string | null;
  funding_valuation_usd: number | null;
  tags_json: string | null;
  keywords_json: string | null;
  key_people_json: string | null;
  sources_json: string | null;
  social_json: string | null;
  funding_investors_json: string | null;
  added_date: string | null;
  last_updated: string | null;
  data_quality_score: number | null;
  // Rich fields
  pricing_model: string | null;
  has_free_tier: number | null;
  modalities_json: string | null;
  platforms_json: string | null;
  target_audience_json: string | null;
  target_audience_zh_json: string | null;
  use_cases_json: string | null;
  use_cases_zh_json: string | null;
  supported_languages_zh_json: string | null;
  competitors_json: string | null;
  based_on_json: string | null;
  used_by_json: string | null;
  hiring_json: string | null;
  app_store_json: string | null;
  platform_availability_json: string | null;
  ai_native_json: string | null;
  api_available: number | null;
  api_docs_url: string | null;
  architecture: string | null;
  parameter_count: string | null;
  context_window: number | null;
  supported_languages_json: string | null;
  release_date: string | null;
  github_stars: number | null;
}

function rowToProductDetail(row: RawProductRow): ProductDetail {
  const social = row.social_json ? safeParse(row.social_json, {}) : {};
  const investors = row.funding_investors_json
    ? safeParse(row.funding_investors_json, [])
    : [];

  const hasPricing = row.pricing_model || row.has_free_tier;

  return {
    slug: row.slug,
    name: row.name,
    name_zh: row.name_zh ?? undefined,
    description: row.description ?? "",
    description_zh: row.description_zh ?? undefined,
    product_url: row.product_url ?? "",
    icon_url: row.icon_url ?? undefined,
    product_type: row.product_type ?? "other",
    category: row.category ?? "",
    sub_category: row.sub_category ?? undefined,
    tags: row.tags_json ? safeParse(row.tags_json, []) : undefined,
    keywords: row.keywords_json ? safeParse(row.keywords_json, []) : undefined,
    open_source: row.open_source != null ? Boolean(row.open_source) : undefined,
    status: row.status ?? "active",
    repository_url: row.repository_url ?? undefined,
    license: row.license ?? undefined,
    company: {
      name: row.company_name ?? row.name,
      name_zh: row.company_name_zh ?? undefined,
      url: row.company_url ?? "",
      website: row.company_website ?? undefined,
      founded_year: row.company_founded_year ?? undefined,
      headquarters:
        row.company_hq_city || row.company_hq_country
          ? {
              city: row.company_hq_city ?? "",
              country: row.company_hq_country ?? "",
              country_zh: row.company_hq_country_zh ?? undefined,
              country_code: row.company_hq_country_code ?? undefined,
            }
          : undefined,
      funding:
        row.funding_total_raised_usd || row.funding_last_round
          ? {
              total_raised_usd: row.funding_total_raised_usd ?? undefined,
              last_round: row.funding_last_round ?? undefined,
              last_round_date: row.funding_last_round_date ?? undefined,
              valuation_usd: row.funding_valuation_usd ?? undefined,
              investors: investors.length > 0 ? investors : undefined,
            }
          : undefined,
      employee_count_range: row.company_employee_count_range ?? undefined,
      social: Object.keys(social).length > 0 ? social : undefined,
    },
    key_people: row.key_people_json
      ? safeParse(row.key_people_json, [])
      : undefined,
    sources: row.sources_json ? safeParse(row.sources_json, []) : undefined,
    meta: {
      added_date: row.added_date ?? undefined,
      last_updated: row.last_updated ?? undefined,
      data_quality_score: row.data_quality_score ?? undefined,
    },
    // Rich fields
    pricing: hasPricing
      ? {
          model: row.pricing_model ?? undefined,
          has_free_tier: row.has_free_tier != null ? Boolean(row.has_free_tier) : undefined,
        }
      : undefined,
    modalities: row.modalities_json ? safeParse(row.modalities_json, []) : undefined,
    platforms: row.platforms_json ? safeParse(row.platforms_json, []) : undefined,
    target_audience: row.target_audience_json ? safeParse(row.target_audience_json, []) : undefined,
    target_audience_zh: row.target_audience_zh_json ? safeParse(row.target_audience_zh_json, []) : undefined,
    use_cases: row.use_cases_json ? safeParse(row.use_cases_json, []) : undefined,
    use_cases_zh: row.use_cases_zh_json ? safeParse(row.use_cases_zh_json, []) : undefined,
    competitors: row.competitors_json ? safeParse(row.competitors_json, []) : undefined,
    based_on: row.based_on_json ? safeParse(row.based_on_json, []) : undefined,
    used_by: row.used_by_json ? safeParse(row.used_by_json, []) : undefined,
    hiring: row.hiring_json ? safeParse(row.hiring_json, {}) : undefined,
    app_store: row.app_store_json ? safeParse(row.app_store_json, {}) : undefined,
    platform_availability: row.platform_availability_json ? safeParse(row.platform_availability_json, {}) : undefined,
    ai_native: row.ai_native_json ? safeParse(row.ai_native_json, {}) : undefined,
    api_available: row.api_available != null ? Boolean(row.api_available) : undefined,
    api_docs_url: row.api_docs_url ?? undefined,
    architecture: row.architecture ?? undefined,
    parameter_count: row.parameter_count ?? undefined,
    context_window: row.context_window ?? undefined,
    supported_languages: row.supported_languages_json
      ? safeParse(row.supported_languages_json, [])
      : undefined,
    supported_languages_zh: row.supported_languages_zh_json
      ? safeParse(row.supported_languages_zh_json, [])
      : undefined,
    release_date: row.release_date ?? undefined,
    github_stars: row.github_stars ?? undefined,
  };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// Cache to avoid rebuilding the product list multiple times during SSG
let _allProductsCache: ProductIndex | null = null;

export function getAllProducts(): ProductIndex {
  if (_allProductsCache) return _allProductsCache;

  const db = getDb();
  let result: ProductIndex;
  if (db) {
    const rows = db
      .prepare(
        `SELECT slug, name, name_zh,
                SUBSTR(description, 1, 160) AS description,
                SUBSTR(description_zh, 1, 160) AS description_zh,
                icon_url, category, tags_json,
                open_source, status, company_name,
                company_hq_country AS country,
                company_hq_country_code AS country_code,
                COALESCE(funding_total_raised_usd, 0) AS total_raised_usd,
                funding_last_round AS last_round,
                pricing_model, has_free_tier,
                modalities_json, platforms_json, api_available
         FROM products
         ORDER BY funding_total_raised_usd DESC, name ASC`
      )
      .all() as RawIndexRow[];
    const products = rows.map(rowToIndexEntry);
    result = { total: products.length, products };
  } else {
    // Fallback: read from index.json
    const indexPath = path.join(DATA_DIR, "index.json");
    const raw = fs.readFileSync(indexPath, "utf-8");
    result = JSON.parse(raw) as ProductIndex;
  }

  _allProductsCache = result;
  return result;
}

export function getProductBySlug(slug: string): ProductDetail {
  if (!/^[a-z0-9-]+$/.test(slug)) {
    throw new Error(`Invalid slug: ${slug}`);
  }

  const db = getDb();
  if (db) {
    const row = db
      .prepare("SELECT * FROM products WHERE slug = ?")
      .get(slug) as RawProductRow | undefined;
    if (!row) {
      throw new Error(`Product not found: ${slug}`);
    }
    return rowToProductDetail(row);
  }

  // Fallback: read individual JSON file
  const filePath = path.join(PRODUCTS_DIR, `${slug}.json`);
  const raw = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(raw) as ProductDetail;
}

export function getStats(): Stats {
  const statsPath = path.join(DATA_DIR, "stats.json");
  const raw = fs.readFileSync(statsPath, "utf-8");
  return JSON.parse(raw) as Stats;
}

export function getAllSlugs(): string[] {
  const db = getDb();
  if (db) {
    const rows = db
      .prepare("SELECT slug FROM products ORDER BY slug")
      .all() as { slug: string }[];
    return rows.map((r) => r.slug);
  }

  // Fallback: read from filesystem
  const files = fs.readdirSync(PRODUCTS_DIR);
  return files
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(".json", ""));
}

export function getCategories(): Category[] {
  const catPath = path.join(DATA_DIR, "categories.json");
  const raw = fs.readFileSync(catPath, "utf-8");
  const data = JSON.parse(raw);
  return data.categories as Category[];
}

/** Pre-compute category counts server-side to avoid O(n*m) in client. */
export function getCategoryCounts(): Record<string, number> {
  const db = getDb();
  if (db) {
    const rows = db
      .prepare("SELECT category, COUNT(*) AS cnt FROM products GROUP BY category")
      .all() as { category: string; cnt: number }[];
    const counts: Record<string, number> = {};
    for (const row of rows) {
      if (row.category) counts[row.category] = row.cnt;
    }
    return counts;
  }
  // Fallback: compute from index
  const { products } = getAllProducts();
  const counts: Record<string, number> = {};
  for (const p of products) {
    counts[p.category] = (counts[p.category] || 0) + 1;
  }
  return counts;
}

/** Distinct country names, sorted alphabetically. */
export function getCountries(): string[] {
  const db = getDb();
  if (db) {
    const rows = db
      .prepare(
        "SELECT DISTINCT company_hq_country FROM products WHERE company_hq_country IS NOT NULL AND company_hq_country != '' ORDER BY company_hq_country",
      )
      .all() as { company_hq_country: string }[];
    return rows.map((r) => r.company_hq_country);
  }
  // Fallback: compute from index
  const { products } = getAllProducts();
  return Array.from(new Set(products.map((p) => p.country).filter(Boolean))).sort();
}

export function getTags(): TagsData {
  const tagsPath = path.join(DATA_DIR, "tags.json");
  const raw = fs.readFileSync(tagsPath, "utf-8");
  return JSON.parse(raw) as TagsData;
}
