#!/bin/bash
#
# WyzeGuardi Installation Script
# ===============================
# Automated installation with error handling and validation
#
# Usage:
#   bash install.sh
#
# This script will:
#   1. Check system requirements
#   2. Install Python dependencies
#   3. Initialize the database
#   4. Create systemd service (optional)
#   5. Start the application
#

set +e  # Continue on error, show all issues

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
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

# Error handler - prints error but doesn't exit
error_exit() {
    print_error "$1"
    echo ""
    print_info "This component failed. Continuing to check other requirements..."
    return 1
}

# Check if running as root
check_root() {
    if [ "$EUID" -eq 0 ]; then
        print_warning "Running as root. This is not recommended for security reasons."
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installation cancelled by user"
            return 1
        fi
    fi
}

# Install system dependencies
install_system_dependencies() {
    print_header "Installing System Dependencies"

    MISSING_PACKAGES=()

    # Check for pip3
    if ! command -v pip3 &> /dev/null; then
        MISSING_PACKAGES+=("python3-pip")
        print_info "Missing: python3-pip"
    fi

    # Check for gcc/build tools
    if ! command -v gcc &> /dev/null; then
        MISSING_PACKAGES+=("build-essential")
        print_info "Missing: build-essential"
    fi

    # Check for python3-dev
    if ! dpkg -s python3-dev &> /dev/null 2>&1; then
        MISSING_PACKAGES+=("python3-dev")
        print_info "Missing: python3-dev"
    fi

    # Check for python3-venv (CRITICAL)
    if ! dpkg -s python3-venv &> /dev/null 2>&1; then
        MISSING_PACKAGES+=("python3-venv")
        print_info "Missing: python3-venv"
    fi

    # Check for libffi-dev
    if ! dpkg -s libffi-dev &> /dev/null 2>&1; then
        MISSING_PACKAGES+=("libffi-dev")
        print_info "Missing: libffi-dev"
    fi

    # Check for libssl-dev
    if ! dpkg -s libssl-dev &> /dev/null 2>&1; then
        MISSING_PACKAGES+=("libssl-dev")
        print_info "Missing: libssl-dev"
    fi

    # Install missing packages
    if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
        print_info "Installing missing packages: ${MISSING_PACKAGES[*]}"

        # Update package lists
        print_info "Updating package lists..."
        if ! sudo apt update -qq; then
            print_error "Failed to update package lists"
            return 1
        fi

        # Install packages
        print_info "Installing packages (this may take a few minutes)..."
        if ! sudo apt install -y "${MISSING_PACKAGES[@]}"; then
            print_error "Failed to install system packages"
            print_info "Try manually: sudo apt install -y ${MISSING_PACKAGES[*]}"
            return 1
        fi

        print_success "System dependencies installed successfully"
    else
        print_success "All system dependencies already installed"
    fi

    echo ""
}

# Check system requirements
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

    # Check pip
    if ! command -v pip3 &> /dev/null; then
        error_exit "pip3 is not installed. Please install pip3 first."
    fi
    print_success "pip3 found"

    # Check git (optional but recommended)
    if ! command -v git &> /dev/null; then
        print_warning "git is not installed. Recommended for updates."
    else
        print_success "git found"
    fi

    # Check available disk space (minimum 100MB)
    AVAILABLE_SPACE=$(df -BM . | awk 'NR==2 {print $4}' | sed 's/M//')
    if [ "$AVAILABLE_SPACE" -lt 100 ]; then
        error_exit "Not enough disk space. Need at least 100MB, have ${AVAILABLE_SPACE}MB"
    fi
    print_success "Sufficient disk space available (${AVAILABLE_SPACE}MB)"

    echo ""
}

# Create virtual environment
create_venv() {
    print_header "Setting Up Virtual Environment"

    if [ -d "venv" ]; then
        print_warning "Virtual environment already exists"
        read -p "Recreate it? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Removing old virtual environment..."
            rm -rf venv
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi

    print_info "Creating virtual environment..."
    python3 -m venv venv || error_exit "Failed to create virtual environment"
    print_success "Virtual environment created"

    echo ""
}

# Install dependencies
install_dependencies() {
    print_header "Installing Dependencies"

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
    python3 -c "import cryptography" || error_exit "cryptography not installed correctly"

    # Verify wyze-sdk version (must be >= 2.0.0 for API key support)
    WYZE_VERSION=$(python3 -c "import wyze_sdk; print(wyze_sdk.__version__)" 2>/dev/null || echo "0.0.0")
    WYZE_MAJOR=$(echo $WYZE_VERSION | cut -d. -f1)
    WYZE_MINOR=$(echo $WYZE_VERSION | cut -d. -f2)

    if [ "$WYZE_MAJOR" -lt 2 ]; then
        print_error "wyze-sdk version $WYZE_VERSION is too old (need >= 2.0.0)"
        print_info "Try: pip install --upgrade wyze-sdk==2.2.0"
        return 1
    fi
    print_success "wyze-sdk $WYZE_VERSION installed (API key support confirmed)"

    # Verify pycryptodomex (Cryptodome namespace)
    if ! python3 -c "from Cryptodome.Cipher import AES" 2>/dev/null; then
        print_error "pycryptodomex not installed correctly (Cryptodome namespace missing)"
        print_info "Try: pip install pycryptodomex==3.21.0"
        return 1
    fi
    print_success "pycryptodomex installed correctly (Cryptodome namespace available)"

    print_success "All packages verified"

    echo ""
}

