"""Resolves the trusted client IP from a Cloud Run request.

Cloud Run sits behind Google's front end (GFE)/load balancer, which
appends exactly two entries to X-Forwarded-For on every request that
reaches the container -- `<real-client-ip>,<gfe-ip>` -- regardless of
whatever the raw incoming request already had in that header. A client
can put any value it wants at the front of its own X-Forwarded-For
header; Google's infrastructure does not strip or replace that, it only
appends after it. So the trustworthy client IP is always the
SECOND-TO-LAST entry (index -2), never the first, and nothing before
that position may ever be treated as trusted.

request.remote_addr is not a usable substitute on Cloud Run: it resolves
to the GFE's own connecting IP -- the same single value for every real
user, not a per-client fallback. It's only meaningful for a bare local
dev server with no Google infrastructure in front of it, which is why
using it here is opt-in, never a silent default.

Shared by every endpoint that needs a rate-limit IP key (login today,
the password-lifecycle endpoints later) so this logic exists exactly
once.
"""

# Returned when no trustworthy IP can be resolved (see get_trusted_client_ip).
# A fixed constant, never derived from anything the client sent -- every
# such request shares this one bucket rather than each getting a fresh,
# attacker-chosen key.
UNRESOLVED_IP_KEY = '__unresolved_client_ip__'


def get_trusted_client_ip(headers, remote_addr=None, allow_remote_addr_fallback=False):
    """Return a client IP a caller can safely use as a rate-limit key.

    Never returns a value the client itself could have chosen: either
    the second-to-last X-Forwarded-For entry (the one Google's own
    infrastructure appended, not attacker-suppliable), the real
    remote_addr peer -- but only when the caller explicitly opts into
    that for local dev -- or the fixed UNRESOLVED_IP_KEY sentinel.
    Never the first X-Forwarded-For entry, and never remote_addr on
    Cloud Run.
    """
    xff = headers.get('X-Forwarded-For')
    if xff:
        parts = [p.strip() for p in xff.split(',') if p.strip()]
        if len(parts) >= 2:
            return parts[-2]
        # Fewer than two entries: this request did not arrive through
        # Cloud Run's expected two-hop path (Google always appends
        # <client-ip>,<gfe-ip>) -- a misconfigured proxy, a direct hit
        # bypassing the front end, or a bare local dev server. There is
        # no entry left in this header that Google's infrastructure,
        # rather than the client itself, is vouching for, so falling
        # through rather than trusting any of it here.

    if allow_remote_addr_fallback and remote_addr:
        return remote_addr

    return UNRESOLVED_IP_KEY
