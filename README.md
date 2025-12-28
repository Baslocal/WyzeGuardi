# WyzeGuardi

**Intelligent, presence-based Wyze camera automation system**

WyzeGuardi automatically controls your Wyze cameras based on your phone's presence. Cameras turn OFF when you're home, ON when you're away. Simple, private, and runs locally on your hardware.

## Features

### Core Functionality
- **Automatic Presence Detection**: Multiple detection methods (ARP/Layer 2, network ping, heartbeat)
- **Manual Override**: Instant control via web dashboard
- **Custom Schedules**: Time-based camera control with custom rules
- **Multiple Devices**: Track multiple phones, tablets, etc.
- **Privacy-First**: Runs locally on your network - data never leaves your home
- **Easy Setup**: Web-based wizard for first-time configuration
- **Encrypted Storage**: All credentials encrypted at rest

### Security Features
- **CSRF Protection**: Cross-Site Request Forgery protection on all state-changing operations
- **Secure Sessions**: HttpOnly and SameSite cookie flags prevent session hijacking
- **Rate Limiting**: Automatic throttling on webhook endpoints prevents abuse
- **SQL Injection Prevention**: Whitelisted database queries ensure data safety
- **Input Validation**: Sanitized inputs across all user-facing forms

### User Experience
- **Responsive Design**: Modern, mobile-friendly interface
- **Real-time Dashboard**: Auto-refreshing status and activity log
- **Timezone Support**: Automatic timezone handling for schedules and logs
- **Consistent Styling**: Standardized UI components throughout application

## Installation

### Quick Install (Recommended)

```bash
# 1. Install git if needed
sudo apt update
sudo apt install -y git

# 2. Clone repository
git clone https://github.com/Baslocal/Wyze_Guardi.git
cd Wyze_Guardi

# 3. Run automated installer
bash install.sh
```

The installer automatically:
- Installs system dependencies (Python, build tools, etc.)
- Creates virtual environment
- Installs Python packages
- Sets up database
- Tests server startup
- Optionally creates systemd service

### Manual Installation

If you prefer manual setup:

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv build-essential python3-dev libffi-dev libssl-dev

# 2. Clone repository
git clone https://github.com/Baslocal/Wyze_Guardi.git
cd Wyze_Guardi

# 3. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install Python packages
pip install --upgrade pip
pip install -r requirements.txt

# 5. Start server
python3 server.py
```

## First-Time Setup

1. Open browser: `http://localhost:5000` (or use your server's IP)
2. Setup wizard will guide you through configuration:
   - **Wyze Credentials**: Email, password, API key/ID
   - **Timezone**: Your local timezone
   - **Thresholds**: When to consider you home/away
   - **Webhook Secret**: Auto-generated security token
3. **IMPORTANT**: Save the encryption key shown after setup
4. Dashboard is now ready to use

**Get Wyze API Credentials:**
- Visit https://developer-api-console.wyze.com/
- Create an API key and note your API ID

## Presence Detection Setup

WyzeGuardi can detect your presence using multiple methods:

1. **ARP Detection (Recommended)**: Layer 2 MAC address detection - most reliable, no phone setup needed
2. **Network Ping**: Server pings your phone's IP - works automatically
3. **Heartbeat**: iOS Shortcut sends periodic updates - optional for additional reliability

### ARP Detection (Recommended - No Setup Required)

ARP (Address Resolution Protocol) detects your phone at the MAC address level (Layer 2), making it:
- **15x faster** than traditional ping (30ms vs 3-9 seconds)
- **More reliable** - reduces false "away" detections from 20-30% to <2%
- **Zero configuration** - works automatically when phone joins network

Simply register your device in Device Manager with detection method **arp_3x** (tries 3 times for maximum reliability).

### Creating iOS Shortcut (Optional - Additional Reliability)

**Step 1: Create Shortcut**
1. Open **Shortcuts** app
2. Tap **+** to create new shortcut
3. Add action: **Get Contents of URL**
   - URL: `http://<your-server-ip>:5000/heartbeat?token=<WEBHOOK_SECRET>`
   - Method: GET
4. Name it "WyzeGuardi Heartbeat"

**Step 2: Create Automation**
1. Go to **Automation** tab
2. Tap **+** → **Create Personal Automation**
3. Choose: **Time of Day** → Every 10 minutes
4. Add action: **Run Shortcut** → "WyzeGuardi Heartbeat"
5. Disable "Ask Before Running"
6. Save

**How Presence Detection Works:**
- Phone detected (ARP succeeds OR ping succeeds OR heartbeat < 10 min): **HOME** → Cameras OFF
- Grace period (10-30 min since last detection): **No change** (only for ping/heartbeat modes)
- Away confirmed (> 30 min since last detection OR ARP fails): **AWAY** → Cameras ON

**Note:** Pure ARP modes (arp_3x, arp) do NOT use grace period - cameras turn ON immediately when device leaves network.

## Using the Dashboard

### Main Dashboard (`/`)