# Initialize database
init_database() {
    print_header "Initializing Database"

    # Check if database exists
    if [ -f "wyze_automation.db" ]; then
        print_warning "Database already exists"
        read -p "Backup and reinitialize? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            BACKUP_FILE="wyze_automation.db.backup.$(date +%Y%m%d_%H%M%S)"
            print_info "Backing up to $BACKUP_FILE..."
            cp wyze_automation.db "$BACKUP_FILE"
            print_success "Database backed up"
            rm wyze_automation.db
        else
            print_info "Keeping existing database"
            return 0
        fi
    fi

    # Prepare database module
    print_info "Preparing database module..."
    if ! python3 -c "import database" 2>/dev/null; then
        print_error "Failed to load database module"
        return 1
    fi

    print_success "Database module ready (file will be created on first server run)"
    print_info "Note: SQLite creates wyze_automation.db automatically on first connection"

    echo ""
}

# Configure environment
configure_env() {
    print_header "Environment Configuration"

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

    print_success ".env file created"
    print_info "Edit .env to customize settings"

    echo ""
}

# Test server startup
test_server() {
    print_header "Testing Server Startup"

    print_info "Starting server in test mode..."

    # Start server in background
    source venv/bin/activate
    timeout 10 python3 server.py > test_server.log 2>&1 &
    SERVER_PID=$!

    # Wait for server to start
    sleep 3

    # Check if server is running
    if ! ps -p $SERVER_PID > /dev/null 2>&1; then
        print_error "Server failed to start"
        print_info "Check test_server.log for details:"
        tail -20 test_server.log
        rm -f test_server.log
        error_exit "Server startup failed"
    fi

    # Test HTTP endpoint
    if command -v curl &> /dev/null; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/status)
        if [ "$HTTP_CODE" -eq 200 ]; then
            print_success "Server responded successfully (HTTP $HTTP_CODE)"
        else
            print_warning "Server responded with HTTP $HTTP_CODE"
        fi
    fi

    # Stop test server
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    rm -f test_server.log

    print_success "Server test completed"

    echo ""
}

# Create systemd service
create_service() {
    print_header "Systemd Service Setup (Optional)"

    print_info "This will create a systemd service to run WyzeGuardi automatically"
    read -p "Create systemd service? (y/n) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Skipping systemd service creation"
        return 0
    fi

    # Check if systemd is available
    if ! command -v systemctl &> /dev/null; then
        print_warning "systemd not available on this system"
        return 0
    fi

    # Get absolute path
    INSTALL_DIR=$(pwd)
    USER=$(whoami)

    # Create service file
    SERVICE_FILE="/tmp/wyze-automation.service"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=WyzeGuardi - Smart Camera Automation
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    print_info "Service file created at $SERVICE_FILE"
    print_warning "You need root privileges to install the service"
    echo ""
    echo "Run these commands to install and start the service:"
    echo ""
    echo "  sudo cp $SERVICE_FILE /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable wyze-automation"
    echo "  sudo systemctl start wyze-automation"
    echo "  sudo systemctl status wyze-automation"
    echo ""

    echo ""
}

# Print final instructions
print_instructions() {
    print_header "Installation Complete!"

    echo ""
    print_success "WyzeGuardi has been installed successfully"
    echo ""
    print_info "Next Steps:"
    echo ""
    echo "  1. Start the server:"
    echo "     ./start.sh"
    echo "     (or manually: source venv/bin/activate && python3 server.py)"
    echo ""
    echo "  2. Open your browser and navigate to:"
    echo "     http://localhost:5000"
    echo "     (or http://YOUR_SERVER_IP:5000 from another device)"
    echo ""
    echo "  3. Complete the setup wizard:"
    echo "     - Enter your Wyze credentials"
    echo "     - Get API key/ID from: https://developer-api-console.wyze.com"
    echo "     - Configure thresholds and preferences"
    echo ""
    echo "  4. Set up iOS Shortcut for heartbeat:"
    echo "     - See: Planning/04_IOS_SHORTCUT_SETUP.md"
    echo ""
    print_info "Documentation:"
    echo "     - Codebase Analysis: Planning/01_CODEBASE_ANALYSIS.md"
    echo "     - Session Issues:    Planning/02_SESSION_ISSUES.md"
    echo "     - Installation:      Planning/03_INSTALLATION_GUIDE.md"
    echo "     - Database Schema:   Planning/04_DATABASE_SCHEMA.md"
    echo ""
    print_info "Logs:"
    echo "     - Application: app.log"
    echo "     - Server:      server.log (if running in background)"
    echo ""
    print_info "Need help?"
    echo "     - Check the documentation in the Planning/ folder"
    echo "     - Review logs for errors"
    echo "     - Check GitHub issues"
    echo ""
}

# Create start script
create_start_script() {
    print_header "Creating Start Script"

    cat > start.sh << 'EOF'
#!/bin/bash
# WyzeGuardi Start Script

echo "Starting WyzeGuardi..."

# Activate virtual environment
source venv/bin/activate

# Start server
python3 server.py
EOF

    chmod +x start.sh
    print_success "Created start.sh script"

    echo ""
}

# Main installation flow
main() {
    echo ""
    print_header "WyzeGuardi Installation"
    echo ""
    print_info "This script will install and configure WyzeGuardi"
    print_info "Installation directory: $(pwd)"
    echo ""

    # Confirm installation
    read -p "Continue with installation? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled by user"
        return 0
    fi

    echo ""

    # Run installation steps
    check_root
    install_system_dependencies
    check_requirements
    create_venv
    install_dependencies
    init_database
    configure_env
    create_start_script
    test_server
    create_service
    print_instructions

    echo ""
    print_success "Installation script completed successfully!"
    echo ""
}

# Run main function
main
