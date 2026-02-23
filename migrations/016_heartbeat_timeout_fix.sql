-- Fix heartbeat timeout vs throttle mismatch.
-- HEARTBEAT_INTERVAL is 600s (write every 10 min), but heartbeat_timeout
-- defaulted to 300s (5 min). Agents looked dead during the gap between
-- writes, causing a ping-pong of down/recovery emails that burned through
-- Resend's 100/day free tier limit overnight.
-- New default: 900s (15 min) — well above the 10-min write interval.
ALTER TABLE agents ALTER COLUMN heartbeat_timeout SET DEFAULT 900;
UPDATE agents SET heartbeat_timeout = 900 WHERE heartbeat_timeout = 300;
