-- Clear stale agent_down_notified flags and refresh last_seen_at.
-- The heartbeat ping-pong left agents in a notified state. Each deploy
-- triggered recovery emails because the flag was still set.
UPDATE agents SET agent_down_notified = FALSE, last_seen_at = now()
WHERE agent_down_notified = TRUE;
