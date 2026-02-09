-- Task 5: Query optimization variants + rationales

-- Scenario 1: Documents modified within 1-day rolling window
-- COST-EFFICIENT APPROACH
-- Rationale: Simple filter on LASTMOD scans only a narrow time window and avoids joins, materialized views or additional indexing costs. Using `COALESCE` handling ensures we don't miss docs with NULL LASTMOD if that's the business rule, but for strict cost efficiency on a time-series column, a direct range filter usually allows partition pruning (if clustered by LASTMOD).
SELECT
  DOCUMENT_URL,
  LASTMOD
FROM IDENTIFIER('{DOCS_MASTER}')
WHERE LASTMOD >= DATEADD('day', -1, CURRENT_DATE())
ORDER BY LASTMOD DESC, DOCUMENT_URL;

-- TIME-EFFICIENT APPROACH
-- Rationale: Maintain a materialized view that precomputes recent modifications. Querying the materialized view is significantly faster (lower latency) because it acts as a pre-filtered, pre-sorted cache, avoiding the need to scan the entire base table. The tradeoff is storage cost and background maintenance compute.
-- CREATE MATERIALIZED VIEW mv_recent_docs AS
--   SELECT DOCUMENT_URL, LASTMOD FROM IDENTIFIER('{DOCS_MASTER}') WHERE LASTMOD >= DATEADD('day', -1, CURRENT_DATE());
SELECT DOCUMENT_URL, LASTMOD
FROM mv_recent_docs
ORDER BY LASTMOD DESC, DOCUMENT_URL;


-- Scenario 2: Unique URL count per source with mean content length
-- COMPUTE-EFFICIENT APPROACH
-- Rationale: Use `APPROX_COUNT_DISTINCT` (HyperLogLog) instead of precise `COUNT(DISTINCT)`. This drastically reduces memory usage and shuffling during aggregation, making it much cheaper and faster for large datasets where ~1-2% error rate is acceptable.
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

-- PARALLELISM-OPTIMIZED APPROACH
-- Rationale: Uses exact `COUNT(DISTINCT)`. While more resource-intensive, this query benefits from scaling up the warehouse size. Snowflake splits the distinct counting operation across all available worker nodes. For strict accuracy requirements, throwing more compute (parallelism) at the problem is the optimization strategy.
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
-- JOIN-COMPLEXITY OPTIMIZED APPROACH (Window Functions)
-- Rationale: Uses window functions (`QUALIFY COUNT(*) OVER...`) to identify duplicates in a single pass without a self-join. This avoids the complexity and potential Cartesian explosion of self-joins. The execution plan is simpler: Scan -> Sort/Shuffle -> Filter.
SELECT
  DOCUMENT_URL,
  CONTENT_HASH
FROM IDENTIFIER('{DOCUMENT_CONTENT}')
WHERE CONTENT_HASH IS NOT NULL
QUALIFY COUNT(*) OVER (PARTITION BY CONTENT_HASH) > 1
ORDER BY CONTENT_HASH, DOCUMENT_URL;

-- SPEED OPTIMIZED APPROACH (Pruning join)
-- Rationale: While generally `QUALIFY` is preferred, a self-join can sometimes be faster IF the data is extremely sparse (few duplicates) and clustered by hash, or if we need to compare distinct pairs. By aliasing and filtering `a.DOCUMENT_URL < b.DOCUMENT_URL`, we avoid redundant pairs and prune the search space. *Note: In modern Snowflake, the Window Function approach is almost always superior, but this demonstrates the alternative join-based strategy.*
SELECT
  a.CONTENT_HASH,
  a.DOCUMENT_URL AS URL_1,
  b.DOCUMENT_URL AS URL_2
FROM IDENTIFIER('{DOCUMENT_CONTENT}') a
JOIN IDENTIFIER('{DOCUMENT_CONTENT}') b
  ON a.CONTENT_HASH = b.CONTENT_HASH
  AND a.DOCUMENT_URL < b.DOCUMENT_URL
WHERE a.CONTENT_HASH IS NOT NULL
ORDER BY a.CONTENT_HASH;
