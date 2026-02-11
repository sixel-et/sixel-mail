-- Migration 003: Enable Row Level Security on all tables
--
-- Supabase exposes public schema tables via PostgREST. Without RLS,
-- anyone with the anon key can read/write all data directly.
--
-- We access the DB exclusively through our backend (using the service_role
-- connection string, which bypasses RLS). So we enable RLS with no
-- permissive policies — effectively blocking all PostgREST access.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE _migrations ENABLE ROW LEVEL SECURITY;
