# SEBI Static-IP VPS Deployment Guide (Mumbai Region)

Under SEBI's retail algorithmic trading framework, all DhanHQ v2.5 live execution requests should originate from a **single dedicated Static IP** registered/whitelisted inside your DhanHQ API portal.

## 1. Recommended Cloud Regions (Lowest NSE/BSE Latency)
- **AWS Mumbai (`ap-south-1`):** Provision a `t3.small` or `t3.medium` Ubuntu 24.04 instance and attach an **Elastic IP (EIP)**.
- **DigitalOcean Bangalore (`blr1`):** Provision a 2 vCPU / 4 GB Droplet with a **Reserved IP**.

## 2. Firewall Hardening (UFW)
Allow only SSH (`22`), HTTP (`80`), and HTTPS (`443`) inbound so Postgres (`5432`) and FastAPI (`8000`) are never exposed directly to the public internet:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 3. Configure `.env` & Boot Production Stack
```bash
cp .env.example .env
# Edit .env and set:
#   TERMINAL_DOMAIN=terminal.yourdomain.in
#   POSTGRES_PASSWORD=<strong-random-password>
#   TRADING_MODE=PAPER_LIVE   (always start safe; switch to DHAN_LIVE only via UI confirmation)

docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
```
Caddy automatically provisions Let's Encrypt TLS certificates for `TERMINAL_DOMAIN` and proxies `/api/*` (including `/api/v1/ws/stream` WebSockets) to the backend.

## 4. Verify & Whitelist Static Egress IP on DhanHQ
1. Check your backend's outbound public IP directly from the VPS:
   ```bash
   curl -s https://terminal.yourdomain.in/api/v1/system/egress-ip
   ```
   Or open the **Dhan API** modal in the TopBar and inspect **Backend Egress Static IP**.
2. Log in to **DhanHQ Web -> Access DhanHQ APIs -> Static IP Whitelist** and register that exact IPv4 address.
3. Verify health and default safe boot mode (`execution_mode: "PAPER_LIVE"`):
   ```bash
   curl -s https://terminal.yourdomain.in/health
   ```
4. Always test any new strategy in **Dhan Sandbox** mode first before switching the TopBar mode pill to **Dhan Live**.