**Manual Control:**
- **Turn Cameras OFF (2h)**: Override to keep cameras off
- **Turn Cameras ON (2h)**: Override to keep cameras on
- Override expires automatically after duration

**Status Display:**
- Current camera state (on/off)
- Presence status (HOME/AWAY/GRACE)
- Online devices count
- Last heartbeat time
- Manual override expiration

**Activity Log:**
- Recent events (camera changes, heartbeats, errors)
- Auto-refreshes every 30 seconds

### Device Manager (`/devices`)

**Register Devices:**
1. Click "Add Device"
2. Enter device name (e.g., "iPhone", "iPad")
3. Choose detection method:
   - **arp_3x**: ARP with 3 retries (recommended - fastest, most reliable)
   - **arp**: ARP detection (Layer 2 MAC-based)
   - **ping**: Network ping only (Layer 3 IP-based)
   - **heartbeat**: iOS Shortcut only (requires setup)
   - **arp_and_heartbeat**: Combines ARP + heartbeat (maximum reliability)
   - **both**: Network ping + heartbeat (legacy method)
4. Save

**Device Status:**
- Green: Online (detected recently)
- Gray: Offline

### Schedule Manager (`/schedules`)

Create custom time-based schedules:

1. Click "Add Schedule"
2. Configure:
   - Name (e.g., "Weekday Work Hours")
   - Days of week
   - Time range
   - Camera state (on/off)
3. Save

**Examples:**
- Weekday 8am-6pm: Cameras ON (at work)
- Weekend 9am-11pm: Cameras OFF (home all day)
- Night 11pm-7am: Cameras ON (everyone sleeping)

### Settings (`/settings`)

**View:**
- System health metrics
- Historical statistics
- Database info
- Current configuration

**Edit Settings:**
- Update Wyze credentials
- Change thresholds (HOME/AWAY timing)
- Adjust state machine interval
- Test API connection

## Configuration

### Presence Detection Settings

**HOME_THRESHOLD** (default: 10 minutes)
- How recent heartbeat must be to consider device online
- Increase if iOS Shortcut runs infrequently
- Example: Set to 15 min if Shortcut runs every 10 min

**AWAY_THRESHOLD** (default: 30 minutes)
- Grace period before confirming you're away
- Prevents cameras turning ON during brief WiFi drops
- Increase for more tolerance, decrease for faster response

**STATE_MACHINE_INTERVAL** (default: 5 minutes)
- How often system checks presence and updates cameras
- Lower = faster response, higher = less frequent API calls

**Configure via:** Settings → Edit Settings

### Detection Methods (Per Device)

- **arp_3x**: ARP detection with 3 retries (~30ms, recommended for most devices)
- **arp**: Single ARP check (fastest but may miss device during network transitions)
- **ping**: Network ping via TCP ports (3-9s, works if phone allows connections)
- **heartbeat**: iOS Shortcut only (requires setup, user must trigger periodically)
- **arp_and_heartbeat**: Combines ARP + heartbeat (maximum reliability, no grace period)
- **both**: Network ping + heartbeat (legacy, slower than ARP methods)

**Recommendations:**
- **iPhone/iPad**: Use **arp_3x** (no setup, most reliable)
- **Android**: Use **arp_3x** (works with all Android devices)
- **If ARP fails**: Fall back to **both** or **arp_and_heartbeat** with iOS Shortcut

**Configure via:** Device Manager → Edit device

## Running as Service

The installer can create a systemd service for auto-start:

```bash
# Service management
sudo systemctl status wyzeguardi    # Check status
sudo systemctl restart wyzeguardi   # Restart
sudo systemctl stop wyzeguardi      # Stop
sudo systemctl start wyzeguardi     # Start

# View logs
sudo journalctl -u wyzeguardi -f    # Live logs
sudo journalctl -u wyzeguardi -n 50 # Last 50 lines
```

## Troubleshooting

### Cameras Not Turning Off When Home

**Possible Causes:**
1. **Detection method unreliable** - Ping or heartbeat may be failing
2. **Network ping blocked** - iPhone may block ping ports in Low Power Mode
3. **Schedule override** - Active schedule may be controlling cameras
4. **Device not registered** - Device not added to Device Manager

**Solutions:**
- **Switch to ARP detection** - Change device to **arp_3x** method (most reliable)
- Check Device Manager - is your device showing as online?
- Use Test button on device to verify detection is working
- If using heartbeat: manually trigger iOS Shortcut to test
- Check Settings → thresholds (HOME_THRESHOLD may be too short)

### Cameras Not Turning On When Away

**Possible Causes:**
1. **Still in grace period** - Default 30 min wait before confirming away
2. **Other device online** - Another registered device still home
3. **Manual override active** - Check dashboard for override status

**Solutions:**
- Wait for grace period to expire (check Dashboard for timing)
- Check Device Manager - disable devices that shouldn't trigger presence
- Reduce AWAY_THRESHOLD in Settings for faster response

### Heartbeats Not Received

**Check:**
1. iOS Shortcut URL correct (including token and IP)
2. iPhone on same network as server
3. Shortcut automation enabled and running
4. Check Logs page for heartbeat entries

