/** Strongly-typed dictionary shape matching en.json / zh.json. */

export interface ProductDict {
  product_type: string;
  tags_by_dimension: string;
  company_name: string;
  founded: string;
  headquarters: string;
  employees: string;
  funding: string;
  total_raised: string;
  last_round: string;
  last_round_date: string;
  valuation: string;
  investors: string;
  key_people: string;
  founder: string;
  social: string;
  open_source: string;
  tags: string;
  overview: string;
  visit: string;
  visit_product: string;
  visit_company: string;
  status: string;
  data_sources: string;
  back_to_list: string;
  city: string;
  country: string;
  category: string;
  yes: string;
  no: string;
  // Rich detail fields
  pricing: string;
  pricing_model: string;
  free_tier: string;
  technical: string;
  modalities: string;
  platforms: string;
  api_available: string;
  api_docs: string;
  architecture: string;
  parameters: string;
  context_window: string;
  supported_languages: string;
  release_date: string;
  license: string;
  repository: string;
  github_stars: string;
  use_cases: string;
  target_audience: string;
  competitors: string;
  based_on: string;
  used_by: string;
  hiring: string;
  is_hiring: string;
  careers: string;
  tech_stack: string;
  open_positions: string;
  sub_category: string;
  app_store: string;
  rating: string;
  free: string;
  freemium: string;
  paid: string;
  enterprise: string;
  open_source_model: string;
  usage_based: string;
  free_trial: string;
  last_updated: string;
  added_date: string;
}

export interface SearchDict {
  title: string;
  placeholder: string;
  results: string;
  no_results: string;
  filters: string;
  filter_tags: string;
  category: string;
  country: string;
  clear_filters: string;
}

export interface HomeDict {
  hero_title: string;
  hero_subtitle: string;
  filter_all: string;
  sort_by: string;
  sort_funding: string;
  sort_name: string;
  no_results: string;
}

export interface Dictionary {
  site: { title: string; description: string };
  nav: { home: string; search: string; compare: string; analytics: string; github: string };
  home: HomeDict;
  product: ProductDict;
  search: SearchDict;
  compare: { title: string; select_prompt: string; add_product: string; remove: string; field: string; no_data: string };
  analytics: { title: string; total_products: string; total_funding: string; open_source: string; funding_chart: string; category_chart: string; tag_chart: string; timeline_chart: string; geography_chart: string };
  footer: { description: string; contribute: string; data_updated: string };
}
