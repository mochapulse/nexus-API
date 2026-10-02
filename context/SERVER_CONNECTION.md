# Bypassing Corporate Firewalls: WireGuard over WebSocket + TLS (`wstunnel`)

## 1. Architectural Overview

Standard WireGuard uses UDP, which is frequently blocked by strict corporate firewalls. Additionally, firewalls performing Deep Packet Inspection (DPI) will block unrecognized traffic on standard web ports. 

The most robust way to make WireGuard traffic look exactly like legitimate HTTPS web traffic is by tunneling it over TCP using **`wstunnel`** alongside a modern reverse proxy (like Nginx or Caddy) equipped with a valid SSL/TLS certificate.

### Network Flow Diagram

```text
[ Workplace PC ] 
       │
       │ (WireGuard UDP locally routed)
       v
  [ wstunnel client ] ────( TCP / HTTPS Port 443 w/ TLS Certificate )────► [ Corporate Firewall ]
                                                                                   │
                                                                                   v
[ Home PC (WireGuard) ] ◄── (WireGuard UDP) ── [ wstunnel server ] ◄── [ Nginx / Caddy Proxy ]

```

---

## 2. Prerequisites: Target Environment

This tutorial assumes the home side runs **Ubuntu Server 24.04 LTS** (Noble Numbat). All commands and package names below are written for it.

* **Operating System:** Ubuntu Server 24.04 LTS.
* **Initial setup:** Update the base image before installing anything:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
* **Required packages:** WireGuard and the reverse proxy come from the official Ubuntu repos:
  ```bash
  sudo apt install -y wireguard nginx
  ```
  `wstunnel` is not packaged for Ubuntu — download the binary for your architecture (`amd64` for the typical x86 server) from its GitHub releases page, or build it with `cargo install wstunnel`.
* **Static LAN IP:** Give the server a fixed address (e.g., `192.168.1.100`) via a DHCP reservation on the router, or configure it statically with netplan. Port forwarding stops working the moment the server's IP changes.
* **Firewall (ufw):** If ufw is enabled, allow the tunnel port or traffic is dropped before it ever reaches the proxy:
  ```bash
  sudo ufw allow 443/tcp
  ```

---

## 3. Step-by-Step Breakdown: How It Works

### Phase 1: At Home (Infrastructure & SSL)

To mimic legitimate web traffic, your home server requires a valid domain and an SSL certificate.

* **Domain:** You obtain a free domain via a Dynamic DNS provider (e.g., DuckDNS, No-IP).
* **Port Forwarding:** Your router must forward inbound TCP traffic on the chosen port to the Ubuntu server's LAN IP — without this rule, none of the traffic ever reaches home (see Section 4).
* **Reverse Proxy:** You configure Caddy or Nginx to listen on TCP port `443`.
* **TLS/SSL:** The proxy automatically provisions a free **Let's Encrypt** SSL certificate for your domain. To any outside observer, your home server now simply looks like a secure website.

### Phase 2: Reverse Proxying (The Gateway)

The reverse proxy (Nginx/Caddy) sits at the edge of your home network and receives all incoming HTTPS traffic on port 443.

* It is configured with a routing rule: If it receives a **WebSocket upgrade request** on a specific, obscured path (e.g., `wss://yourdomain.com/vpn-ws`), it proxies that connection internally to the `wstunnel` server.
* Any other requests (like standard web crawlers hitting the root domain) can be served a generic dummy webpage, effectively hiding the VPN.

### Phase 3: Decapsulation (Unwrapping the Tunnel)

The `wstunnel` server receives the proxied TCP WebSocket stream from Nginx/Caddy.

* **Extraction:** It unwraps the TCP payload to extract the original raw UDP packets.
* **Delivery:** It then forwards these native UDP packets locally to your WireGuard server (which is listening locally on port `51820`).
* Because this happens entirely inside the home server, WireGuard functions completely normally, unaware it was just tunneled over TCP.

### Phase 4: At Work (Client-Side Evasion)

On the restricted workplace network, standard UDP WireGuard connections would be dropped instantly.

* Your work computer runs `wstunnel` in **client mode**.
* Your local WireGuard client is pointed to `127.0.0.1` (localhost) instead of your home IP.
* `wstunnel` intercepts this local UDP traffic, wraps it into a secure WebSocket stream, and sends it out over **TCP port 443** directly to your home domain (`https://yourdomain.com/vpn-ws`).
* **The Result:** The corporate firewall inspects the outbound connection, sees standard TCP traffic on port 443 secured by a valid Let's Encrypt certificate, and allows the traffic through, assuming it is normal, secure web browsing.

---

## 4. Port Forwarding (Router → Ubuntu Server)

Phase 1 (domain + certificate) is useless until inbound internet traffic can actually reach the Ubuntu server. That is the router's **port forwarding** job: every TCP packet arriving on the WAN side of the chosen port is forwarded to the server's static LAN IP.

1. **Find the server's LAN IP** — on the server, run `ip -4 addr show` (e.g., `192.168.1.100`).
2. **Open the router's admin panel** — usually `http://192.168.1.1`; look for "Port Forwarding", "Virtual Server", or "NAT" (often under Advanced / Firewall settings).
3. **Create the forwarding rule:**

   | Field | Value |
   |-------|-------|
   | Protocol | TCP |
   | External port (WAN) | `443` |
   | Destination IP (LAN) | `192.168.1.100` (Ubuntu server) |
   | Destination port (LAN) | `443` |
   | Enabled | ✓ |

4. **Verify from outside your LAN** — disconnect from Wi-Fi (e.g., use mobile data) and run `curl -I https://yourdomain.com`; you should get an HTTP response from the reverse proxy.

**When your ISP blocks port 443:** many residential ISPs block inbound 443. Forward a high port instead (e.g., `8443`) and make the proxy listen on it (`listen 8443 ssl;` in Nginx, `:8443` in the Caddyfile). The client URL then becomes `https://yourdomain.com:8443/vpn-ws`.

**CGNAT warning:** if the router's WAN IP differs from the public IP reported by sites like ifconfig.me, your ISP uses CGNAT and port forwarding will never reach you — you would need a VPS relay instead. Dynamic DNS only helps once the forwarding path actually works, since it merely tracks the current WAN IP.

---

## 5. Important Considerations

* **TCP-over-TCP Drawbacks:** Because you are encapsulating network packets inside a TCP stream, you may experience higher latency or performance drops if there is packet loss (a phenomenon known as TCP meltdown). It is perfectly functional for remote desktop, SSH, and web browsing, but might not be optimal for heavy downloading or gaming.
* **Security:** Always use a difficult-to-guess path for your WebSocket endpoint (e.g., `/vpn-ws-8a9d12`) to prevent automated scanners from discovering your tunnel endpoint.

