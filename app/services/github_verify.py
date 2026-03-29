import hashlib
import hmac


def verify_signature(secret: str, body: bytes, signature_256: str | None) -> bool:
    if not signature_256:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_256)
