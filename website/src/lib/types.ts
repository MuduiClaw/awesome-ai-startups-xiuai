export interface Headquarters {
  city: string;
  state?: string;
  country: string;
  country_code?: string;
}

export interface Funding {
  total_raised_usd?: number;
  last_round?: string;
  last_round_date?: string;
  valuation_usd?: number;
  investors?: string[];
}

export interface Social {
  github?: string;
  twitter?: string;
  linkedin?: string;
  crunchbase?: string;
}

export interface Hiring {
  is_hiring?: boolean;
  careers_url?: string;
  tech_stack?: string[];
  total_positions?: number;
  positions?: { title: string; location?: string; url?: string }[];
  last_checked?: string;
}

export interface AppStore {
  apple_store_url?: string;
  google_play_url?: string;
  rating?: number;
  downloads?: string;
  last_updated?: string;
}

export interface Pricing {
  model?: string;
  has_free_tier?: boolean;
  url?: string;
  input_price_per_1m_tokens?: number;
  output_price_per_1m_tokens?: number;
}

export interface CompanyInfo {
  name: string;
  name_zh?: string;
  url: string;
  website?: string;
  founded_year?: number;
  headquarters?: Headquarters;
  funding?: Funding;
  employee_count_range?: string;
  social?: Social;
}

export interface KeyPerson {
  name: string;
  title?: string;
  is_founder?: boolean;
  profile_url?: string;
}

export interface Source {
  url: string;
  source_name: string;
  scraped_at?: string;
}

export interface ProductMeta {
  added_date?: string;
  last_updated?: string;
  data_quality_score?: number;
  needs_review?: boolean;
}

/** Full product detail — loaded from individual product JSON files. */
export interface ProductDetail {
  slug: string;
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  product_url: string;
  icon_url?: string;
  product_type: string;
  category: string;
  sub_category?: string;
  tags?: string[];
  keywords?: string[];
  open_source?: boolean;
  status: string;
  repository_url?: string;
  license?: string;
  company: CompanyInfo;
  key_people?: KeyPerson[];
  sources?: Source[];
  meta?: ProductMeta;
  // Rich fields
  pricing?: Pricing;
  modalities?: string[];
  platforms?: string[];
  target_audience?: string[];
  use_cases?: string[];
  competitors?: string[];
  based_on?: string[];
  used_by?: string[];
  hiring?: Hiring;
  app_store?: AppStore;
  api_available?: boolean;
  api_docs_url?: string;
  architecture?: string;
  parameter_count?: string;
  context_window?: number;
  supported_languages?: string[];
  release_date?: string;
  github_stars?: number;
}

/** Flattened product entry from index.json — used for list/card views.
 *  Optimized for minimal payload: only fields displayed on cards.
 *  Descriptions truncated to 160 chars, tags limited to 3. */
export interface ProductIndexEntry {
  slug: string;
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  product_url: string;
  icon_url?: string;
  product_type: string;
  category: string;
  tags?: string[];
  open_source?: boolean;
  status: string;
  company_name: string;
  company_url: string;
  country: string;
  country_code: string;
  city: string;
  total_raised_usd: number;
  last_round: string;
  valuation_usd: number;
  employee_count_range: string;
  // Rich card fields
  pricing_model?: string;
  has_free_tier?: boolean;
  modalities?: string[];
  platforms?: string[];
  api_available?: boolean;
}

export interface ProductIndex {
  total: number;
  products: ProductIndexEntry[];
}

export interface StatEntry {
  label: string;
  count: number;
}

export interface FundingLeaderEntry {
  slug: string;
  name: string;
  total_raised_usd: number;
  valuation_usd: number;
}

export interface TagDimensionStat {
  tag: string;
  count: number;
}

export interface Stats {
  generated_at: string;
  total_products: number;
  by_category: StatEntry[];
  by_country: StatEntry[];
  by_status: StatEntry[];
  by_tag_dimension: Record<string, TagDimensionStat[]>;
  funding_leaderboard: FundingLeaderEntry[];
  total_funding_usd: number;
  open_source_count: number;
  recently_added: { slug: string; name: string; added_date: string }[];
}

export interface Category {
  id: string;
  name: string;
  name_zh: string;
  icon: string;
}

export interface Tag {
  id: string;
  name: string;
  name_zh: string;
}

export interface TagDimension {
  name: string;
  name_zh: string;
  tags: Tag[];
}

export interface TagsData {
  version: string;
  dimensions: Record<string, TagDimension>;
}

export type Locale = "en" | "zh";
