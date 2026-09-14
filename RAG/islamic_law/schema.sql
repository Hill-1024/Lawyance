-- 伊斯兰法系数据库 schema v3
-- 双层：宗教法源共享层 (sharia_principles) + 国家转化实例层 (islamic_rules)
-- 另含：四语术语表、权威来源白名单、manifest 键值表
-- 模式：SQLite + manifest（与 Lawver RAG 管辖库一致）

PRAGMA foreign_keys = ON;

-- ========== 层1：宗教法源共享层（跨国一份）==========
CREATE TABLE IF NOT EXISTS sharia_principles (
    sharia_principle_id TEXT PRIMARY KEY,
    rule_subject TEXT NOT NULL,
    madhhab TEXT NOT NULL DEFAULT 'Shafi''i',
    sharia_source_type TEXT NOT NULL DEFAULT '',
    religious_anchor TEXT NOT NULL DEFAULT '',
    arabic_text TEXT NOT NULL DEFAULT '',
    transliteration TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    legal_effect TEXT NOT NULL DEFAULT 'religious-guidance',
    parallel_languages TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    country_rule_ids TEXT NOT NULL DEFAULT '[]',
    search_blob TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sharia_principles_source
    ON sharia_principles(sharia_source_type);
CREATE INDEX IF NOT EXISTS idx_sharia_principles_madhhab
    ON sharia_principles(madhhab);

-- ========== 层2：国家转化实例层 ==========
CREATE TABLE IF NOT EXISTS islamic_rules (
    rule_id TEXT PRIMARY KEY,
    source_id TEXT,
    law_name TEXT NOT NULL,
    article_number TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    effective_date TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'en',
    country TEXT NOT NULL,
    country_label TEXT NOT NULL DEFAULT '',

    rule_subject TEXT NOT NULL DEFAULT '',
    national_transformation TEXT NOT NULL DEFAULT '',
    parallel_languages TEXT NOT NULL DEFAULT '',
    output_annotation TEXT NOT NULL DEFAULT '',

    madhhab TEXT NOT NULL DEFAULT '',
    sharia_source_type TEXT NOT NULL DEFAULT '',
    religious_anchor TEXT NOT NULL DEFAULT '',
    fatwa_issuer TEXT NOT NULL DEFAULT '',
    fatwa_id TEXT NOT NULL DEFAULT '',
    supersedes TEXT NOT NULL DEFAULT '',
    legal_effect TEXT NOT NULL DEFAULT '',
    applicability_person TEXT NOT NULL DEFAULT '',
    applicability_subject TEXT NOT NULL DEFAULT '',
    applicability_territory TEXT NOT NULL DEFAULT '',
    arabic_text TEXT NOT NULL DEFAULT '',
    transliteration TEXT NOT NULL DEFAULT '',
    sharia_principle_id TEXT,
    country_rule_ids TEXT NOT NULL DEFAULT '[]',

    law_name_key TEXT NOT NULL DEFAULT '',
    article_key TEXT NOT NULL DEFAULT '',
    search_blob TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (sharia_principle_id) REFERENCES sharia_principles(sharia_principle_id)
);

CREATE INDEX IF NOT EXISTS idx_islamic_rules_country ON islamic_rules(country);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_status ON islamic_rules(status);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_madhhab ON islamic_rules(madhhab);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_legal_effect ON islamic_rules(legal_effect);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_source_type ON islamic_rules(sharia_source_type);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_principle ON islamic_rules(sharia_principle_id);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_law_article ON islamic_rules(law_name_key, article_key);
CREATE INDEX IF NOT EXISTS idx_islamic_rules_fatwa ON islamic_rules(fatwa_issuer, fatwa_id);

-- ========== 四语术语对照表 ==========
CREATE TABLE IF NOT EXISTS terminology (
    term_id TEXT PRIMARY KEY,
    ar TEXT NOT NULL DEFAULT '',
    en TEXT NOT NULL DEFAULT '',
    zh TEXT NOT NULL DEFAULT '',
    ms TEXT NOT NULL DEFAULT '',
    id TEXT NOT NULL DEFAULT '',
    preferred_zh TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_terminology_en ON terminology(en);
CREATE INDEX IF NOT EXISTS idx_terminology_zh ON terminology(zh);

-- ========== 权威来源白名单（表6骨架）==========
CREATE TABLE IF NOT EXISTS authority_sources (
    source_key TEXT PRIMARY KEY,
    country TEXT NOT NULL DEFAULT '',
    layer TEXT NOT NULL DEFAULT 'country',
    organization TEXT NOT NULL,
    channels TEXT NOT NULL DEFAULT '',
    primary_use TEXT NOT NULL DEFAULT '',
    homepage_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);

-- ========== 库内 manifest 键值 ==========
CREATE TABLE IF NOT EXISTS islamic_manifest (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
