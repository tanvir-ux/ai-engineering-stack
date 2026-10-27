-- Retrieval inside Snowflake, two ways.
USE SCHEMA MERIDIAN.RAW;

-- 1) Exact vector search with the built-in similarity function. The query vector is bound as a JSON array by
--    the client (see src/aistack/data/snowflake_pipeline.py). The row access policy filters
--    chunks before ranking, so forbidden text never reaches the result.
SELECT
  CHUNK_ID,
  TITLE,
  VECTOR_COSINE_SIMILARITY(EMBEDDING, PARSE_JSON(?)::ARRAY::VECTOR(FLOAT, 384)) AS SCORE
FROM MERIDIAN.RAW.CHUNKS
ORDER BY SCORE DESC
LIMIT 5;

-- 2) Managed hybrid search with Cortex Search (keyword + semantic, service-managed embeddings).
CREATE OR REPLACE CORTEX SEARCH SERVICE MERIDIAN_DOCS_SEARCH
  ON TEXT
  ATTRIBUTES CLASSIFICATION, DEPARTMENT, TITLE
  WAREHOUSE = MERIDIAN_WH
  TARGET_LAG = '1 day'
  AS (
    SELECT CHUNK_ID, TITLE, CLASSIFICATION, DEPARTMENT, TEXT
    FROM MERIDIAN.RAW.CHUNKS
  );

SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  'MERIDIAN.RAW.MERIDIAN_DOCS_SEARCH',
  '{"query": "how many vacation days do I get", "columns": ["TITLE", "TEXT"], "limit": 3}'
);
