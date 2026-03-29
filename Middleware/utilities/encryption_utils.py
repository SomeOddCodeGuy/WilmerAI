import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_Fernet = None
_PBKDF2HMAC = None
_hashes = None


def _ensure_cryptography():
    """Lazily imports cryptography components on first use."""
    global _Fernet, _PBKDF2HMAC, _hashes
    if _Fernet is None:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        _Fernet = Fernet
        _PBKDF2HMAC = PBKDF2HMAC
        _hashes = hashes


def derive_fernet_key(api_key: str, username: Optional[str] = None) -> bytes:
    """
    Derives a Fernet-compatible encryption key from an API key using PBKDF2.

    The derivation uses a per-user salt built from a SHA-256 hash of the
    username and 100,000 iterations of SHA-256. The per-user salt ensures
    that even if two users happen to use the same API key, they derive
    different encryption keys.

    When ``username`` is None (e.g., in standalone scripts), a fixed
    application-level salt is used instead.

    Args:
        api_key (str): The raw API key string.
        username (Optional[str]): The WilmerAI username. When provided, it
            is hashed into the salt. Defaults to None.

    Returns:
        bytes: A 32-byte URL-safe base64-encoded key suitable for Fernet.
    """
    _ensure_cryptography()
    if username is not None:
        user_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
        salt = f"WilmerAI-v1-{user_hash}".encode("utf-8")
    else:
        salt = b"WilmerAI-encryption-salt-v1"
    kdf = _PBKDF2HMAC(
        algorithm=_hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    key_bytes = kdf.derive(api_key.encode("utf-8"))
    return base64.urlsafe_b64encode(key_bytes)


def hash_api_key(api_key: str) -> str:
    """
    Returns the first 16 hex characters of the SHA-256 hash of the API key.

    This is used for directory naming so that the raw key never appears in
    file paths.

    Args:
        api_key (str): The raw API key string.

    Returns:
        str: A 16-character hex string derived from the key.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def encrypt_bytes(data: bytes, fernet_key: bytes) -> bytes:
    """
    Encrypts raw bytes using Fernet symmetric encryption.

    Args:
        data (bytes): The plaintext bytes to encrypt.
        fernet_key (bytes): The Fernet key (from ``derive_fernet_key``).

    Returns:
        bytes: The encrypted ciphertext.
    """
    _ensure_cryptography()
    return _Fernet(fernet_key).encrypt(data)


def decrypt_bytes(token: bytes, fernet_key: bytes) -> bytes:
    """
    Decrypts Fernet-encrypted bytes.

    Args:
        token (bytes): The encrypted ciphertext.
        fernet_key (bytes): The Fernet key (from ``derive_fernet_key``).

    Returns:
        bytes: The decrypted plaintext bytes.
    """
    _ensure_cryptography()
    return _Fernet(fernet_key).decrypt(token)


def get_encryption_key_if_available(api_key: Optional[str]) -> Optional[bytes]:
    """
    Convenience helper: derives the Fernet key when an API key is present
    and the ``encryptUsingApiKey`` user config setting is enabled.

    The current WilmerAI username is automatically fetched and used as
    the per-user salt for key derivation.

    Directory isolation (via ``get_api_key_hash_if_available``) always
    applies when an API key is present. Encryption only applies when the
    user has opted in via their config.

    Args:
        api_key (Optional[str]): The raw API key, or None.

    Returns:
        Optional[bytes]: The derived Fernet key, or None if encryption
            is not applicable.
    """
    if api_key:
        from Middleware.utilities.config_utils import get_encrypt_using_api_key, get_current_username
        if get_encrypt_using_api_key():
            username = get_current_username()
            return derive_fernet_key(api_key, username=username)
    return None


def get_api_key_hash_if_available(api_key: Optional[str]) -> Optional[str]:
    """
    Convenience helper: hashes the API key when present.

    Args:
        api_key (Optional[str]): The raw API key, or None.

    Returns:
        Optional[str]: The 16-char hex hash, or None if no key was provided.
    """
    if api_key:
        return hash_api_key(api_key)
    return None
