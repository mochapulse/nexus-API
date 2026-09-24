"""Minecraft server integration for the watchdog.

Submodules:
    slp: Server List Ping probe (stdlib ``socket``), used to detect
        whether the Minecraft server is reachable and how many players
        are online.
    service: Thin ``systemctl`` wrappers to query and restart the
        Minecraft systemd unit.
"""
