-- Add heartbeat_checked_at column to agents.
-- This replaces the in-memory _previous_seen dict with a DB-backed
-- single source of truth. The checker updates this every cycle.
-- The AND-logic becomes: last_seen_at is stale AND last_seen_at <= heartbeat_checked_at
-- (meaning last_seen_at hasn't changed since the last check).
--
-- This survives Fly machine swaps, process restarts, and multi-machine deployments.

ALTER TABLE agents ADD COLUMN IF NOT EXISTS heartbeat_checked_at timestamptz;
