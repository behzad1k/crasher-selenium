#!/usr/bin/env python3
"""
Flask Server for Crasher Bot GUI
Provides REST API for bot control and data visualization with WebSocket support for real-time logs
"""

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from queue import Empty, Queue
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Import bot components
from crasher_bot import Database, MultiStrategyCrasherBot


# Custom log handler to capture logs and send via WebSocket
class WebSocketLogHandler(logging.Handler):
    """Custom handler that sends logs via WebSocket"""

    def __init__(self, socketio):
        super().__init__()
        self.socketio = socketio
        self.log_queue = Queue(maxsize=1000)

    def emit(self, record):
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": self.format(record),
            }

            # Add to queue for buffer
            try:
                self.log_queue.put_nowait(log_entry)
            except:
                pass

            # Send via WebSocket
            self.socketio.emit("log_message", log_entry, namespace="/")
        except Exception as e:
            # Don't let logging errors break the app
            pass


# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crasher_bot_server.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = "crasher-bot-secret-key-change-in-production"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Add WebSocket handler to logger
ws_handler = WebSocketLogHandler(socketio)
ws_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(ws_handler)

# Also add it to the bot's logger
bot_logger = logging.getLogger("crasher_bot")
bot_logger.addHandler(ws_handler)

# Global bot instance
bot_instance: Optional[MultiStrategyCrasherBot] = None
bot_thread: Optional[threading.Thread] = None
bot_status = {
    "running": False,
    "current_session_id": None,
    "total_profit": 0.0,
    "start_time": None,
    "error": None,
}