**Test:**
- Manually run Shortcut from Shortcuts app
- Check Dashboard - "Last heartbeat" should update immediately
- If working: automation trigger issue, check iOS Settings

### Service Won't Start

```bash
# Check logs for error
sudo journalctl -u wyzeguardi -n 50

# Common issues:
# - Database locked: Kill any running python3 server.py processes
# - Missing dependencies: Reinstall with bash install.sh
# - Permission error: Check file ownership in install directory
```

### Wyze API Errors

**"Failed to initialize Wyze client"**
- Check credentials in Settings → Edit Settings
- Click "Test Connection" to verify API key/ID
- Ensure API key is active at https://developer-api-console.wyze.com/

**"Client.__init__() got unexpected keyword argument"**
- wyze-sdk version too old
- Update: `pip install --upgrade wyze-sdk==2.2.0`

## Security Best Practices

- **LAN-only**: Do NOT expose port 5000 to internet
- **Firewall**: Block external access via router or server firewall
- **Strong webhook secret**: Use 32+ random characters (auto-generated)
- **File permissions**: Keep .env and .db_key files private (chmod 600)
- **Regular updates**: Update dependencies periodically

### Optional: HTTPS Access

Use nginx or Caddy as reverse proxy for HTTPS:

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

## System Requirements

- **Hardware**: Raspberry Pi 3/4 or any Linux server (512MB+ RAM)
- **OS**: Debian 10+, Ubuntu 20.04+, Raspberry Pi OS
- **Python**: 3.8 or higher
- **Network**: Local network access to Wyze cameras and devices
- **Disk**: ~100MB for application + database (~10MB/month growth)

## API Reference

All endpoints return JSON (except HTML pages).

### Control
- `GET /manual/on` - Turn cameras ON (2h override)
- `GET /manual/off` - Turn cameras OFF (2h override)
- `GET /heartbeat?token=SECRET` - Receive heartbeat (for devices)

### Status
- `GET /status` - Health check (returns "OK" or "DEGRADED")
- `GET /api/state` - Current system state
- `GET /api/cameras` - Camera list with states
- `GET /api/health/database` - Database health
- `GET /api/health/wyze` - Wyze API health
- `GET /api/health/system` - System resources (CPU, memory)

## How It Works

**State Machine (runs every 5 minutes):**

1. **Check Manual Override**
   - If active: maintain current state, exit

2. **Check Presence Detection**
   - Get all enabled devices
   - For each device:
     - If detection method includes "arp": Try ARP detection (ping + arp -a command, ~30ms)
     - If detection method includes "ping": Try network ping (TCP ports 62078, 5353, 3689, 3-9s)
     - If detection method includes "heartbeat": Check last_seen timestamp
   - If any device online: HOME → Cameras OFF
   - If no devices online:
     - For ARP-only modes (arp, arp_3x): AWAY → Cameras ON immediately (no grace period)
     - For ping/heartbeat modes:
       - If last seen < 30 min ago: GRACE → No change
       - If last seen > 30 min ago: AWAY → Cameras ON

3. **Check Schedules (if no presence data)**
   - Check custom schedules for current time
   - Or use default weekday/weekend schedule
   - Apply scheduled camera state

4. **Execute State Change**
   - If desired state != current state: Update cameras via Wyze API
   - Log to activity log
   - Update dashboard

## License

MIT License - see LICENSE file for details

## Support

- **Issues**: https://github.com/Baslocal/Wyze_Guardi/issues
- **Discussions**: https://github.com/Baslocal/Wyze_Guardi/discussions

## Acknowledgments

- [Wyze SDK](https://github.com/shauntarves/wyze-sdk) - Official Wyze Python library
- Flask, APScheduler, and all open-source dependencies

## Roadmap

Future enhancements under consideration:

### Security Improvements
- **Password Strength Validation**: Enforce strong passwords with complexity requirements and common password checking
- **Environment Variables**: Move sensitive configuration to environment variables for better secrets management
- **Security Headers**: Add Content-Security-Policy, X-Frame-Options, and other security headers
- **Enhanced Input Sanitization**: Additional validation layers for device names and user inputs

### Code Quality
- **Comprehensive Documentation**: Docstrings for all functions with parameter and return type documentation
- **Type Hints**: Full type annotation coverage for improved IDE support and error detection
- **Unit Test Coverage**: Automated test suite for critical functionality
- **Logging Improvements**: Standardized logging levels and enhanced security event logging

### User Experience
- **Error Handling**: Improved error messages and graceful degradation for API failures
- **Timezone Consistency**: Centralized timezone configuration across all components
- **Template Optimization**: Reduced code duplication through reusable components

### Developer Experience
- **Constants Management**: Extracted magic numbers and strings to configuration
- **Code Refactoring**: Improved maintainability through better separation of concerns

**Note**: Roadmap items are prioritized based on user feedback and security considerations. Contributions welcome!

---

**Made with privacy and local control in mind.**
