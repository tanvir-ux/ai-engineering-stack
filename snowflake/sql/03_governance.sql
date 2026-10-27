-- The same access rule the application enforces, expressed as a Snowflake row access policy:
-- a role only sees chunks whose classification it has been granted.
USE SCHEMA MERIDIAN.RAW;

CREATE OR REPLACE TABLE ROLE_CLASSIFICATION_MAP (
  ROLE_NAME      STRING,
  CLASSIFICATION STRING
);

-- Kept in sync with src/aistack/auth/policy.py ROLE_CLASSES by tests/test_snowflake.py.
INSERT INTO ROLE_CLASSIFICATION_MAP VALUES
  ('MERIDIAN_ADMIN', 'finance'),
  ('MERIDIAN_ADMIN', 'hr'),
  ('MERIDIAN_ADMIN', 'internal'),
  ('MERIDIAN_ADMIN', 'public'),
  ('MERIDIAN_ADMIN', 'security'),
  ('MERIDIAN_CONTRACTOR', 'public'),
  ('MERIDIAN_EMPLOYEE', 'internal'),
  ('MERIDIAN_EMPLOYEE', 'public'),
  ('MERIDIAN_FINANCE', 'finance'),
  ('MERIDIAN_FINANCE', 'internal'),
  ('MERIDIAN_FINANCE', 'public'),
  ('MERIDIAN_HR', 'hr'),
  ('MERIDIAN_HR', 'internal'),
  ('MERIDIAN_HR', 'public'),
  ('MERIDIAN_SECURITY', 'internal'),
  ('MERIDIAN_SECURITY', 'public'),
  ('MERIDIAN_SECURITY', 'security');

CREATE OR REPLACE ROW ACCESS POLICY CHUNK_ACL AS (CLASSIFICATION STRING) RETURNS BOOLEAN ->
  IS_ROLE_IN_SESSION('ACCOUNTADMIN')
  OR EXISTS (
    SELECT 1
    FROM MERIDIAN.RAW.ROLE_CLASSIFICATION_MAP M
    WHERE M.CLASSIFICATION = CLASSIFICATION
      AND IS_ROLE_IN_SESSION(M.ROLE_NAME)
  );

ALTER TABLE CHUNKS ADD ROW ACCESS POLICY CHUNK_ACL ON (CLASSIFICATION);
