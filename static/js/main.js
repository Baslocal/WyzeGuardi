/**
 * WyzeGuardi Client-Side JavaScript
 */

// Utility: Format timestamp to relative time
function formatRelativeTime(timestamp) {
    const now = new Date();
    const then = new Date(timestamp);
    const diffMs = now - then;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} min ago`;
    if (diffHours < 24) return `${diffHours} hours ago`;
    return `${diffDays} days ago`;
}

// Utility: Confirm action with custom message
function confirmAction(message) {
    return confirm(message);
}

// Auto-refresh notification
let autoRefreshInterval = null;

function startAutoRefresh(intervalSeconds = 30) {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }

    autoRefreshInterval = setInterval(() => {
        console.log('Auto-refreshing page...');
        location.reload();
    }, intervalSeconds * 1000);
}

// Stop auto-refresh on user interaction (prevents interrupting user)
function stopAutoRefreshOnInteraction() {
    ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(event => {
        document.addEventListener(event, () => {
            if (autoRefreshInterval) {
                console.log('User interaction detected, pausing auto-refresh');
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }, { once: true });
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('WyzeGuardi dashboard loaded');

    // Enable auto-refresh prevention on interaction
    // stopAutoRefreshOnInteraction();

    // Add timestamps to elements with data-timestamp attribute
    document.querySelectorAll('[data-timestamp]').forEach(el => {
        const timestamp = el.dataset.timestamp;
        el.textContent = formatRelativeTime(timestamp);
    });

    // Mobile hamburger menu toggle
    const hamburger = document.getElementById('hamburger');
    const navMenu = document.getElementById('nav-menu');

    if (hamburger && navMenu) {
        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });

        // Close menu when clicking a nav link
        navMenu.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            });
        });
    }
});

// Keyboard shortcuts (optional)
document.addEventListener('keydown', (e) => {
    // Ctrl+R or Cmd+R: Manual refresh (browser default, but we can log it)
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        console.log('Manual refresh requested');
    }
});

// Add visual feedback for manual control buttons
document.querySelectorAll('.btn-off, .btn-on').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const action = btn.classList.contains('btn-off') ? 'OFF' : 'ON';
        console.log(`Camera control: ${action}`);
    });
});

// Export utilities for use in templates
window.WyzeGuardi = {
    formatRelativeTime,
    confirmAction,
    startAutoRefresh
};
