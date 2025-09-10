import hashlib, hmac, os, base64

# -------------------------
# bcrypt-like API (PBKDF2-SHA256 under the hood)
# -------------------------

def gensalt(length: int = 16) -> str:
    """
    Generate a random salt (base64-encoded).
    """
    return base64.b64encode(os.urandom(length)).decode("utf-8")

def hashpw(password: str, salt: str, iterations: int = 200_000, dklen: int = 32) -> str:
    """
    Hash a password with PBKDF2-HMAC-SHA256.
    Returns: "pbkdf2_sha256$<iterations>$<salt>$<hash>"
    """
    if isinstance(password, str):
        password = password.encode("utf-8")
    salt_bytes = base64.b64decode(salt.encode("utf-8"))
    dk = hashlib.pbkdf2_hmac("sha256", password, salt_bytes, iterations, dklen=dklen)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(dk).decode('utf-8')}"

def checkpw(password: str, stored: str) -> bool:
    """
    Verify if a password matches the stored hash string.
    Uses constant-time comparison.
    """
    try:
        algo, iterations_str, salt, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            raise ValueError("Unsupported algorithm")
        iterations = int(iterations_str)
        expected = base64.b64decode(hash_b64.encode("utf-8"))
    except Exception:
        return False

    # Recompute candidate hash
    if isinstance(password, str):
        password = password.encode("utf-8")
    salt_bytes = base64.b64decode(salt.encode("utf-8"))
    candidate = hashlib.pbkdf2_hmac("sha256", password, salt_bytes, iterations, dklen=len(expected))

    return hmac.compare_digest(candidate, expected)