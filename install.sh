#!/bin/bash
#
# WyzeGuardi Secure Installation Script
# ======================================
# Installs WyzeGuardi with dedicated user, proper permissions, and systemd service
#
# Usage:
#   sudo bash install.sh
#
# This script will:
#   1. Check system requirements
#   2. Create dedicated 'wyzeguardi' user
#   3. Install to /opt/wyzeguardi
#   4. Install Python dependencies
#   5. Set proper permissions and security
#   6. Create systemd service
#   7. Initialize database
#   8. Start the application
#

set +e  # Continue on error to show all issues

# ============================================================================
# Configuration
# ============================================================================

INSTALL_USER="wyzeguardi"
INSTALL_DIR="/opt/wyzeguardi"
SERVICE_NAME="wyzeguardi"
CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Print Functions
# ============================================================================

print_header() {
    echo -e "${BLUE}================================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}================================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# ============================================================================
# Error Handler
# ============================================================================

error_exit() {
    print_error "$1"
    echo ""
    print_info "Installation failed. Check errors above."
    exit 1
}

# ============================================================================
# Check Root Privileges
# ============================================================================

check_root() {
    print_header "Checking Privileges"
    
    if [ "$EUID" -ne 0 ]; then
        error_exit "This script must be run as root. Use: sudo bash install.sh"
    fi
    
    print_success "Running with root privileges"
    echo ""
}

# ============================================================================
# Check System Requirements
# ============================================================================

check_requirements() {
    print_header "Checking System Requirements"

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        error_exit "Python 3 is not installed. Please install Python 3.8 or higher."
    fi

    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        error_exit "Python 3.8 or higher is required. Found: $PYTHON_VERSION"
    fi
    print_success "Python $PYTHON_VERSION found"

    # Check available disk space (minimum 500MB)
    AVAILABLE_SPACE=$(df -BM /opt 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/M//')
    if [ -z "$AVAILABLE_SPACE" ]; then
        AVAILABLE_SPACE=$(df -BM / | awk 'NR==2 {print $4}' | sed 's/M//')
    fi
    
    if [ "$AVAILABLE_SPACE" -lt 500 ]; then
        error_exit "Not enough disk space in /opt. Need at least 500MB, have ${AVAILABLE_SPACE}MB"
    fi
    print_success "Sufficient disk space available (${AVAILABLE_SPACE}MB)"

    # Check systemd
    if ! command -v systemctl &> /dev/null; then
        print_warning "systemd not found - service installation will be skipped"
    else
        print_success "systemd found"
    fi

    echo ""
}

# ============================================================================
# Install System Dependencies
# ============================================================================

install_system_dependencies() {
    print_header "Installing System Dependencies"

    MISSING_PACKAGES=()

    # Check for required packages
    for pkg in python3-pip python3-venv build-essential python3-dev libffi-dev libssl-dev; do
        if ! dpkg -s "$pkg" &> /dev/null 2>&1; then
            MISSING_PACKAGES+=("$pkg")
        fi
    done

    if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
        print_info "Installing missing packages: ${MISSING_PACKAGES[*]}"
        
        apt update -qq || error_exit "Failed to update package lists"
        apt install -y "${MISSING_PACKAGES[@]}" || error_exit "Failed to install system packages"
        
        print_success "System dependencies installed"
    else
        print_success "All system dependencies already installed"
    fi

    echo ""
}

# ============================================================================
# Create Dedicated User
# ============================================================================

create_user() {
    print_header "Creating Dedicated User"

    if id "$INSTALL_USER" &>/dev/null; then
        print_warning "User '$INSTALL_USER' already exists"
        read -p "Continue with existing user? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error_exit "Installation cancelled by user"
        fi
    else
        print_info "Creating system user: $INSTALL_USER"
        useradd -r -m -d "$INSTALL_DIR" -s /bin/bash "$INSTALL_USER" || error_exit "Failed to create user"
        print_success "User '$INSTALL_USER' created"
    fi

    echo ""
}

# ============================================================================
# Create Installation Directory
# ============================================================================

create_install_dir() {
    print_header "Creating Installation Directory"

    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory $INSTALL_DIR already exists"
        read -p "Overwrite existing installation? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Backing up existing installation..."
            BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
            mv "$INSTALL_DIR" "$BACKUP_DIR"
            print_success "Backup created: $BACKUP_DIR"
        else
            print_info "Using existing directory"
            return 0
        fi
    fi

    print_info "Creating directory: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR" || error_exit "Failed to create directory"
    print_success "Installation directory created"

    echo ""
}

# ============================================================================
# Copy Application Files
# ============================================================================

copy_files() {
    print_header "Copying Application Files"

    print_info "Copying files from $CURRENT_DIR to $INSTALL_DIR"
    
    # Copy all files except venv, __pycache__, *.pyc, .git
    if command -v rsync &> /dev/null; then
        rsync -av \
            --exclude='venv' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='.git' \
            --exclude='*.backup.*' \
            "$CURRENT_DIR/" "$INSTALL_DIR/" || error_exit "Failed to copy files"
    else
        # Fallback to cp if rsync not available
        cp -r "$CURRENT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$CURRENT_DIR"/.[^.]* "$INSTALL_DIR/" 2>/dev/null || true
    fi
    
    print_success "Application files copied"

    echo ""
}

# ============================================================================
# Create Virtual Environment
# ============================================================================

create_venv() {
    print_header "Setting Up Virtual Environment"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    if [ -d "venv" ]; then
        print_warning "Virtual environment already exists"
        rm -rf venv
    fi

    print_info "Creating virtual environment..."
    python3 -m venv venv || error_exit "Failed to create virtual environment"
    print_success "Virtual environment created"

    echo ""
}

# ============================================================================
# Install Python Dependencies
# ============================================================================

install_dependencies() {
    print_header "Installing Python Dependencies"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    # Activate virtual environment
    source venv/bin/activate || error_exit "Failed to activate virtual environment"

    # Upgrade pip
    print_info "Upgrading pip..."
    pip install --upgrade pip > /dev/null 2>&1 || error_exit "Failed to upgrade pip"
    print_success "pip upgraded"

    # Install requirements
    if [ ! -f "requirements.txt" ]; then
        error_exit "requirements.txt not found"
    fi

    print_info "Installing Python packages (this may take a few minutes)..."
    pip install -r requirements.txt || error_exit "Failed to install dependencies"
    print_success "All dependencies installed"

    # Verify critical packages
    print_info "Verifying installations..."
    python3 -c "import flask" || error_exit "Flask not installed correctly"
    python3 -c "import apscheduler" || error_exit "APScheduler not installed correctly"
    python3 -c "import wyze_sdk" || error_exit "wyze-sdk not installed correctly"
    
    # Verify wyze-sdk version
    WYZE_VERSION=$(python3 -c "import wyze_sdk; print(wyze_sdk.__version__)" 2>/dev/null || echo "0.0.0")
    print_success "wyze-sdk $WYZE_VERSION installed"

    echo ""
}

# ============================================================================
# Set Permissions
# ============================================================================

set_permissions() {
    print_header "Setting Permissions"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    print_info "Setting ownership to $INSTALL_USER:$INSTALL_USER"
    chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR" || error_exit "Failed to set ownership"

    print_info "Setting directory permissions..."
    find "$INSTALL_DIR" -type d -exec chmod 755 {} \;
    
    print_info "Setting file permissions..."
    find "$INSTALL_DIR" -type f -exec chmod 644 {} \;
    
    print_info "Setting executable permissions..."
    chmod 755 "$INSTALL_DIR"/venv/bin/* 2>/dev/null || true
    
    # Create start.sh if it doesn't exist
    if [ ! -f "start.sh" ]; then
        print_info "Creating start.sh script..."
        create_start_script
    fi
    chmod 755 "$INSTALL_DIR/start.sh"

    # Protect sensitive files
    print_info "Securing sensitive files..."
    if [ -f ".env" ]; then
        chmod 600 .env
        print_success "Secured .env file (600)"
    fi
    
    if [ -f "wyze_automation.db" ]; then
        chmod 600 wyze_automation.db
        print_success "Secured database file (600)"
    fi
    
    if [ -f ".db_key" ]; then
        chmod 600 .db_key
        print_success "Secured encryption key (600)"
    fi

    print_success "Permissions set successfully"

    echo ""
}

# ============================================================================
# Create Start Script
# ============================================================================

create_start_script() {
    cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
#
# WyzeGuardi Start Script
# Properly backgrounds the server for cron/manual use
#

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$INSTALL_DIR/server.log"
PID_FILE="$INSTALL_DIR/server.pid"

cd "$INSTALL_DIR" || exit 1

# Check if server already running
if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server already running (PID: $(cat $PID_FILE))" >> "$LOG_FILE"
    exit 0
fi

# Double-check with pgrep
if pgrep -f "python3.*server.py" > /dev/null; then
    EXISTING_PID=$(pgrep -f "python3.*server.py")
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server already running (PID: $EXISTING_PID)" >> "$LOG_FILE"
    echo "$EXISTING_PID" > "$PID_FILE"
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting WyzeGuardi server..." >> "$LOG_FILE"

# Activate virtual environment
source venv/bin/activate || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cannot activate venv" >> "$LOG_FILE"
    exit 1
}

# Start server in background with nohup
nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Save PID
echo "$SERVER_PID" > "$PID_FILE"

# Wait and verify startup
sleep 3

if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server started successfully (PID: $SERVER_PID)" >> "$LOG_FILE"
    exit 0
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Server failed to start" >> "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
EOF
}

# ============================================================================
# Configure Environment
# ============================================================================

configure_env() {
    print_header "Configuring Environment"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    if [ -f ".env" ]; then
        print_warning ".env file already exists"
        read -p "Overwrite with defaults? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing .env file"
            return 0
        fi
    fi

    print_info "Creating .env file with defaults..."
    cat > .env << 'EOF'
# Flask Configuration
FLASK_PORT=5000
FLASK_HOST=0.0.0.0

# Timezone (use your local timezone)
TZ=America/New_York

# Logging
LOG_LEVEL=INFO
LOG_FILE=app.log

# Thresholds (minutes)
HOME_THRESHOLD=10
AWAY_THRESHOLD=30
MANUAL_OVERRIDE_DURATION=2

# State Machine
STATE_MACHINE_INTERVAL=5

# Schedule defaults (hours, 0-23)
WEEKDAY_HOME_START=8
WEEKDAY_HOME_END=18
WEEKEND_HOME_START=9
WEEKEND_HOME_END=23
EOF

    chmod 600 .env
    chown "$INSTALL_USER:$INSTALL_USER" .env
    
    print_success ".env file created and secured"
    print_info "Edit $INSTALL_DIR/.env to customize settings"

    echo ""
}

# ============================================================================
# Create Systemd Service
# ============================================================================

create_systemd_service() {
    print_header "Creating Systemd Service"

    if ! command -v systemctl &> /dev/null; then
        print_warning "systemd not available - skipping service creation"
        return 0
    fi

    print_info "Creating systemd service: $SERVICE_NAME"

    cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=WyzeGuardi - Smart Camera Automation
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/server.py
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

    print_success "Service file created"

    # Reload systemd
    systemctl daemon-reload || error_exit "Failed to reload systemd"
    print_success "systemd reloaded"

    # Enable service
    print_info "Enabling service to start on boot..."
    systemctl enable "$SERVICE_NAME" || error_exit "Failed to enable service"
    print_success "Service enabled"

    echo ""
}

# ============================================================================
# Initialize Database
# ============================================================================

init_database() {
    print_header "Initializing Database"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    if [ -f "wyze_automation.db" ]; then
        print_warning "Database already exists"
        read -p "Keep existing database? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing database"
            return 0
        else
            BACKUP_FILE="wyze_automation.db.backup.$(date +%Y%m%d_%H%M%S)"
            print_info "Backing up to $BACKUP_FILE..."
            cp wyze_automation.db "$BACKUP_FILE"
            chown "$INSTALL_USER:$INSTALL_USER" "$BACKUP_FILE"
            print_success "Database backed up"
        fi
    fi

    print_success "Database will be created on first server startup"

    echo ""
}

# ============================================================================
# Test Installation
# ============================================================================

test_installation() {
    print_header "Testing Installation"

    cd "$INSTALL_DIR" || error_exit "Cannot access $INSTALL_DIR"

    print_info "Starting server as $INSTALL_USER (test mode)..."

    # Run as wyzeguardi user with timeout
    su - "$INSTALL_USER" -c "cd $INSTALL_DIR && source venv/bin/activate && timeout 10 python3 server.py > /tmp/wyzeguardi_test.log 2>&1 &"
    
    sleep 5

    # Check if server started
    if pgrep -u "$INSTALL_USER" -f "python3.*server.py" > /dev/null; then
        print_success "Server test successful"
        
        # Stop test server
        pkill -u "$INSTALL_USER" -f "python3.*server.py"
        
        rm -f /tmp/wyzeguardi_test.log
    else
        print_error "Server test failed"
        print_info "Check logs: cat /tmp/wyzeguardi_test.log"
    fi

    echo ""
}

# ============================================================================
# Print Final Instructions
# ============================================================================

print_instructions() {
    print_header "Installation Complete!"

    # Get host IP address dynamically
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    
    echo ""
    print_success "WyzeGuardi has been installed successfully"
    echo ""
    print_info "Installation Details:"
    echo "  Location:      $INSTALL_DIR"
    echo "  User:          $INSTALL_USER"
    echo "  Service:       $SERVICE_NAME"
    echo "  Source Dir:    $CURRENT_DIR"
    echo ""
    
    print_header "IMPORTANT: First-Time Setup Required"
    echo ""
    print_warning "Before you can use WyzeGuardi, you MUST create an admin account"
    echo ""
    print_info "Step 1: Start the service"
    echo "  sudo systemctl start $SERVICE_NAME"
    echo ""
    print_info "Step 2: Register your account at:"
    echo "  http://localhost:5000/register"
    if [ -n "$HOST_IP" ]; then
        echo "  http://${HOST_IP}:5000/register  (from other devices)"
    fi
    echo ""
    print_info "Step 3: After registration, access dashboard at:"
    echo "  http://localhost:5000"
    if [ -n "$HOST_IP" ]; then
        echo "  http://${HOST_IP}:5000  (from other devices)"
    fi
    echo ""
    
    print_header "Clean Up Source Directory"
    echo ""
    print_info "The application has been copied to $INSTALL_DIR"
    print_info "After confirming the service works, you can remove the source:"
    echo ""
    echo "  cd ~"
    echo "  rm -rf $CURRENT_DIR"
    echo ""
    print_warning "Only delete AFTER verifying the service starts successfully!"
    echo ""
    
    print_header "Quick Start Commands"
    echo ""
    echo "# 1. Start the service"
    echo "sudo systemctl start $SERVICE_NAME"
    echo ""
    echo "# 2. Check service status"
    echo "sudo systemctl status $SERVICE_NAME"
    echo ""
    echo "# 3. View live logs"
    echo "sudo journalctl -u $SERVICE_NAME -f"
    echo ""
    echo "# 4. Register admin account (in browser)"
    if [ -n "$HOST_IP" ]; then
        echo "http://${HOST_IP}:5000/register"
    else
        echo "http://localhost:5000/register"
    fi
    echo ""
    echo "# 5. Clean up source directory (after verification)"
    echo "cd ~ && rm -rf $CURRENT_DIR"
    echo ""
    
    print_header "Service Management"
    echo ""
    echo "  sudo systemctl start $SERVICE_NAME     # Start service"
    echo "  sudo systemctl stop $SERVICE_NAME      # Stop service"
    echo "  sudo systemctl restart $SERVICE_NAME   # Restart service"
    echo "  sudo systemctl status $SERVICE_NAME    # Check status"
    echo "  sudo journalctl -u $SERVICE_NAME -f    # View live logs"
    echo ""
    
    print_header "Configuration"
    echo ""
    echo "Edit application settings:"
    echo "  sudo nano $INSTALL_DIR/.env"
    echo "  sudo systemctl restart $SERVICE_NAME  # Apply changes"
    echo ""
    echo "Access as wyzeguardi user:"
    echo "  sudo su - $INSTALL_USER"
    echo ""
    
    print_header "Next Steps"
    echo ""
    echo "1. Start service:       sudo systemctl start $SERVICE_NAME"
    echo "2. Verify status:       sudo systemctl status $SERVICE_NAME"
    if [ -n "$HOST_IP" ]; then
        echo "3. Register account:    http://${HOST_IP}:5000/register"
    else
        echo "3. Register account:    http://localhost:5000/register"
    fi
    echo "4. Get Wyze API creds:  https://developer-api-console.wyze.com/"
    echo "5. Add devices:         Navigate to Device Manager"
    echo "6. Clean up source:     cd ~ && rm -rf $CURRENT_DIR"
    echo ""
    
    print_header "Security Reminders"
    echo ""
    print_warning "Important Security Notes:"
    echo "  • Application runs as '$INSTALL_USER' user (non-root)"
    echo "  • Sensitive files protected with 600 permissions"
    echo "  • Service includes security hardening (NoNewPrivileges, ProtectSystem)"
    echo "  • Do NOT expose port 5000 to internet without HTTPS proxy"
    echo "  • Use a strong password during registration"
    echo "  • Keep Wyze API credentials secure"
    echo ""
}

# ============================================================================
# Main Installation Flow
# ============================================================================

main() {
    echo ""
    print_header "WyzeGuardi Secure Installation"
    echo ""
    print_info "This will install WyzeGuardi with:"
    echo "  • Dedicated user: $INSTALL_USER (non-admin)"
    echo "  • Installation directory: $INSTALL_DIR"
    echo "  • Systemd service: $SERVICE_NAME"
    echo "  • Security hardening enabled"
    echo "  • Auto-start on boot"
    echo ""
    print_warning "Why a dedicated user?"
    echo "  - Prevents privilege escalation attacks"
    echo "  - Isolates application from system files"
    echo "  - Follows principle of least privilege"
    echo "  - Industry standard security practice"
    echo ""
    
    read -p "Continue with installation? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled by user"
        exit 0
    fi

    echo ""

    # Run installation steps
    check_root
    check_requirements
    install_system_dependencies
    create_user
    create_install_dir
    copy_files
    create_venv
    install_dependencies
    set_permissions
    configure_env
    create_systemd_service
    init_database
    test_installation
    print_instructions

    echo ""
    print_success "Installation completed successfully!"
    echo ""
    print_info "Start WyzeGuardi now:"
    echo "  sudo systemctl start $SERVICE_NAME"
    echo ""
}

# Run main function
main
