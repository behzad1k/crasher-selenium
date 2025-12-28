# Gunicorn configuration file
# gunicorn_config.py

import multiprocessing

# Server socket
bind = "0.0.0.0:5002"
backlog = 2048

# Worker processes
# For CPU-bound apps: workers = (2 * CPU cores) + 1
# For I/O-bound apps (like this bot): workers = (4 * CPU cores) + 1
# Since we're running a bot with WebSockets, we'll use a moderate approach
workers = 4  # 4 cores, 1 worker per core for WebSocket stability
worker_class = "eventlet"  # Use eventlet for WebSocket support
worker_connections = 1000
timeout = 120  # Longer timeout for bot operations
keepalive = 5

# Server mechanics
daemon = False
pidfile = "/tmp/crasher_bot_server.pid"
umask = 0
user = None
group = None
tmp_upload_dir = None

# Logging
errorlog = "/var/log/crasher_error.log"
loglevel = "info"
accesslog = "/var/log/crasher_access.log"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "crasher_bot_server"


# Server hooks
def on_starting(server):
    print("=" * 60)
    print("CRASHER BOT SERVER STARTING WITH GUNICORN")
    print("=" * 60)
    print(f"Workers: {workers}")
    print(f"Worker class: {worker_class}")
    print(f"Binding to: {bind}")
    print("=" * 60)


def when_ready(server):
    print("✓ Crasher Bot Server is ready to accept connections")


def on_exit(server):
    print("✗ Crasher Bot Server shutting down")
