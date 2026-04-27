-- Bootstrap additional databases on first postgres start.
-- The default `bot` database (POSTGRES_DB) is created automatically; here we
-- add the langfuse database so the langfuse container can share the same
-- postgres instance without crossing schemas.

CREATE DATABASE langfuse;
GRANT ALL PRIVILEGES ON DATABASE langfuse TO bot;
