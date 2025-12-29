## WyzeGuardi

**Intelligent, presence-based Wyze camera automation that actually works.**

Born from frustration with iOS Shortcuts notifications spam.

## The Problem

Ever tried automating Wyze cameras with iOS Shortcuts? You know the pain:
- 🔔 **Notification spam** - "Running automation..." every single time
- ⚠️ **Can't disable alerts** - iOS forces notifications even with "Show When Run" off
- 📡 **Network blips = false triggers** - WiFi hiccups cause constant misfires
- 🐛 **Unreliable execution** - sometimes works, sometimes doesn't
- 📱 **Phone-dependent** - only works when your device is connected

## The Solution

WyzeGuardi moves camera automation **off your phone** and onto a server that runs 24/7:

✅ **Silent operation** - No notifications, ever  
✅ **Rock-solid detection** - ARP/Layer 2 + grace periods prevent false triggers  
✅ **Always watching** - Runs independently of your phone  
✅ **Privacy-first** - All processing stays on your local network  
✅ **Set and forget** - Just works in the background  

Built by an engineer who got tired of iOS automation nonsense.

---

## Quick Start

Get running in 3 steps:

```bash
# 1. Clone and install
git clone https://github.com/Baslocal/WyzeGuardi.git
cd WyzeGuardi
sudo bash install.sh

# 2. Start service
sudo systemctl start wyzeguardi

# 3. Register account (in browser)
http://YOUR_SERVER_IP:5000/register
```

Cameras now turn **OFF when you're home**, **ON when you're away**. Automatically.

---

## Features

### Core Automation
- **Automatic presence detection** - Multiple methods: ARP (Layer 2), network ping, iOS heartbeat
- **Manual override** - Instant control via web dashboard (2-hour duration)
- **Custom schedules** - Time-based rules (weekday/weekend, custom times)
- **Multi-device support** - Track multiple phones, tablets, etc.
- **Grace periods** - Prevents false "away" triggers from brief WiFi drops

### Security & Privacy
- **Runs locally** - Data never leaves your network
- **Encrypted storage** - All credentials encrypted at rest
- **Non-root user** - Dedicated service account prevents privilege escalation
- **CSRF protection** - Secure state-changing operations
- **Rate limiting** - Prevents webhook abuse

### User Experience
- **Responsive dashboard** - Mobile-friendly web interface
- **Real-time updates** - Auto-refreshing status and activity log
- **Easy setup wizard** - First-time configuration in browser
- **Timezone aware** - Automatic handling for schedules and logs

---

## Why a Dedicated User? (Security)

WyzeGuardi runs as the `wyzeguardi` user (not root) because:

- **Limits damage if compromised** - Attackers can't access system files or install malware
- **Industry standard** - Follows principle of least privilege
- **Audit trail** - All actions tied to dedicated account, easy to track
- **File isolation** - Application can only modify its own files

**Installation:** `/opt/wyzeguardi` (system-wide, proper permissions)  
**Runtime user:** `wyzeguardi` (non-admin, security hardened)

---

## Installation

### Secure Installation (Recommended)

Creates dedicated user, sets permissions, auto-starts on boot:

```bash
git clone https://github.com/Baslocal/WyzeGuardi.git
cd WyzeGuardi
sudo bash install.sh
```

**What it does:**
- Creates `wyzeguardi` system user (non-root)
- Installs to `/opt/wyzeguardi` with proper permissions
- Sets up systemd service with security hardening
- Enables auto-start on boot

**Post-install cleanup:**
```bash
# After confirming service works
cd ~ && rm -rf WyzeGuardi
```

### Legacy Installation (Not Recommended)

⚠️ **Runs as root** - Only for testing or temporary deployments:

```bash
git clone https://github.com/Baslocal/WyzeGuardi.git
cd WyzeGuardi
bash legacy_install.sh
```

| Feature | Secure | Legacy |
|---------|--------|--------|
| User | `wyzeguardi` | `root` ⚠️ |
| Location | `/opt/wyzeguardi` | `~/WyzeGuardi` |
| Auto-start | ✅ systemd | ❌ Manual |
| Security | ✅ Hardened | ⚠️ Root access |
| **Use case** | **Production** | **Testing only** |

---

## First-Time Setup

**Prerequisites:** 
- Wyze account with cameras
- API credentials from https://developer-api-console.wyze.com/

**Steps:**

1. **Start service**
   ```bash
   sudo systemctl start wyzeguardi
   ```

2. **Register admin account**  
   Open browser: `http://YOUR_SERVER_IP:5000/register`  
   Create username and strong password

3. **Complete setup wizard**
   - Enter Wyze email and password
   - Add API Key and API ID (from Wyze Developer Console)
   - Set timezone (e.g., America/New_York)
   - Configure thresholds (defaults: HOME=10min, AWAY=30min)
   - Save encryption key shown after setup

4. **Add devices**
   - Navigate to Device Manager
   - Click "Add Device"
   - Enter device name (e.g., "iPhone")
   - Choose detection method: **`arp_3x`** (recommended - fastest, most reliable)
   - Save