class BotController:
    """Manages bot lifecycle"""

    def __init__(self):
        self.bot = None
        self.thread = None
        self.should_stop = False

    def start(self):
        """Start the bot in a background thread"""
        if self.is_running():
            logger.warning("Bot start requested but bot is already running")
            return {"success": False, "error": "Bot is already running"}

        try:
            logger.info("Starting bot...")
            self.should_stop = False
            self.bot = MultiStrategyCrasherBot(config_path="./bot_config.json")

            def run_bot():
                try:
                    bot_status["running"] = True
                    bot_status["start_time"] = datetime.now().isoformat()
                    bot_status["error"] = None

                    logger.info("Bot thread started successfully")
                    socketio.emit("bot_status", bot_status, namespace="/")

                    self.bot.run()

                except Exception as e:
                    logger.error(f"Bot error: {e}", exc_info=True)
                    bot_status["error"] = str(e)
                    socketio.emit("bot_status", bot_status, namespace="/")
                finally:
                    bot_status["running"] = False
                    logger.info("Bot stopped")
                    socketio.emit("bot_status", bot_status, namespace="/")

            self.thread = threading.Thread(target=run_bot, daemon=True)
            self.thread.start()

            # Wait a moment to check if bot started successfully
            time.sleep(2)

            logger.info("Bot start command completed")
            return {"success": True, "message": "Bot started"}

        except Exception as e:
            logger.error(f"Failed to start bot: {e}", exc_info=True)
            bot_status["running"] = False
            bot_status["error"] = str(e)
            socketio.emit("bot_status", bot_status, namespace="/")
            return {"success": False, "error": str(e)}

    def stop(self):
        """Stop the bot"""
        if not self.is_running():
            logger.warning("Bot stop requested but bot is not running")
            return {"success": False, "error": "Bot is not running"}

        try:
            logger.info("Stopping bot...")
            if self.bot:
                self.bot.running = False
                self.should_stop = True

            # Wait for thread to finish (with timeout)
            if self.thread:
                self.thread.join(timeout=10)

            bot_status["running"] = False
            logger.info("Bot stopped successfully")
            socketio.emit("bot_status", bot_status, namespace="/")
            return {"success": True, "message": "Bot stopped"}

        except Exception as e:
            logger.error(f"Failed to stop bot: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def is_running(self):
        """Check if bot is running"""
        return bot_status["running"] and self.thread and self.thread.is_alive()

    def get_status(self):
        """Get current bot status"""
        status = bot_status.copy()
        status["running"] = self.is_running()

        if self.bot:
            status["current_session_id"] = self.bot.db.current_session_id
            status["total_profit"] = self.bot.total_profit

            # Get strategy states
            strategy_states = {}
            for name, strategy in self.bot.strategies.items():
                strategy_states[name] = {
                    "is_active": strategy.is_active,
                    "waiting_for_result": strategy.waiting_for_result,
                    "consecutive_losses": strategy.consecutive_losses,
                    "current_bet": strategy.current_bet,
                    "total_profit": strategy.total_profit,
                }
            status["strategies"] = strategy_states

        return status


# Global controller
bot_controller = BotController()


# ============================================================================
# WebSocket Events
# ============================================================================


@socketio.on("connect")
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")

    # Send current bot status
    emit("bot_status", bot_controller.get_status())

    # Send recent logs from buffer
    recent_logs = []
    try:
        while len(recent_logs) < 100:
            log_entry = ws_handler.log_queue.get_nowait()
            recent_logs.append(log_entry)
    except Empty:
        pass

    if recent_logs:
        emit("initial_logs", {"logs": recent_logs})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")


@socketio.on("request_logs")
def handle_request_logs(data):
    """Send recent logs on request"""
    count = data.get("count", 100)

    recent_logs = []
    try:
        temp_logs = []
        while len(temp_logs) < count:
            log_entry = ws_handler.log_queue.get_nowait()
            temp_logs.append(log_entry)
        # Put them back
        for log in temp_logs:
            ws_handler.log_queue.put_nowait(log)
        recent_logs = temp_logs
    except Empty:
        pass

    emit("initial_logs", {"logs": recent_logs})


# ============================================================================
# API Routes - Bot Control
# ============================================================================


@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    """Start the bot"""
    result = bot_controller.start()
    return jsonify(result)


@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """Stop the bot"""
    result = bot_controller.stop()
    return jsonify(result)


@app.route("/api/bot/status", methods=["GET"])
def get_bot_status():
    """Get bot status"""
    status = bot_controller.get_status()
    return jsonify(status)


# ============================================================================
# API Routes - Strategies
# ============================================================================


@app.route("/api/strategies", methods=["GET"])
def get_strategies():
    """Get all strategies from config"""
    try:
        with open("./bot_config.json", "r") as f:
            config = json.load(f)
        return jsonify({"success": True, "strategies": config.get("strategies", [])})
    except Exception as e:
        logger.error(f"Error loading strategies: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/strategies", methods=["POST"])
def create_strategy():
    """Create a new strategy"""
    try:
        new_strategy = request.json

        # Validate required fields
        required = [
            "name",
            "base_bet",
            "auto_cashout",
            "trigger_threshold",
            "trigger_count",
        ]
        for field in required:
            if field not in new_strategy:
                return jsonify(
                    {"success": False, "error": f"Missing field: {field}"}
                ), 400

        # Load config
        with open("./bot_config.json", "r") as f:
            config = json.load(f)

        # Check if strategy name already exists
        if any(s["name"] == new_strategy["name"] for s in config["strategies"]):
            return jsonify(
                {"success": False, "error": "Strategy name already exists"}
            ), 400

        # Add defaults
        new_strategy.setdefault("max_consecutive_losses", 100)
        new_strategy.setdefault("bet_multiplier", 2.0)

        # Add strategy
        config["strategies"].append(new_strategy)

        # Save config
        with open("./bot_config.json", "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Strategy created: {new_strategy['name']}")
        return jsonify({"success": True, "message": "Strategy created"})

    except Exception as e:
        logger.error(f"Error creating strategy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/strategies/<strategy_name>", methods=["PUT"])
def update_strategy(strategy_name):
    """Update an existing strategy"""
    try:
        updated_strategy = request.json

        # Load config
        with open("./bot_config.json", "r") as f:
            config = json.load(f)

        # Find and update strategy
        found = False
        for i, strategy in enumerate(config["strategies"]):
            if strategy["name"] == strategy_name:
                # Keep the name, update other fields
                updated_strategy["name"] = strategy_name
                config["strategies"][i] = updated_strategy
                found = True
                break

        if not found:
            return jsonify({"success": False, "error": "Strategy not found"}), 404

        # Save config
        with open("./bot_config.json", "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Strategy updated: {strategy_name}")
        return jsonify({"success": True, "message": "Strategy updated"})

    except Exception as e:
        logger.error(f"Error updating strategy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/strategies/<strategy_name>", methods=["DELETE"])
def delete_strategy(strategy_name):
    """Delete a strategy"""
    try:
        # Load config
        with open("./bot_config.json", "r") as f:
            config = json.load(f)

        # Filter out the strategy
        original_count = len(config["strategies"])
        config["strategies"] = [
            s for s in config["strategies"] if s["name"] != strategy_name
        ]

        if len(config["strategies"]) == original_count:
            return jsonify({"success": False, "error": "Strategy not found"}), 404

        # Save config
        with open("./bot_config.json", "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Strategy deleted: {strategy_name}")
        return jsonify({"success": True, "message": "Strategy deleted"})

    except Exception as e:
        logger.error(f"Error deleting strategy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# API Routes - Data
# ============================================================================


@app.route("/api/multipliers/recent", methods=["GET"])
def get_recent_multipliers():
    """Get recent multipliers from current session"""
    try:
        limit = request.args.get("limit", 100, type=int)

        db = Database()

        if bot_controller.bot and bot_controller.bot.db.current_session_id:
            session_id = bot_controller.bot.db.current_session_id
        else:
            # Get last session
            cursor = db.conn.cursor()
            cursor.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1")
            result = cursor.fetchone()
            session_id = result[0] if result else None

        if not session_id:
            return jsonify({"success": True, "multipliers": []})

        cursor = db.conn.cursor()
        cursor.execute(
            """
            SELECT m.id, m.multiplier, m.bettor_count, m.timestamp,
                   b.bet_amount, b.outcome, b.profit_loss, b.strategy_name
            FROM multipliers m
            LEFT JOIN bets b ON b.timestamp BETWEEN
                datetime(m.timestamp, '-5 seconds') AND datetime(m.timestamp, '+5 seconds')
            WHERE m.session_id = ?
            ORDER BY m.id DESC
            LIMIT ?
        """,
            (session_id, limit),
        )

        multipliers = []
        for row in cursor.fetchall():
            multipliers.append(
                {
                    "id": row[0],
                    "multiplier": row[1],
                    "bettor_count": row[2],
                    "timestamp": row[3],
                    "bet": {
                        "amount": row[4],
                        "outcome": row[5],
                        "profit_loss": row[6],
                        "strategy_name": row[7],
                    }
                    if row[4]
                    else None,
                }
            )

        # Reverse to get chronological order
        multipliers.reverse()

        db.close()

        return jsonify(
            {"success": True, "multipliers": multipliers, "session_id": session_id}
        )

    except Exception as e:
        logger.error(f"Error getting recent multipliers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    """Get all sessions"""
    try:
        db = Database()
        cursor = db.conn.cursor()

        cursor.execute("""
            SELECT s.id, s.start_timestamp, s.end_timestamp,
                   s.start_balance, s.end_balance, s.total_rounds,
                   COUNT(m.id) as actual_rounds
            FROM sessions s
            LEFT JOIN multipliers m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.id DESC
        """)

        sessions = []
        for row in cursor.fetchall():
            sessions.append(
                {
                    "id": row[0],
                    "start_timestamp": row[1],
                    "end_timestamp": row[2],
                    "start_balance": row[3],
                    "end_balance": row[4],
                    "total_rounds": row[6],  # Use actual count
                    "profit_loss": (row[4] - row[3]) if (row[3] and row[4]) else None,
                }
            )

        db.close()

        return jsonify({"success": True, "sessions": sessions})

    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sessions/<int:session_id>/multipliers", methods=["GET"])
def get_session_multipliers(session_id):
    """Get all multipliers for a specific session"""
    try:
        db = Database()
        cursor = db.conn.cursor()

        cursor.execute(
            """
            SELECT m.id, m.multiplier, m.bettor_count, m.timestamp,
                   b.bet_amount, b.outcome, b.profit_loss, b.strategy_name
            FROM multipliers m
            LEFT JOIN bets b ON b.timestamp BETWEEN
                datetime(m.timestamp, '-5 seconds') AND datetime(m.timestamp, '+5 seconds')
            WHERE m.session_id = ?
            ORDER BY m.id ASC
        """,
            (session_id,),
        )

        multipliers = []
        for row in cursor.fetchall():
            multipliers.append(
                {
                    "id": row[0],
                    "multiplier": row[1],
                    "bettor_count": row[2],
                    "timestamp": row[3],
                    "bet": {
                        "amount": row[4],
                        "outcome": row[5],
                        "profit_loss": row[6],
                        "strategy_name": row[7],
                    }
                    if row[4]
                    else None,
                }
            )

        db.close()

        return jsonify(
            {"success": True, "multipliers": multipliers, "session_id": session_id}
        )

    except Exception as e:
        logger.error(f"Error getting session multipliers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/bets/current-session", methods=["GET"])
def get_current_session_bets():
    """Get all bets from current session"""
    try:
        db = Database()

        if bot_controller.bot and bot_controller.bot.db.current_session_id:
            session_id = bot_controller.bot.db.current_session_id
        else:
            # Get last session
            cursor = db.conn.cursor()
            cursor.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1")
            result = cursor.fetchone()
            session_id = result[0] if result else None

        if not session_id:
            return jsonify({"success": True, "bets": []})

        cursor = db.conn.cursor()
        cursor.execute(
            """
            SELECT b.id, b.strategy_name, b.bet_amount, b.outcome,
                   b.multiplier, b.profit_loss, b.timestamp
            FROM bets b
            WHERE b.timestamp >= (
                SELECT start_timestamp FROM sessions WHERE id = ?
            )
            ORDER BY b.id DESC
            LIMIT 100
        """,
            (session_id,),
        )

        bets = []
        for row in cursor.fetchall():
            bets.append(
                {
                    "id": row[0],
                    "strategy_name": row[1],
                    "bet_amount": row[2],
                    "outcome": row[3],
                    "multiplier": row[4],
                    "profit_loss": row[5],
                    "timestamp": row[6],
                }
            )

        db.close()

        return jsonify({"success": True, "bets": bets, "session_id": session_id})

    except Exception as e:
        logger.error(f"Error getting bets: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Static Files
# ============================================================================


@app.route("/")
def index():
    """Serve the main page"""
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def serve_static(path):
    """Serve static files"""
    return send_from_directory("static", path)


# ============================================================================
# Main
# ============================================================================


def main():
    """Run the Flask server"""
    port = int(os.environ.get("PORT", 5001))
    logger.info("=" * 60)
    logger.info("CRASHER BOT SERVER STARTING")
    logger.info("=" * 60)
    logger.info(f"Starting Crasher Bot Server on port {port}")
    logger.info(f"Dashboard available at http://localhost:{port}")
    logger.info(f"WebSocket support enabled for real-time logs")
    logger.info("=" * 60)

    # Create static directory if it doesn't exist
    os.makedirs("static", exist_ok=True)

    # Run with SocketIO
    socketio.run(
        app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True
    )


if __name__ == "__main__":
    main()
