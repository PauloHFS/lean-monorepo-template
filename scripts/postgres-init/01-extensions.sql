-- =============================================================================
-- Bootstrap de extensões. Roda na primeira inicialização do cluster
-- (via /docker-entrypoint-initdb.d). Idempotente e tolerante: cada extensão é
-- criada num bloco próprio. Se a imagem não trouxer os arquivos de controle
-- (ex.: `vector` no postgis/postgis, `pg_cron` sem a extensão), o bloco emite
-- NOTICE e o script segue — sem abortar as extensões seguintes.
-- =============================================================================

-- Geoespacial
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS postgis; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'postgis indisponível nesta imagem: %', SQLERRM; END $$;

-- Full-text e busca trigram
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pg_trgm; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pg_trgm indisponível nesta imagem: %', SQLERRM; END $$;
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS unaccent; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'unaccent indisponível nesta imagem: %', SQLERRM; END $$;

-- Grafos / hierarquia (queries recursivas e paths)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS ltree; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'ltree indisponível nesta imagem: %', SQLERRM; END $$;

-- Índices compostos úteis (ex.: ranges + inet)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS btree_gist; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'btree_gist indisponível nesta imagem: %', SQLERRM; END $$;

-- Embeddings (RAG / busca semântica)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS vector; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'vector indisponível nesta imagem: %', SQLERRM; END $$;

-- Criptografia/hash dentro do banco (tokens de sessão, por ex.)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pgcrypto; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pgcrypto indisponível nesta imagem: %', SQLERRM; END $$;

-- UUIDs nativos (v4/v7)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'uuid-ossp indisponível nesta imagem: %', SQLERRM; END $$;

-- Cron jobs (limpeza automática de tabelas efêmeras; opcional por design)
DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS pg_cron; EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pg_cron indisponível nesta imagem: %', SQLERRM; END $$;
