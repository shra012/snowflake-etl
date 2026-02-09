-- Task 5: Query optimization variants + rationales

-- Scenario 1: Documents modified within 7-day rolling window
-- COST-EFFICIENT APPROACH
-- Rationale: Simple filter on LASTMOD scans only a narrow time window and avoids joins, materialized views or additional indexing costs. Uses set-oriented operations so it remains cheap when LASTMOD is selective.
SELECT
  DOCUMENT_URL,
  LASTMOD
FROM IDENTIFIER('{DOCS_MASTER}')
WHERE LASTMOD >= DATEADD('day', -7, CURRENT_DATE())
ORDER BY LASTMOD DESC, DOCUMENT_URL;

-- TIME-EFFICIENT APPROACH
-- Rationale: Maintain a materialized view that precomputes recent modifications. Querying the materialized view is fast (low latency) at the cost of MV maintenance overhead on insert/update.
-- CREATE MATERIALIZED VIEW mv_recent_docs AS
--   SELECT DOCUMENT_URL, LASTMOD FROM IDENTIFIER('{DOCS_MASTER}') WHERE LASTMOD >= DATEADD('day', -7, CURRENT_DATE());

SELECT DOCUMENT_URL, LASTMOD
FROM mv_recent_docs
ORDER BY LASTMOD DESC, DOCUMENT_URL;


-- Scenario 2: Unique URL count per source with mean content length
-- COST-EFFICIENT APPROACH
-- Rationale: Use approximate aggregation functions to reduce compute and memory footprint for very large sets. APPROX_COUNT_DISTINCT and AVG on aggregated partitions reduce shuffle and sort costs.
WITH expanded AS (
  SELECT
    dm.DOCUMENT_URL,
    f.VALUE::STRING AS SOURCE_IDENTIFIER
  FROM IDENTIFIER('{DOCS_MASTER}') dm,
       LATERAL FLATTEN(input => dm.SOURCES) f
)
SELECT
  SOURCE_IDENTIFIER,
  APPROX_COUNT_DISTINCT(DOCUMENT_URL) AS APPROX_UNIQUE_URLS,
  AVG(COALESCE(dc.CONTENT_LENGTH_BYTES, 0)) AS MEAN_CONTENT_LENGTH_BYTES
FROM expanded e
LEFT JOIN IDENTIFIER('{DOCUMENT_CONTENT}') dc
  ON dc.DOCUMENT_URL = e.DOCUMENT_URL
GROUP BY SOURCE_IDENTIFIER
ORDER BY APPROX_UNIQUE_URLS DESC, SOURCE_IDENTIFIER;

-- TIME-EFFICIENT APPROACH
-- Rationale: Exact aggregates with full GROUP BY exploit Snowflake's parallelism and produce precise results quickly when cluster keys and compute resources are available.
WITH expanded AS (
  SELECT
    dm.DOCUMENT_URL,
    f.VALUE::STRING AS SOURCE_IDENTIFIER
  FROM IDENTIFIER('{DOCS_MASTER}') dm,
       LATERAL FLATTEN(input => dm.SOURCES) f
)
SELECT
  SOURCE_IDENTIFIER,
  COUNT(DISTINCT DOCUMENT_URL) AS UNIQUE_URLS,
  AVG(COALESCE(dc.CONTENT_LENGTH_BYTES, 0)) AS MEAN_CONTENT_LENGTH_BYTES
FROM expanded e
LEFT JOIN IDENTIFIER('{DOCUMENT_CONTENT}') dc
  ON dc.DOCUMENT_URL = e.DOCUMENT_URL
GROUP BY SOURCE_IDENTIFIER
ORDER BY UNIQUE_URLS DESC, SOURCE_IDENTIFIER;


-- Scenario 3: Content deduplication detection (identical hashes, distinct URLs)
-- COST-EFFICIENT APPROACH
-- Rationale: GROUP BY CONTENT_HASH to identify duplicated content. Minimal state and no heavy self-joins; good when number of distinct hashes << number of rows.
SELECT
  CONTENT_HASH,
  COUNT(*) AS URL_COUNT,
  MIN(DOCUMENT_URL) AS SAMPLE_URL
FROM IDENTIFIER('{DOCUMENT_CONTENT}')
WHERE CONTENT_HASH IS NOT NULL
GROUP BY CONTENT_HASH
HAVING COUNT(*) > 1
ORDER BY URL_COUNT DESC, CONTENT_HASH;

-- TIME-EFFICIENT APPROACH
-- Rationale: Use a window function to compute partition counts and then select all rows for duplicated hashes. This avoids an extra aggregation join and returns full URL lists with lower latency.
SELECT
  DOCUMENT_URL,
  CONTENT_HASH
FROM (
  SELECT
    DOCUMENT_URL,
    CONTENT_HASH,
    COUNT(*) OVER (PARTITION BY CONTENT_HASH) AS HASH_COUNT
  FROM IDENTIFIER('{DOCUMENT_CONTENT}')
  WHERE CONTENT_HASH IS NOT NULL
) t
WHERE HASH_COUNT > 1
ORDER BY CONTENT_HASH, DOCUMENT_URL;
