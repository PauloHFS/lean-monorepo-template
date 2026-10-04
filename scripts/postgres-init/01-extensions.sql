-- =============================================================================
-- Bootstrap de extensões. Roda na primeira inicialização do cluster
-- (via /docker-entrypoint-initdb.d). Idempotente: CREATE EXTENSION IF NOT EXISTS.
-- =============================================================================

-- Geoespacial
CREATE EXTENSION IF NOT EXISTS postgis;

-- Full-text e busca trigram
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Grafos / hierarquia (queries recursivas e paths)
CREATE EXTENSION IF NOT EXISTS ltree;

-- Índices compostos úteis (ex.: ranges + inet)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Embeddings (RAG / busca semântica)
CREATE EXTENSION IF NOT EXISTS vector;

-- Criptografia/hash dentro do banco (tokens de sessão, por ex.)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- UUIDs nativos (v4/v7)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Cron jobs (limpeza automática de tabelas efêmeras)
CREATE EXTENSION IF NOT EXISTS pg_cron;
