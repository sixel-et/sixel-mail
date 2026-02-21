-- Create red team target agent for penetration testing.
-- The attacker's goal is to land a message in this inbox.
-- Idempotent — safe to re-run.

-- Reuse test user (github_id=0)
INSERT INTO users (github_id, github_username, email)
VALUES (0, 'test-loopback', 'test-loopback@test.local')
ON CONFLICT (github_id) DO NOTHING;

-- redteam-target: nonce enabled, allowed contact is a non-existent address
-- (the attacker should NOT have a legitimate path to send email)
INSERT INTO agents (user_id, address, allowed_contact, credit_balance, nonce_enabled, channel_active)
SELECT u.id, 'redteam-target', 'nobody-real@example.com', 10000, TRUE, TRUE
FROM users u WHERE u.github_id = 0
ON CONFLICT (address) DO UPDATE
    SET allowed_contact = 'nobody-real@example.com',
        credit_balance = 10000,
        nonce_enabled = TRUE,
        channel_active = TRUE;