5. **Verify automation**
   - Check Dashboard for device status
   - Leave home network → cameras should turn ON
   - Return home → cameras should turn OFF

**Done!** Your cameras now respond to your presence automatically.

---

## Detection Methods

WyzeGuardi offers multiple ways to detect your presence:

| Method | Speed | Reliability | Setup Required |
|--------|-------|-------------|----------------|
| **arp_3x** | ~30ms | ⭐⭐⭐⭐⭐ | None |
| **arp** | ~30ms | ⭐⭐⭐⭐ | None |
| **ping** | 3-9s | ⭐⭐⭐ | None |
| **heartbeat** | N/A | ⭐⭐⭐⭐ | iOS Shortcut |
| **arp_and_heartbeat** | ~30ms | ⭐⭐⭐⭐⭐ | iOS Shortcut |
| **both** | 3-9s | ⭐⭐⭐⭐ | iOS Shortcut |

**Recommended:** `arp_3x` - No setup required, most reliable

**Optional: iOS Shortcut for heartbeat** (adds redundancy):
1. Open Shortcuts app → Create new shortcut
2. Add action: "Get Contents of URL"
   - URL: `http://YOUR_SERVER_IP:5000/heartbeat?token=YOUR_WEBHOOK_SECRET`
   - Method: GET
3. Create automation: Time of Day → Every 10 minutes
4. Disable "Ask Before Running"

---

## Daily Usage

### Dashboard (`http://YOUR_SERVER_IP:5000`)

**Manual control:**
- Turn Cameras OFF (2h) - Override to keep cameras off
- Turn Cameras ON (2h) - Override to keep cameras on

**Status display:**
- Current camera state (on/off)
- Presence status (HOME/AWAY/GRACE)
- Online devices count
- Last heartbeat time
- Manual override expiration

**Activity log:**
- Recent events (camera changes, heartbeats, errors)
- Auto-refreshes every 30 seconds

### Device Manager

**Add/edit/delete devices:**
- Register multiple phones, tablets, etc.
- Choose detection method per device
- View online/offline status
- Test detection with "Test" button

### Schedule Manager

**Create time-based rules:**
- Weekday 8am-6pm: Cameras ON (at work)
- Weekend 9am-11pm: Cameras OFF (home all day)
- Night 11pm-7am: Cameras ON (sleeping)

Schedules override presence detection during specified times.

### Settings

**View system health:**
- CPU/memory usage
- Database statistics
- Historical activity

**Edit configuration:**
- Update Wyze credentials
- Change thresholds (HOME/AWAY timing)
- Adjust state machine interval
- Test Wyze API connection

---

## Management

### Service Commands

```bash
# Start/stop/restart
sudo systemctl start wyzeguardi
sudo systemctl stop wyzeguardi
sudo systemctl restart wyzeguardi

# Check status
sudo systemctl status wyzeguardi

# Enable/disable auto-start
sudo systemctl enable wyzeguardi   # Auto-start on boot (default)
sudo systemctl disable wyzeguardi  # Disable auto-start
```

### View Logs

```bash
# Live system logs
sudo journalctl -u wyzeguardi -f

# Last 50 entries
sudo journalctl -u wyzeguardi -n 50

# Today's logs
sudo journalctl -u wyzeguardi --since today

# Application logs
tail -f /opt/wyzeguardi/server.log
```

### Configuration

```bash
# Edit settings
sudo nano /opt/wyzeguardi/.env

# Apply changes
sudo systemctl restart wyzeguardi
```

### Access as wyzeguardi user

```bash
sudo su - wyzeguardi
cd /opt/wyzeguardi
source venv/bin/activate
```

---

## Cron Job (Optional - Additional Reliability)

Add a cron job for redundant health monitoring:

```bash
# Edit root crontab
sudo crontab -e

# Add this line (checks every 5 minutes)
*/5 * * * * su - wyzeguardi -c "/opt/wyzeguardi/start.sh"
```

