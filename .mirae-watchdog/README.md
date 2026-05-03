# Mirae Portal Watchdog

## Three-Layer Protection

### Layer 1: systemd `Restart=always`

- Service: `mirae-tunnel.service`
- Restarts localtunnel process if it crashes
- Config: `RestartSec=10`

### Layer 2: URL Health Check (cron)

- Script: `/usr/local/bin/mirae-tunnel-healthcheck.sh`
- Runs every 2 minutes via cron
- Checks if `mirae-portal.loca.lt` responds with HTTP 200
- Restarts `mirae-tunnel.service` if public URL is down
- Log: `/var/log/mirae-tunnel-healthcheck.log`

### Layer 3: Portal systemd

- Service: `sg-portal.service`
- Independent restart policy for the FastAPI app

## Commands

```bash
# Check tunnel status
systemctl status mirae-tunnel

# Check health check log
tail -f /var/log/mirae-tunnel-healthcheck.log

# Manual restart
systemctl restart mirae-tunnel

# Check cron
crontab -l | grep mirae-tunnel
```
