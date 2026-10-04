"""Which address a request counts against, and whether it arrived over https.

Behind a reverse proxy every request reaches the API from the proxy's address, so per-client limits would
share one bucket. ``X-Forwarded-For`` is honoured ONLY when the immediate peer is a configured trusted proxy
(``OAH_TRUSTED_PROXIES``); otherwise it is ignored, because any client can send that header itself.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Collection


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _hop_client(peer: str, forwarded_for: str | None, hops: int) -> str:
    """The entry ``hops`` places from the right of the chain: what the outermost trusted proxy recorded as its client.

    Every entry to its left was supplied by the caller and is ignored (a spoofed leading entry changes nothing). Fewer
    entries than hops, an empty entry or an entry that is not an IP address means the chain is not what the deployment
    promised: the peer is used, never a guessed address.
    """
    if not forwarded_for:
        return peer
    parts = [part.strip() for part in forwarded_for.split(",")]
    if len(parts) < hops or not parts[-hops] or not _is_address(parts[-hops]):
        return peer
    return parts[-hops]


def client_key(
    peer: str | None, forwarded_for: str | None, trusted_proxies: Collection[str], trusted_hops: int = 0
) -> str:
    """The client address to rate-limit: the peer itself unless it is a trusted proxy.

    For a trusted proxy the ``X-Forwarded-For`` chain is walked from the right and the first address that is
    not itself a trusted proxy is the client (the entries to its left are client-supplied and not trusted).
    A malformed chain falls back to the peer, never to a guessed address.

    ``trusted_hops`` (``OAH_TRUSTED_PROXY_HOPS``, default 0 = off) is for a platform whose proxy addresses are not known in
    advance (Cloud Run): the client is the entry that many places from the right of the chain, whatever the peer is. It
    is safe only when every request really passes through that many proxies, which is the deployment's promise, not
    something this function can check. A peer listed in ``trusted_proxies`` is handled by the address-based rule above.
    """
    if not peer:
        return "unknown"
    if peer in trusted_proxies:
        if not forwarded_for:
            return peer
        for entry in reversed([part.strip() for part in forwarded_for.split(",") if part.strip()]):
            if not _is_address(entry):
                return peer
            if entry not in trusted_proxies:
                return entry
        return peer
    if trusted_hops > 0:
        return _hop_client(peer, forwarded_for, trusted_hops)
    return peer


# An end-user token is an opaque value chosen by the trusted web server layer (for example a keyed hash of a visitor
# session). It is UNTRUSTED input: anyone holding the shared key can send any token, so it is a fairness aid for the
# per-minute chat and explanation limits and nothing else (never authentication, never an identity, never logged in full).
END_USER_HEADER = "x-oah-end-user"
_END_USER_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,64}")


def end_user_token(value: str | None) -> str | None:
    """The token when it matches the strict pattern (16 to 64 of ``A-Z a-z 0-9 _ -``); otherwise None (the header is ignored)."""
    if value is None or not _END_USER_TOKEN.fullmatch(value):
        return None
    return value


def rate_key(client: str, token: str | None) -> str:
    """The bucket of the chat and explanation limiters: the client address, plus the end-user token when one is valid."""
    return f"{client}|u:{token}" if token else client


def is_https(scheme: str, peer: str | None, forwarded_proto: str | None, trusted_proxies: Collection[str]) -> bool:
    """True when the request used https directly, or through a trusted proxy that says so."""
    if scheme == "https":
        return True
    return bool(peer and peer in trusted_proxies and (forwarded_proto or "").strip().lower() == "https")
