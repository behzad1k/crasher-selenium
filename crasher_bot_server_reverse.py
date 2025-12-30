#!/usr/bin/env python3
"""
Crasher Bot Server - Reverse Martingale Version

Flask server for controlling and monitoring the reverse martingale bot
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import signal
import json
import logging
from datetime import datetime
from threading import Thread, Lock

app = Flask(__name__)
CORS(app)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BotController:
    """Controller for the reverse martingale bot"""
    
    def __init__(self):
        self.process = None
        self.lock = Lock()
        self.bot = None
    
    def start(self):
        """Start the bot process"""
        with self.lock:
            if self.process and self.process.poll() is None:
                return {"success": False, "error": "Bot is already running"}
            
            try:
                # Start bot as subprocess
                self.process = subprocess.Popen(
                    ["python3", "crasher_bot_reverse.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                
                logger.info(f"Bot started with PID: {self.process.pid}")
                return {"success": True, "pid": self.process.pid}
            
            except Exception as e:
                logger.error(f"Failed to start bot: {e}")
                return {"success": False, "error": str(e)}
    
    def stop(self):
        """Stop the bot process"""
        with self.lock:
            if not self.process or self.process.poll() is not None:
                return {"success": False, "error": "Bot is not running"}
            
            try:
                # Send SIGTERM for graceful shutdown
                os.kill(self.process.pid, signal.SIGTERM)
                
                # Wait for process to terminate (max 10 seconds)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Force kill if not responding
                    os.kill(self.process.pid, signal.SIGKILL)
                    self.process.wait()
                
                logger.info("Bot stopped")
                self.process = None
                return {"success": True}
            
            except Exception as e:
                logger.error(f"Failed to stop bot: {e}")
                return {"success": False, "error": str(e)}
    
    def is_running(self):
        """Check if bot is running"""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def get_status(self):
        """Get bot status"""
        running = self.is_running()
        
        if running:
            return {
                "running": True,
                "pid": self.process.pid
            }
        else:
            return {
                "running": False,
                "pid": None
            }


# Global bot controller
bot_controller = BotController()


@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    """Start the bot"""
    result = bot_controller.start()
    
    if result["success"]:
        return jsonify(result), 200
    else:
        return jsonify(result), 400


@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """Stop the bot"""
    result = bot_controller.stop()
    
    if result["success"]:
        return jsonify(result), 200
    else:
        return jsonify(result), 400


@app.route("/api/bot/status", methods=["GET"])
def get_status():
    """Get bot status"""
    status = bot_controller.get_status()
    return jsonify(status), 200


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get current configuration"""
    try:
        with open("bot_config.json", "r") as f:
            config = json.load(f)
        return jsonify(config), 200
    except Exception as e:
        logger.error(f"Failed to read config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def update_config():
    """Update configuration"""
    try:
        new_config = request.json
        
        # Validate config
        if "strategies" not in new_config:
            return jsonify({"error": "Missing 'strategies' field"}), 400
        
        # Backup current config
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"bot_config_backup_{timestamp}.json"
        
        try:
            with open("bot_config.json", "r") as f:
                old_config = f.read()
            with open(backup_path, "w") as f:
                f.write(old_config)
            logger.info(f"Config backed up to {backup_path}")
        except:
            pass
        
        # Write new config
        with open("bot_config.json", "w") as f:
            json.dump(new_config, f, indent=2)
        
        logger.info("Config updated successfully")
        return jsonify({"success": True}), 200
    
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/strategies", methods=["GET"])
def get_strategies():
    """Get all strategies"""
    try:
        with open("bot_config.json", "r") as f:
            config = json.load(f)
        
        strategies = config.get("strategies", [])
        return jsonify({"strategies": strategies}), 200
    
    except Exception as e:
        logger.error(f"Failed to get strategies: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/strategies/<strategy_name>/activate", methods=["POST"])
def activate_strategy(strategy_name):
    """Manually activate a strategy"""
    try:
        if not bot_controller.is_running():
            return jsonify({"success": False, "error": "Bot is not running"}), 400
        
        # Note: This requires the bot to expose an API or use IPC
        # For now, we'll just return success and let the user manually trigger
        # A full implementation would require the bot to listen for commands
        
        logger.info(f"Strategy '{strategy_name}' activation requested via API")
        return jsonify({
            "success": True, 
            "message": f"Strategy '{strategy_name}' activation requested. Note: Manual activation requires bot restart or config change."
        }), 200
    
    except Exception as e:
        logger.error(f"Error activating strategy: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Get recent log entries"""
    try:
        lines = request.args.get("lines", 100, type=int)
        
        if not os.path.exists("crasher_bot.log"):
            return jsonify({"logs": []}), 200
        
        with open("crasher_bot.log", "r") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:]
        
        return jsonify({"logs": recent_lines}), 200
    
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/database/sessions", methods=["GET"])
def get_sessions():
    """Get database sessions"""
    try:
        import sqlite3
        
        conn = sqlite3.connect("crasher_data.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT s.id, s.start_timestamp, s.end_timestamp, COUNT(m.id) as rounds
            FROM sessions s
            LEFT JOIN multipliers m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.id DESC
            LIMIT 50
        """)
        
        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "id": row[0],
                "start": row[1],
                "end": row[2],
                "rounds": row[3]
            })
        
        conn.close()
        
        return jsonify({"sessions": sessions}), 200
    
    except Exception as e:
        logger.error(f"Failed to get sessions: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/database/multipliers", methods=["GET"])
def get_multipliers():
    """Get recent multipliers"""
    try:
        import sqlite3
        
        session_id = request.args.get("session_id", type=int)
        limit = request.args.get("limit", 100, type=int)
        
        conn = sqlite3.connect("crasher_data.db")
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute("""
                SELECT multiplier, bettor_count, timestamp
                FROM multipliers
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (session_id, limit))
        else:
            cursor.execute("""
                SELECT multiplier, bettor_count, timestamp
                FROM multipliers
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        
        multipliers = []
        for row in cursor.fetchall():
            multipliers.append({
                "multiplier": row[0],
                "bettor_count": row[1],
                "timestamp": row[2]
            })
        
        conn.close()
        
        return jsonify({"multipliers": multipliers}), 200
    
    except Exception as e:
        logger.error(f"Failed to get multipliers: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    """Health check"""
    return jsonify({
        "service": "Crasher Bot Server - Reverse Martingale",
        "version": "1.0.0",
        "status": "running"
    }), 200


def main():
    """Run the server"""
    logger.info("Starting Crasher Bot Server - Reverse Martingale...")
    logger.info("API available at http://localhost:5001")
    
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False,
        threaded=True
    )


if __name__ == "__main__":
    main()
