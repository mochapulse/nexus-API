# Minecraft Watchdog — Deployment Report

Date: 2026-09-23 · Release: merged to `main` via PR #1 (`287756b`) · Host: `nexus-lan`

## Status

| Area | State |
|------|-------|
| Code | Merged to `main` (PRs #1–#5), 175 tests passing |
| Server deploy (nexus-lan) | Done: pull, deps, `.env`, polkit, service restarted |
| Windows CLI | Updated via `git pull` (no new deps) |
| Polkit restart rule | Verified (`systemctl restart mc-server-create --no-ask-password` → OK) |
| Poweroff test | **Host powered off** after `active 5m threshold 1m` — log confirmation pending |

## Poweroff Test Timeline (2026-09-23, COT)

| Time | Event |
|------|-------|
| 23:27:10 | `mc-server-create` restarted (polkit test) |
| 23:32:55 | `nexus-API mc-server active 5m threshold 1m` (POST 200) |
| 23:33:01 | `status` (GET 200) — first probe not done yet (probe interval 30s) |
| ~23:34 | SSH session closed by the remote host |
| ~23:35 | Host powered off (~1 min after SSH closed) |

### Why the host powers off ~1 minute after SSH closes (expected)

`systemctl poweroff` shuts down in order:

1. **User sessions are terminated first** (logind) → the SSH connection drops immediately.
2. systemd stops services. `mc-server-create`'s `ExecStop` sends `stop` and **waits for Minecraft to save the world** (up to `TimeoutStopSec=120`).
3. Only then does the machine power off.

So the ~1 minute gap is the modded world being saved. That is the fix from
`daemon/mc-server-create.service` working as intended, not a bug.

Verify after boot:

```bash
journalctl -b -1 -u mc-server-create --no-pager | tail -5   # "Stopping..." → "Stopped..." ~1 min apart
journalctl -b -1 -u nexus-api --no-pager | tail -10          # "Watchdog triggering poweroff: ..."
```

If `-b -1` reports no previous boot, the journal is not persistent
(`sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald` enables it).

## Open Issues

| # | Severity | Issue | Evidence | Proposed fix |
|---|----------|-------|----------|--------------|
| 1 | Medium | **Arming while MC is booting restarts it immediately.** The 5m startup grace only applies after restarts made by the watchdog itself. | `tick()`: unreachable + `last_restart_at is None` → `RESTART_MC` | Start the grace at arm time too (`last_restart_at = armed_at`-style grace). |
| 2 | Medium | **`status` is misleading while disarmed.** The loop only probes when armed, so a disarmed status shows `MC reachable: no` / `unreachable` meaning "never probed", not "down". | `api/mc/watchdog.py:187` (`None` probe → `False`) | Report `null`/"unknown" when there is no probe, or run a live probe on `GET`. |
| 3 | Low | **App INFO logs are not visible** in the journal (e.g. "watchdog loop started", "restarted", "window expired"). Only WARNING+ appears (Python's last-resort handler). Pre-existing: DuckDNS logs are affected too. | Journal after restart shows only uvicorn lines | Configure `logging.basicConfig(level=INFO)` (or reuse uvicorn's handler) at startup. |
| 4 | Low | **Default port does not match production.** Default `MINECRAFT_PORT=25565`, real server uses `37294`. A wrong port makes the watchdog restart MC 3 times, then disarm. | `server.properties: server-port=37294` | Already set in the server `.env`; call it out in the README deploy step. |
| 5 | Low | DEBUG placeholders are static (the POST template always shows threshold 1800; the CLI placeholder deadline is fixed). | DEBUG run | Cosmetic; optionally echo the requested values. |
| 6 | Low | `nexus-API health` has no DEBUG guard (sends a real request in DEBUG). Pre-existing. | DEBUG CLI run | Align with the other commands or document it. |
| 7 | Info | The Windows checkout looks fully modified when read from WSL (`/mnt/c`): file-mode/CRLF noise only; Git for Windows sees it as clean. | `git -c core.fileMode=false diff --ignore-cr-at-eol` → empty | `git config core.fileMode false` in that checkout if using WSL git on it. |
| 8 | Info | Remote feature branches (`feat/mc-server-watchdog`, `feat/mc-watchdog-01..04`) still exist on GitHub. | `git branch -r` | Delete when no longer needed. |
| 9 | Info | Tooling: `gh pr edit` fails (classic Projects GraphQL deprecation); the final merge to `main` needed manual approval. | Session | Use `gh api -X PATCH repos/<repo>/pulls/<n>`; merge manually. |

## Commands Used

### Server (nexus-lan) — deploy

```bash
cd ~/nexus-API
git status --short && git branch --show-current
git pull origin main
git fetch --tags
source venv/bin/activate
pip install -r requirements.txt                      # adds mcstatus + asyncio-dgram
awk -F= '/^server-port/{print $2}' "<MC dir>/server.properties"   # → 37294
nano api/.env                                        # DEBUG=false, MINECRAFT_PORT=37294, MINECRAFT_SERVICE=mc-server-create
```

Polkit rule (restart/start of the MC unit only):

```bash
sudo tee /etc/polkit-1/rules.d/20-nexus-mc-server.rules > /dev/null << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "mc-server-create.service" &&
        (action.lookup("verb") == "start" || action.lookup("verb") == "restart") &&
        subject.user == "nexus-lan") {
        return polkit.Result.YES;
    }
});
EOF
sudo systemctl restart polkit
sudo systemctl restart nexus-api
systemctl status nexus-api --no-pager
systemctl restart mc-server-create --no-ask-password && echo "polkit OK"
```

Readiness and monitoring:

```bash
ss -ltn | grep 37294                                  # LISTEN = MC accepts connections
tmux -L mc-server-create attach -t mc-server-create   # console (detach: Ctrl+B, D)
journalctl -u nexus-api -f
```

### Windows workstation — update

```powershell
cd C:\Users\david\nexus-API
git status
git pull origin main
git fetch --tags
nexus-API mc-server --help
```

### Watchdog test

```powershell
nexus-API mc-server status
nexus-API mc-server active 5m threshold 1m   # window must exceed threshold + ~30s
nexus-API mc-server status                   # wait ≥30s for the first probe
nexus-API wol                                # power the host back on
```

## Next Steps

1. Wake the host (`nexus-API wol`), confirm the poweroff from the previous boot's journal, and confirm `status` → `Armed: no`.
2. Fix issues 1–3 (small, one PR).
3. Optionally tag `v0.4.0` (minor: new feature) and delete the merged remote branches.
