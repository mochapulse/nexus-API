"""Shared state for network background services.

Module-level variables updated by the DuckDNS background service and
read by the ``/health`` endpoint.  Thread-safety is not a concern here:
the event loop is single-threaded, and the health endpoint reads the
values synchronously within the same loop.

Attributes
----------
last_duckdns_update_ms : int or None
    Unix timestamp in milliseconds of the last successful DuckDNS update,
    or ``None`` if no update has completed yet.
connectivity_delay_ms : int or None
    Round-trip time in milliseconds of the most recent TCP handshake
    to ``google.com:443``, or ``None`` before the first probe.
"""

last_duckdns_update_ms: int | None = None
connectivity_delay_ms: int | None = None