The `start.sh` script:
- Checks if server is running
- Auto-restarts if crashed
- Logs all actions with timestamps
- Only acts if needed (doesn't duplicate processes)

**When to use:**
- Production environments requiring maximum uptime
- Backup to systemd auto-restart
- Systems with memory issues

---

## Troubleshooting

### Cameras not turning off when home

**Check detection method:**
```bash
# Switch device to arp_3x in Device Manager
# This is the most reliable method
```

**Verify device is online:**
- Check Device Manager - device should show green (online)
- Click "Test" button to verify detection works

**Check service status:**
```bash
sudo systemctl status wyzeguardi
sudo journalctl -u wyzeguardi -n 50
```

### Cameras not turning on when away

**Wait for grace period:**
- Default: 30 minutes after last detection
- Check Dashboard for "GRACE" status

**Check for other devices:**
- Another registered device may still be home
- Review Device Manager for unexpected online devices

**Verify thresholds:**
```bash
sudo nano /opt/wyzeguardi/.env
# Check AWAY_THRESHOLD setting
```

### Service won't start

**Check logs:**
```bash
sudo journalctl -u wyzeguardi -n 50
```

**Common fixes:**
```bash
# Verify Python version (need 3.8+)
python3 --version

# Reinstall dependencies
cd /opt/wyzeguardi
sudo -u wyzeguardi bash -c "source venv/bin/activate && pip install -r requirements.txt"

# Restart service
sudo systemctl restart wyzeguardi
```

### Can't access dashboard

**Check service is running:**
```bash
sudo systemctl status wyzeguardi
```

**Verify port 5000 is open:**
```bash
sudo netstat -tulpn | grep 5000
```

**Try localhost:**
```bash
# From server itself
curl http://localhost:5000/status
```

### Wyze API errors

**Test connection:**
- Settings → Edit Settings → "Test Connection"

**Update credentials:**
- Check email/password are correct
- Verify API Key/ID from https://developer-api-console.wyze.com/
- Ensure API key is active

**Update wyze-sdk:**
```bash
cd /opt/wyzeguardi
sudo -u wyzeguardi bash -c "source venv/bin/activate && pip install --upgrade wyze-sdk"
sudo systemctl restart wyzeguardi
```

### Forgot admin password

```bash
cd /opt/wyzeguardi
sudo -u wyzeguardi python3 reset_password.py
```

---

## Uninstall

### Secure Installation

```bash
# Stop and remove service
sudo systemctl stop wyzeguardi
sudo systemctl disable wyzeguardi
sudo rm /etc/systemd/system/wyzeguardi.service
sudo systemctl daemon-reload

# Optional: Backup database
sudo cp /opt/wyzeguardi/wyze_automation.db ~/wyzeguardi_backup.db

# Remove installation
sudo rm -rf /opt/wyzeguardi

# Remove user
sudo userdel wyzeguardi

# Remove cron job (if added)
sudo crontab -e
# Delete the WyzeGuardi line
```

### Legacy Installation

```bash
# Stop server
pkill -f "python3.*server.py"

# Optional: Backup database
cp ~/WyzeGuardi/wyze_automation.db ~/wyzeguardi_backup.db

# Remove installation
rm -rf ~/WyzeGuardi

# Remove cron job (if added)
crontab -e
# Delete the WyzeGuardi line
```

### Automated Cleanup

```bash
# If cleanup script is available
sudo bash cleanup.sh
```

---

## System Requirements

- **OS:** Debian 10+, Ubuntu 20.04+, Raspberry Pi OS
- **Python:** 3.8 or higher
- **RAM:** 512MB minimum, 1GB recommended
- **Disk:** ~500MB (application + database growth)
- **Network:** Local network access to Wyze cameras and devices
- **Privileges:** Root/sudo access for installation

**Hardware:**
- Raspberry Pi 3/4 (recommended)
- Any Linux server or VM
- Low power consumption (~5W idle)

---

## How It Works

**State Machine (runs every 5 minutes):**

1. **Check manual override** → If active, maintain state and exit

2. **Check presence detection:**
   - Query all registered devices
   - Try detection methods (ARP, ping, heartbeat)
   - If ANY device detected → HOME → Cameras OFF
   - If NO devices detected:
     - ARP modes: AWAY immediately → Cameras ON
     - Ping/heartbeat modes: 
       - Last seen < 30 min → GRACE → No change
       - Last seen > 30 min → AWAY → Cameras ON

3. **Check schedules (if no presence data):**
   - Apply time-based rules
   - Or use default weekday/weekend schedule

4. **Execute state change:**
   - Update cameras via Wyze API
   - Log activity
   - Update dashboard

**Detection speeds:**
- ARP: ~30ms (Layer 2 MAC detection)
- Ping: 3-9 seconds (TCP port scan)
- Heartbeat: Depends on iOS Shortcut interval

---

## Security Best Practices

- ✅ **LAN-only** - Do NOT expose port 5000 to internet
- ✅ **Firewall** - Block external access via router/server firewall
- ✅ **Strong password** - Use complex admin password during registration
- ✅ **File permissions** - Installer sets 600 on sensitive files automatically
- ✅ **HTTPS** - Use reverse proxy (nginx/Caddy) if accessing remotely
- ✅ **Regular updates** - Keep dependencies updated periodically

**Optional: HTTPS with reverse proxy**

Example nginx config:
```nginx
server {
    listen 443 ssl;
    server_name wyze.local;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Support

- **Issues:** https://github.com/Baslocal/WyzeGuardi/issues
- **Discussions:** https://github.com/Baslocal/WyzeGuardi/discussions
- **Documentation:** Check `/Planning` folder for technical details

---

## License

MIT License - see LICENSE file for details

---

## Acknowledgments

- [Wyze SDK](https://github.com/shauntarves/wyze-sdk) - Official Wyze Python library
- Flask, APScheduler, and all open-source dependencies
- Built by an engineer tired of iOS Shortcuts notifications

---

**Made with privacy and local control in mind.**
