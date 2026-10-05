-- MySQL 8.0+. Run in MySQL Workbench, or from the mysql client:
--   SOURCE C:/Users/noahd/OneDrive/Desktop/Case_Scraper/sql/create_database.sql;
-- Creates missing objects without deleting existing data.
-- IF NOT EXISTS does not migrate tables created with an older schema.

CREATE DATABASE IF NOT EXISTS case_scraper
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE case_scraper;
SET NAMES utf8mb4;

-- One row per case. Field mappings refer to the dataclass in case.py.
-- Store identifiers as text to preserve leading zeroes and punctuation.
-- Convert a missing/empty case.ID to SQL NULL before inserting.
CREATE TABLE IF NOT EXISTS cases (
    case_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_case_id VARCHAR(255) COLLATE utf8mb4_bin NULL COMMENT 'case.ID',
    case_type VARCHAR(255) NULL COMMENT 'case.type (display name, not filter ID)',
    case_number VARCHAR(100) NOT NULL COMMENT 'case.number',
    case_name TEXT NULL COMMENT 'case.name',
    case_interest TEXT NULL COMMENT 'case.interest',
    court VARCHAR(255) NOT NULL COMMENT 'case.court',
    case_status VARCHAR(255) NULL COMMENT 'case.status from search results',
    search_date DATE NULL COMMENT 'Opening date searched; parse DD/MM/YYYY before insert',
    general_details_href TEXT NULL COMMENT 'details.tabs.general_details.href',
    general_details_extracted_at DATETIME(6) NULL COMMENT 'UTC; NULL until general details are collected',
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (case_id),
    UNIQUE KEY uq_cases_source_id (source_case_id),
    UNIQUE KEY uq_cases_number_court (case_number, court),
    KEY ix_cases_search_date (search_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- General details can contain multiple records per case. Preserve their order.
-- Maps details.tabs.general_details.body.records[*] from case_details.py.
-- filing_id is not a primary key: the source can return 0 or NULL.
-- Python None maps to SQL NULL; keep numeric zero as zero.
CREATE TABLE IF NOT EXISTS case_general_details (
    case_id BIGINT UNSIGNED NOT NULL,
    record_index INT UNSIGNED NOT NULL COMMENT 'Zero-based position in records',
    case_title TEXT NULL,
    filing_description TEXT NULL,
    access_status VARCHAR(255) NULL,
    claim_amount DECIMAL(20, 2) NULL,
    case_status VARCHAR(255) NULL COMMENT 'Status from the general details record',
    filing_id BIGINT NULL,
    source_fields JSON NULL COMMENT 'Complete original record, including additional source fields',
    PRIMARY KEY (case_id, record_index),
    CONSTRAINT fk_general_details_case FOREIGN KEY (case_id)
        REFERENCES cases (case_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Links are returned separately by the extractor; do not assume that a link
-- index identifies a general-details record.
-- Maps details.tabs.general_details.body.details_links[*].
CREATE TABLE IF NOT EXISTS case_general_details_links (
    case_id BIGINT UNSIGNED NOT NULL,
    link_index INT UNSIGNED NOT NULL COMMENT 'Zero-based position in details_links',
    href TEXT NULL,
    label TEXT NULL,
    PRIMARY KEY (case_id, link_index),
    CONSTRAINT fk_general_details_links_case FOREIGN KEY (case_id)
        REFERENCES cases (case_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Writer integration:
-- 1. Find/update a case by source_case_id, falling back to (case_number, court).
--    Resolve both keys to the same row before attaching a newly discovered ID.
-- 2. Search-only runs populate cases and leave the child tables untouched.
-- 3. After successful general-details extraction, replace that case's records
--    and links in a single transaction and set general_details_extracted_at.
--    A successfully extracted empty list replaces old rows with no rows;
--    a failed/skipped extraction must not erase previously collected details.
-- 4. Bind values as parameters, use an utf8mb4 connection, and set session
--    time_zone = '+00:00'. Serialize source_fields for the JSON column only.
-- This file configures storage; Python database writes are not yet connected.
