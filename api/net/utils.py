"""DuckDNS dynamic DNS updater.

Fetches the host's public IP from external services and updates a
DuckDNS subdomain record to point to it.  All HTTP I/O is performed
through :mod:`httpx` so callers can ``await`` results without blocking
the event loop.

Functions
---------
get_public_ip(client)
    Retrieve the current public IP via api.myip.com, falling back to
    ifconfig.me when the primary service is unavailable.
update_duckdns(domain, token, client)
    Compute the public IP and push it to DuckDNS, returning a structured
    result dict suitable for JSON serialization.
"""

import httpx
import orjson


async def get_public_ip(client: httpx.AsyncClient) -> str | None:
    """Fetch the current public IP address.

    Queries ``api.myip.com`` first (JSON response).  If that fails for
    any reason, falls back to ``ifconfig.me/ip`` (plain-text response).

    Args:
        client: Shared :class:`httpx.AsyncClient` instance owned by the
            caller; the client's lifetime is managed externally so this
            function never closes it.

    Returns:
        The public IPv4 address as a string, or ``None`` if both
        services are unreachable.
    """
    for fetcher in (_ip_from_myip_com, _ip_from_ifconfig):
        ip = await fetcher(client)
        if ip:
            return ip
    return None


async def update_duckdns(
    domain: str,
    token: str,
    client: httpx.AsyncClient,
) -> dict[str, object]:
    """Update a DuckDNS subdomain with the current public IP.

    Retrieves the public IP via :func:`get_public_ip` and sends it to the
    DuckDNS update endpoint.  The IP parameter is always passed explicitly
    so the record reflects the IP this host actually sees, rather than
    relying on DuckDNS's server-side detection.

    Args:
        domain: DuckDNS subdomain name (e.g. ``"nexus-coffee"``), without
            the ``.duckdns.org`` suffix.
        token: DuckDNS API token for the account that owns the domain.
        client: Shared :class:`httpx.AsyncClient` instance owned by the
            caller.

    Returns:
        A dict with keys ``success`` (bool), ``domain`` (str), ``ip``
        (str or ``None``), and ``message`` (str) describing the outcome.
    """
    ip = await get_public_ip(client)
    ip_param = ip or ""
    url = (
        f"https://www.duckdns.org/update"
        f"?domains={domain}&token={token}&ip={ip_param}"
    )

    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "DuckDNS-Python-Client"},
        )
        result = resp.text.strip()

        if result == "OK":
            return {
                "success": True,
                "domain": domain,
                "ip": ip_param or "auto-detected",
                "message": "DuckDNS record updated successfully.",
            }
        return {
            "success": False,
            "domain": domain,
            "ip": ip_param or None,
            "message": f"DuckDNS rejected the update: '{result}'.",
        }
    except Exception as e:
        return {
            "success": False,
            "domain": domain,
            "ip": ip_param or None,
            "message": f"Failed to contact DuckDNS: {e}",
        }


async def _ip_from_myip_com(client: httpx.AsyncClient) -> str | None:
    """Retrieve the public IP from ``api.myip.com`` (JSON endpoint).

    Returns:
        The IP address string, or ``None`` on any failure.
    """
    try:
        resp = await client.get(
            "https://api.myip.com",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=5,
        )
        data = orjson.loads(resp.text)
        ip = data.get("ip", "").strip()
        return ip if ip else None
    except Exception:
        return None


async def _ip_from_ifconfig(client: httpx.AsyncClient) -> str | None:
    """Retrieve the public IP from ``ifconfig.me/ip`` (plain-text endpoint).

    Returns:
        The IP address string, or ``None`` on any failure.
    """
    try:
        resp = await client.get(
            "https://ifconfig.me/ip",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=5,
        )
        ip = resp.text.strip()
        return ip if ip else None
    except Exception:
        return None
