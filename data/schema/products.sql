-- SQLite schema for products database.
-- Hybrid approach: commonly queried fields as real columns,
-- nested/array structures as JSON columns.

CREATE TABLE IF NOT EXISTS products (
    -- Identity
    slug              TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    name_zh           TEXT,
    product_url       TEXT,
    icon_url          TEXT,
    description       TEXT,
    description_zh    TEXT,
    product_type      TEXT,
    category          TEXT,
    sub_category      TEXT,
    status            TEXT DEFAULT 'active',

    -- Company (flattened from company.*)
    company_name      TEXT,
    company_name_zh   TEXT,
    company_url       TEXT,
    company_website   TEXT,
    company_wikipedia_url TEXT,
    company_logo_url  TEXT,
    company_description TEXT,
    company_founded_year INTEGER,
    company_hq_city   TEXT,
    company_hq_country TEXT,
    company_hq_country_code TEXT,
    company_employee_count_range TEXT,

    -- Funding (flattened from company.funding.*)
    funding_total_raised_usd REAL DEFAULT 0,
    funding_last_round TEXT,
    funding_last_round_date TEXT,
    funding_valuation_usd REAL DEFAULT 0,

    -- Tech specs
    open_source       INTEGER,  -- boolean 0/1
    license           TEXT,
    repository_url    TEXT,
    github_stars      INTEGER,
    github_contributors INTEGER,
    architecture      TEXT,
    parameter_count   TEXT,
    context_window    INTEGER,
    api_available     INTEGER,  -- boolean 0/1
    api_docs_url      TEXT,

    -- Pricing (flattened)
    pricing_model     TEXT,
    has_free_tier     INTEGER,  -- boolean 0/1

    -- Dates
    release_date      TEXT,
    added_date        TEXT,
    last_updated      TEXT,
    data_quality_score REAL,
    needs_review      INTEGER DEFAULT 0,  -- boolean 0/1

    -- JSON columns (arrays and nested objects)
    tags_json         TEXT DEFAULT '[]',
    keywords_json     TEXT DEFAULT '[]',
    key_people_json   TEXT DEFAULT '[]',
    modalities_json   TEXT DEFAULT '[]',
    supported_languages_json TEXT DEFAULT '[]',
    platforms_json    TEXT DEFAULT '[]',
    target_audience_json TEXT DEFAULT '[]',
    use_cases_json    TEXT DEFAULT '[]',
    competitors_json  TEXT DEFAULT '[]',
    based_on_json     TEXT DEFAULT '[]',
    used_by_json      TEXT DEFAULT '[]',
    sources_json      TEXT DEFAULT '[]',
    provenance_json   TEXT DEFAULT '{}',
    hiring_json       TEXT DEFAULT '{}',
    social_json       TEXT DEFAULT '{}',
    app_store_json    TEXT DEFAULT '{}',
    funding_investors_json TEXT DEFAULT '[]'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_country ON products(company_hq_country);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_funding ON products(funding_total_raised_usd DESC);
CREATE INDEX IF NOT EXISTS idx_products_added ON products(added_date DESC);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_company ON products(company_name);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
    name,
    name_zh,
    description,
    description_zh,
    category,
    tags,
    keywords,
    company_name,
    content='products',
    content_rowid='rowid'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
    INSERT INTO products_fts(rowid, name, name_zh, description, description_zh,
                             category, tags, keywords, company_name)
    VALUES (new.rowid, new.name, new.name_zh, new.description, new.description_zh,
            new.category,
            COALESCE(new.tags_json, '[]'),
            COALESCE(new.keywords_json, '[]'),
            new.company_name);
END;

CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, name, name_zh, description,
                             description_zh, category, tags, keywords, company_name)
    VALUES ('delete', old.rowid, old.name, old.name_zh, old.description,
            old.description_zh, old.category,
            COALESCE(old.tags_json, '[]'),
            COALESCE(old.keywords_json, '[]'),
            old.company_name);
END;

CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, name, name_zh, description,
                             description_zh, category, tags, keywords, company_name)
    VALUES ('delete', old.rowid, old.name, old.name_zh, old.description,
            old.description_zh, old.category,
            COALESCE(old.tags_json, '[]'),
            COALESCE(old.keywords_json, '[]'),
            old.company_name);
    INSERT INTO products_fts(rowid, name, name_zh, description, description_zh,
                             category, tags, keywords, company_name)
    VALUES (new.rowid, new.name, new.name_zh, new.description, new.description_zh,
            new.category,
            COALESCE(new.tags_json, '[]'),
            COALESCE(new.keywords_json, '[]'),
            new.company_name);
END;
