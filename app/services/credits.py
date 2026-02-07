import asyncpg


async def deduct_credit(pool: asyncpg.Pool, agent_id: str, reason: str) -> int | None:
    """Atomically deduct 1 credit. Returns new balance, or None if insufficient."""
    row = await pool.fetchrow(
        """
        UPDATE agents
        SET credit_balance = credit_balance - 1
        WHERE id = $1 AND credit_balance >= 1
        RETURNING credit_balance
        """,
        agent_id,
    )
    if row is None:
        return None

    await pool.execute(
        """
        INSERT INTO credit_transactions (agent_id, amount, reason)
        VALUES ($1, -1, $2)
        """,
        agent_id,
        reason,
    )
    return row["credit_balance"]


async def add_credits(
    pool: asyncpg.Pool,
    agent_id: str,
    amount: int,
    reason: str,
    stripe_session_id: str | None = None,
) -> int:
    """Add credits to an agent. Returns new balance."""
    row = await pool.fetchrow(
        """
        UPDATE agents
        SET credit_balance = credit_balance + $2
        WHERE id = $1
        RETURNING credit_balance
        """,
        agent_id,
        amount,
    )

    await pool.execute(
        """
        INSERT INTO credit_transactions (agent_id, amount, reason, stripe_session_id)
        VALUES ($1, $2, $3, $4)
        """,
        agent_id,
        amount,
        reason,
        stripe_session_id,
    )
    return row["credit_balance"]
