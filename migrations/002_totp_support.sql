-- Migration 002: Add TOTP support for Cloudflare Email Worker encryption
--
-- has_totp: indicates this agent has TOTP encryption enabled.
-- The TOTP shared secret itself is NEVER stored on our server —
-- it exists only in the human's authenticator app and the agent's local config.
--
-- encrypted: per-message flag indicating whether the body is ciphertext.
-- Allows the dashboard and API to handle both plaintext and encrypted messages.

ALTER TABLE agents ADD COLUMN IF NOT EXISTS has_totp BOOLEAN DEFAULT FALSE;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS encrypted BOOLEAN DEFAULT FALSE;
