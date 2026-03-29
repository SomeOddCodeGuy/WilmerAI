
import pytest

from Middleware.utilities.encryption_utils import (
    derive_fernet_key,
    hash_api_key,
    encrypt_bytes,
    decrypt_bytes,
    get_encryption_key_if_available,
    get_api_key_hash_if_available,
)


class TestDeriveFernetKey:
    """Tests for derive_fernet_key."""

    def test_deterministic(self):
        key1 = derive_fernet_key("test-key-123")
        key2 = derive_fernet_key("test-key-123")
        assert key1 == key2

    def test_different_keys_produce_different_output(self):
        key1 = derive_fernet_key("key-a")
        key2 = derive_fernet_key("key-b")
        assert key1 != key2

    def test_returns_bytes(self):
        key = derive_fernet_key("any-key")
        assert isinstance(key, bytes)

    def test_key_length_is_44_bytes_base64(self):
        key = derive_fernet_key("any-key")
        assert len(key) == 44

    def test_username_salt_changes_derived_key(self):
        """Same API key with different usernames should produce different keys."""
        key_no_user = derive_fernet_key("same-api-key")
        key_user_a = derive_fernet_key("same-api-key", username="alice")
        key_user_b = derive_fernet_key("same-api-key", username="bob")
        assert key_no_user != key_user_a
        assert key_no_user != key_user_b
        assert key_user_a != key_user_b

    def test_username_salt_is_deterministic(self):
        """Same API key + same username should always produce the same key."""
        key1 = derive_fernet_key("my-key", username="alice")
        key2 = derive_fernet_key("my-key", username="alice")
        assert key1 == key2

    def test_none_username_uses_fixed_salt(self):
        """Passing username=None should behave like omitting it."""
        key1 = derive_fernet_key("my-key")
        key2 = derive_fernet_key("my-key", username=None)
        assert key1 == key2


class TestHashApiKey:
    """Tests for hash_api_key."""

    def test_returns_16_chars(self):
        result = hash_api_key("test-key")
        assert len(result) == 16

    def test_deterministic(self):
        h1 = hash_api_key("my-api-key")
        h2 = hash_api_key("my-api-key")
        assert h1 == h2

    def test_different_keys_produce_different_hashes(self):
        h1 = hash_api_key("key-a")
        h2 = hash_api_key("key-b")
        assert h1 != h2

    def test_returns_hex_string(self):
        result = hash_api_key("test")
        assert all(c in "0123456789abcdef" for c in result)


class TestEncryptDecryptBytes:
    """Tests for encrypt_bytes and decrypt_bytes round-trip."""

    def test_round_trip(self):
        key = derive_fernet_key("round-trip-key")
        plaintext = b'{"messages": ["hello", "world"]}'
        encrypted = encrypt_bytes(plaintext, key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == plaintext

    def test_encrypted_differs_from_plaintext(self):
        key = derive_fernet_key("test-key")
        plaintext = b"secret data"
        encrypted = encrypt_bytes(plaintext, key)
        assert encrypted != plaintext

    def test_wrong_key_fails(self):
        key_a = derive_fernet_key("key-a")
        key_b = derive_fernet_key("key-b")
        plaintext = b"secret data"
        encrypted = encrypt_bytes(plaintext, key_a)
        with pytest.raises(Exception):
            decrypt_bytes(encrypted, key_b)

    def test_empty_bytes(self):
        key = derive_fernet_key("test-key")
        plaintext = b""
        encrypted = encrypt_bytes(plaintext, key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == plaintext

    def test_round_trip_with_username_salt(self):
        """Encrypt/decrypt should work correctly with username-salted keys."""
        key = derive_fernet_key("my-api-key", username="testuser")
        plaintext = b'{"content": "hello"}'
        encrypted = encrypt_bytes(plaintext, key)
        decrypted = decrypt_bytes(encrypted, key)
        assert decrypted == plaintext

    def test_wrong_username_fails_decrypt(self):
        """Key derived with one username cannot decrypt data from another."""
        key_alice = derive_fernet_key("same-key", username="alice")
        key_bob = derive_fernet_key("same-key", username="bob")
        encrypted = encrypt_bytes(b"secret", key_alice)
        with pytest.raises(Exception):
            decrypt_bytes(encrypted, key_bob)


class TestConvenienceHelpers:
    """Tests for get_encryption_key_if_available and get_api_key_hash_if_available."""

    def test_encryption_key_returns_none_for_none(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_encrypt_using_api_key', return_value=True)
        assert get_encryption_key_if_available(None) is None

    def test_encryption_key_returns_none_for_empty(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_encrypt_using_api_key', return_value=True)
        assert get_encryption_key_if_available("") is None

    def test_encryption_key_returns_bytes_when_enabled(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_encrypt_using_api_key', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='testuser')
        result = get_encryption_key_if_available("my-key")
        assert isinstance(result, bytes)

    def test_encryption_key_returns_none_when_disabled(self, mocker):
        mocker.patch('Middleware.utilities.config_utils.get_encrypt_using_api_key', return_value=False)
        result = get_encryption_key_if_available("my-key")
        assert result is None

    def test_encryption_key_uses_username_for_derivation(self, mocker):
        """The convenience helper should pass the current username to derive_fernet_key."""
        mocker.patch('Middleware.utilities.config_utils.get_encrypt_using_api_key', return_value=True)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='alice')
        result = get_encryption_key_if_available("my-key")
        expected = derive_fernet_key("my-key", username="alice")
        assert result == expected

    def test_api_key_hash_returns_none_for_none(self):
        assert get_api_key_hash_if_available(None) is None

    def test_api_key_hash_returns_none_for_empty(self):
        assert get_api_key_hash_if_available("") is None

    def test_api_key_hash_returns_string_for_key(self):
        result = get_api_key_hash_if_available("my-key")
        assert isinstance(result, str)
        assert len(result) == 16
