-- Migration 005: Wipe the sixel agent and associated user for fresh start
-- Requested by Eric 2026-02-12

-- Delete in FK order: children first, then parents
DELETE FROM credit_transactions WHERE agent_id IN (SELECT id FROM agents WHERE address = 'sixel');
DELETE FROM messages WHERE agent_id IN (SELECT id FROM agents WHERE address = 'sixel');
DELETE FROM api_keys WHERE agent_id IN (SELECT id FROM agents WHERE address = 'sixel');

-- Capture user_id before deleting agent
DELETE FROM agents WHERE address = 'sixel';

-- Delete the user (Eric's account) — only if they have no remaining agents
DELETE FROM users WHERE id NOT IN (SELECT DISTINCT user_id FROM agents);
