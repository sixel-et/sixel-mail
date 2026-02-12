-- Seed credits for sixel agent (Stripe not yet configured)
UPDATE agents SET credit_balance = 200 WHERE address = 'sixel';
INSERT INTO credit_transactions (agent_id, amount, reason)
SELECT id, 200, 'Manual seed — pre-Stripe'
FROM agents WHERE address = 'sixel';
