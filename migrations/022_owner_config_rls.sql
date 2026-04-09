-- Migration 022: Enable RLS on owner_config (missed in 021)
--
-- Backend uses service_role connection which bypasses RLS;
-- this blocks any PostgREST/anon access (defense in depth).
-- Same pattern as migration 003 and 014.
ALTER TABLE owner_config ENABLE ROW LEVEL SECURITY;
