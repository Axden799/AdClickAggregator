import hashlib
import hmac

from app.config import settings


def _message(impression_id: str, ad_id: int) -> str:
    """The canonical message the signature covers. The ":" delimiter prevents
    (impression_id="1", ad_id=23) from colliding with (impression_id="12",
    ad_id=3) — both must produce distinct messages."""
    return f"{impression_id}:{ad_id}"


def sign_impression(impression_id: str, ad_id: int) -> str:
    # TODO (you): return the HMAC-SHA256 hex signature of
    # _message(impression_id, ad_id), keyed by settings.secret_key.
    return hmac.new(
        settings.secret_key.encode(),
        _message(impression_id, ad_id).encode(),
        hashlib.sha256
        ).hexdigest()


def verify_impression(impression_id: str, ad_id: int, sig: str) -> bool:
    # TODO (you): recompute the expected signature and compare it to `sig`
    # using a constant-time comparison (not ==).
    expected = sign_impression(impression_id, ad_id)
    return hmac.compare_digest(expected, sig)
