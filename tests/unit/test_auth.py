"""Unit tests for app/auth.py — API key generation and hashing."""

from app.auth import generate_api_key, hash_key, PREFIX


class TestGenerateApiKey:

    def test_returns_three_parts(self):
        key, key_hash, key_prefix = generate_api_key()
        assert isinstance(key, str)
        assert isinstance(key_hash, str)
        assert isinstance(key_prefix, str)

    def test_key_starts_with_prefix(self):
        key, _, _ = generate_api_key()
        assert key.startswith(PREFIX)

    def test_prefix_is_first_16_chars(self):
        key, _, key_prefix = generate_api_key()
        assert key_prefix == key[:16]

    def test_hash_is_deterministic(self):
        key, key_hash, _ = generate_api_key()
        assert hash_key(key) == key_hash

    def test_unique_keys(self):
        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10, "Generated keys should be unique"

    def test_hash_length(self):
        _, key_hash, _ = generate_api_key()
        assert len(key_hash) == 64  # SHA-256 hex digest


class TestHashKey:

    def test_consistent(self):
        assert hash_key("test") == hash_key("test")

    def test_different_inputs(self):
        assert hash_key("a") != hash_key("b")
