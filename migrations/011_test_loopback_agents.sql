-- Create loopback test agents for E2E testing.
-- test-a and test-b email each other to exercise the full pipeline.
-- Idempotent — safe to re-run.

-- Test user (github_id=0 reserved for test)
INSERT INTO users (github_id, github_username, email)
VALUES (0, 'test-loopback', 'test-loopback@test.local')
ON CONFLICT (github_id) DO NOTHING;

-- test-a: nonce disabled, allowed contact is test-b
INSERT INTO agents (user_id, address, allowed_contact, credit_balance, nonce_enabled, channel_active)
SELECT u.id, 'test-a', 'test-b@sixel.email', 10000, FALSE, TRUE
FROM users u WHERE u.github_id = 0
ON CONFLICT (address) DO UPDATE
    SET allowed_contact = 'test-b@sixel.email',
        credit_balance = 10000,
        nonce_enabled = FALSE,
        channel_active = TRUE;

-- test-b: nonce enabled, allowed contact is test-a
INSERT INTO agents (user_id, address, allowed_contact, credit_balance, nonce_enabled, channel_active)
SELECT u.id, 'test-b', 'test-a@sixel.email', 10000, TRUE, TRUE
FROM users u WHERE u.github_id = 0
ON CONFLICT (address) DO UPDATE
    SET allowed_contact = 'test-a@sixel.email',
        credit_balance = 10000,
        nonce_enabled = TRUE,
        channel_active = TRUE;

-- API key for test-a
DELETE FROM api_keys WHERE agent_id = (SELECT id FROM agents WHERE address = 'test-a');
INSERT INTO api_keys (agent_id, key_hash, key_prefix)
SELECT id, '15a6fce7322c869aa8d3b35acae1e1e713d4f1f30d1f62f744cac577325a8e1b', 'sm_live_KODiDPif'
FROM agents WHERE address = 'test-a';

-- API key for test-b
DELETE FROM api_keys WHERE agent_id = (SELECT id FROM agents WHERE address = 'test-b');
INSERT INTO api_keys (agent_id, key_hash, key_prefix)
SELECT id, 'f333755aa360acd06b8a801e86dcfa456b4879e2216f527547c3fff9f2bc673d', 'sm_live__bz8BRsf'
FROM agents WHERE address = 'test-b';
