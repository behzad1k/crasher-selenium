#!/usr/bin/env python3
"""
Crasher Bot - Production Optimized
Key improvements:
1. ALWAYS verifies auto-cashout before betting (non-negotiable safety)
2. Python DOM parsing instead of slow JavaScript execution
3. Cached ChromeDriver with automatic fallback download
4. Live strategy reload without restart
5. Manual strategy activation via API
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np  # Needed for volatility calculation

from prediction_module import PredictionAnalyzer, create_game_state_tracker

try:
    import undetected_chromedriver as uc

    UNDETECTED_AVAILABLE = True
except ImportError:
    UNDETECTED_AVAILABLE = False

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crasher_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class StrategyState:
    """Track state for a single strategy"""

    name: str
    base_bet: float
    auto_cashout: float
    trigger_threshold: float
    trigger_count: int
    max_consecutive_losses: int
    bet_multiplier: float

    # Runtime state
    current_bet: float
    consecutive_losses: int
    total_profit: float
    waiting_for_result: bool
    is_active: bool
    manual_trigger: bool = False  # NEW: For manual activation

    def reset(self):
        """Reset strategy state after win"""
        self.current_bet = self.base_bet
        self.consecutive_losses = 0
        self.waiting_for_result = False
        self.manual_trigger = False

    def calc_next_bet(self) -> float:
        """Calculate next bet using custom multiplier"""
        if self.consecutive_losses == 0:
            return self.base_bet
        return self.base_bet * (self.bet_multiplier**self.consecutive_losses)


class SessionManager:
    """Manages session creation and recovery"""

    def __init__(self, conn: sqlite3.Connection, logger_func=None):
        self.conn = conn
        self.log = logger_func or print
        self._ensure_sessions_table()

    def _ensure_sessions_table(self):
        """Ensure sessions table exists"""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_timestamp DATETIME NOT NULL,
                end_timestamp DATETIME,
                start_balance REAL,
                end_balance REAL,
                total_rounds INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(multipliers)")
        columns = [col[1] for col in cursor.fetchall()]

        if "session_id" not in columns:
            cursor.execute(
                "ALTER TABLE multipliers ADD COLUMN session_id INTEGER REFERENCES sessions(id)"
            )

        self.conn.commit()

    def get_last_session(self) -> Optional[Tuple[int, datetime, int]]:
        """Get last session info: (session_id, last_timestamp, round_count)"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]

        if session_count == 0:
            cursor.execute("""
                SELECT COUNT(*), MAX(timestamp)
                FROM multipliers
                WHERE session_id IS NULL
            """)
            old_count, old_last = cursor.fetchone()

            if old_count and old_count > 0:
                self.log(
                    f"Found {old_count} old multipliers without session (migrating...)"
                )
                cursor.execute("""
                    INSERT INTO sessions (start_timestamp, end_timestamp)
                    VALUES (
                        (SELECT MIN(timestamp) FROM multipliers WHERE session_id IS NULL),
                        (SELECT MAX(timestamp) FROM multipliers WHERE session_id IS NULL)
                    )
                """)
                new_session_id = cursor.lastrowid

                cursor.execute(
                    """
                    UPDATE multipliers
                    SET session_id = ?
                    WHERE session_id IS NULL
                """,
                    (new_session_id,),
                )

                self.conn.commit()
                self.log(f"✓ Migrated old data to session #{new_session_id}")

        cursor.execute("""
            SELECT s.id, MAX(m.timestamp), COUNT(m.id)
            FROM sessions s
            LEFT JOIN multipliers m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.id DESC
            LIMIT 1
        """)

        result = cursor.fetchone()
        return result if result and result[1] else None

    def get_last_n_multipliers_from_session(
        self, session_id: int, n: int
    ) -> List[float]:
        """Get last N multipliers from a session in chronological order"""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT multiplier
            FROM multipliers
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
        """,
            (session_id, n),
        )

        return [row[0] for row in reversed(cursor.fetchall())]

    def create_session(self, start_balance: Optional[float] = None) -> int:
        """Create new session and return session_id"""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO sessions (start_timestamp, start_balance)
            VALUES (?, ?)
        """,
            (datetime.now(), start_balance),
        )

        self.conn.commit()
        return cursor.lastrowid

    def update_session_end(self, session_id: int, end_balance: Optional[float] = None):
        """Update session end time and balance"""
        cursor = self.conn.cursor()

        cursor.execute(
            """
            UPDATE sessions
            SET end_timestamp = ?, end_balance = ?
            WHERE id = ?
        """,
            (datetime.now(), end_balance, session_id),
        )

        self.conn.commit()

    def add_missing_rounds(
        self,
        session_id: int,
        multipliers: List[float],
        start_time: datetime,
        end_time: datetime,
    ):
        """Add missing rounds to database with estimated timestamps"""
        if not multipliers:
            return

        cursor = self.conn.cursor()

        total_seconds = (end_time - start_time).total_seconds()
        seconds_per_round = (
            total_seconds / len(multipliers) if len(multipliers) > 1 else 0
        )

        for i, mult in enumerate(multipliers):
            if i == len(multipliers) - 1:
                timestamp = end_time
            else:
                timestamp = start_time + timedelta(seconds=seconds_per_round * (i + 1))

            try:
                cursor.execute(
                    """
                    INSERT INTO multipliers (multiplier, session_id, timestamp)
                    VALUES (?, ?, ?)
                """,
                    (mult, session_id, timestamp),
                )
            except sqlite3.IntegrityError:
                pass

        self.conn.commit()


class Database:
    """Database for tracking bets and multipliers"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()
        self.log_func = None
        self.session_manager = None
        self.current_session_id: Optional[int] = None

    def set_logger(self, log_func):
        """Set logger function and initialize session manager"""
        self.log_func = log_func
        self.session_manager = SessionManager(self.conn, log_func)

    def _init_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                session_id INTEGER REFERENCES sessions(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NULL,
                bet_amount REAL NOT NULL,
                outcome TEXT CHECK(outcome IN ('win', 'loss')),
                multiplier REAL,
                profit_loss REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_multiplier(self, multiplier: float, bettor_count: Optional[int] = None):
        """Add multiplier to current session"""
        if self.current_session_id is None:
            raise ValueError("No active session!")

        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO multipliers (multiplier, bettor_count, session_id) VALUES (?, ?, ?)",
            (multiplier, bettor_count, self.current_session_id),
        )
        self.conn.commit()

    def get_recent_multipliers(self, count: int) -> List[float]:
        """Get recent multipliers from current session"""
        if self.current_session_id is None:
            return []

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT multiplier FROM multipliers WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.current_session_id, count),
        )
        return [row[0] for row in reversed(cursor.fetchall())]

    def add_bet(
        self,
        strategy_name: str,
        bet_amount: float,
        outcome: str,
        multiplier: float,
        profit_loss: float,
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO bets (strategy_name, bet_amount, outcome, multiplier, profit_loss) VALUES (?, ?, ?, ?, ?)",
            (strategy_name, bet_amount, outcome, multiplier, profit_loss),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class MultiStrategyCrasherBot:
    """Crasher bot - Production optimized with Python DOM parsing"""

    def __init__(self, config_path: str = "./bot_config.json"):
        self.config_path = config_path
        self.config = self._load_config()

        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        self.max_loss = float(self.config.get("max_loss", 100000000))

        # Load strategies
        self.strategies: Dict[str, StrategyState] = {}
        self._load_strategies()
        self.prediction_analyzer = None  # Will be initialized after DB is ready
        self.game_state_tracker = create_game_state_tracker()
        # Bot state
        self.driver = None
        self.wait = None
        self.db = Database()
        self.db.set_logger(self.log)
        self.last_seen_multiplier = None
        self.last_round_time = 0
        self.last_round_id = None  # NEW: Track unique round identifier
        self.running = False

        # Config monitoring
        self.last_config_mtime = 0
        self.last_config_check = 0
        self.config_check_interval = 2  # Check every 2 seconds

        self.rounds_since_setup = 0
        self.total_profit = 0.0

    def _load_config(self):
        """Load config from file"""
        with open(self.config_path, "r") as f:
            return json.load(f)

    def activate_strategy_manually(self, strategy_name: str) -> bool:
        """
        Manually activate a strategy (called from API)
        Returns True if strategy was activated
        """
        if strategy_name not in self.strategies:
            self.log(f"ERROR: Strategy '{strategy_name}' not found")
            return False

        strategy = self.strategies[strategy_name]

        if strategy.waiting_for_result:
            self.log(
                f"WARNING: Strategy '{strategy_name}' already has a bet in progress"
            )
            return False

        # Set manual trigger flag
        strategy.manual_trigger = True
        self.log(f"✓ Strategy '{strategy_name}' marked for manual activation")
        return True

    def reload_strategies_if_changed(self) -> bool:
        """
        Monitor config file and reload strategies if changed
        Preserves runtime state for existing strategies
        """
        current_time = time.time()

        # Only check periodically
        if current_time - self.last_config_check < self.config_check_interval:
            return False

        self.last_config_check = current_time

        try:
            # Check if file was modified
            current_mtime = os.path.getmtime(self.config_path)

            if self.last_config_mtime == 0:
                # First check, just record the time
                self.last_config_mtime = current_mtime
                return False

            if current_mtime <= self.last_config_mtime:
                # No change
                return False

            # File was modified!
            self.last_config_mtime = current_mtime

            self.log("=" * 60)
            self.log("CONFIG FILE MODIFIED - Reloading strategies")
            self.log("=" * 60)

            new_config = self._load_config()

            # Save old strategy states
            old_states = {}
            for name, strategy in self.strategies.items():
                old_states[name] = {
                    "current_bet": strategy.current_bet,
                    "consecutive_losses": strategy.consecutive_losses,
                    "total_profit": strategy.total_profit,
                    "waiting_for_result": strategy.waiting_for_result,
                    "is_active": strategy.is_active,
                    "manual_trigger": strategy.manual_trigger,
                }

            old_strategy_names = set(self.strategies.keys())

            # Reload config and strategies
            self.config = new_config
            self.strategies.clear()
            self._load_strategies()

            # Restore runtime state for existing strategies
            for name, strategy in self.strategies.items():
                if name in old_states:
                    state = old_states[name]
                    strategy.current_bet = state["current_bet"]
                    strategy.consecutive_losses = state["consecutive_losses"]
                    strategy.total_profit = state["total_profit"]
                    strategy.waiting_for_result = state["waiting_for_result"]
                    strategy.is_active = state["is_active"]
                    strategy.manual_trigger = state["manual_trigger"]
                    self.log(f"✓ Preserved state for: {name}")
                else:
                    self.log(f"✓ Added new strategy: {name}")

            # Report removed strategies
            new_strategy_names = set(self.strategies.keys())
            removed = old_strategy_names - new_strategy_names
            if removed:
                self.log(f"✗ Removed strategies: {', '.join(removed)}")

            self.log("=" * 60)
            return True

        except Exception as e:
            self.log(f"ERROR reloading config: {e}")
            import traceback

            self.log(traceback.format_exc())

        return False

    def _load_strategies(self):
        """Load all strategies from config"""
        if "strategies" not in self.config:
            raise ValueError("No 'strategies' section found in config file!")

        for strategy_config in self.config["strategies"]:
            name = strategy_config["name"]
            strategy = StrategyState(
                name=name,
                base_bet=float(strategy_config["base_bet"]),
                auto_cashout=float(strategy_config["auto_cashout"]),
                trigger_threshold=float(strategy_config["trigger_threshold"]),
                trigger_count=int(strategy_config["trigger_count"]),
                max_consecutive_losses=int(
                    strategy_config.get("max_consecutive_losses", 20)
                ),
                bet_multiplier=float(strategy_config.get("bet_multiplier", 2.0)),
                current_bet=float(strategy_config["base_bet"]),
                consecutive_losses=0,
                total_profit=0.0,
                waiting_for_result=False,
                is_active=False,
            )
            self.strategies[name] = strategy
            self.log(f"Loaded strategy: {name}")

    def log(self, message: str):
        try:
            logger.info(message)
        except UnicodeEncodeError:
            clean_msg = message.encode("ascii", "ignore").decode("ascii")
            logger.info(clean_msg)

    def read_recent_multipliers_from_page(self) -> List[float]:
        """Read recent multipliers using Python DOM parsing (faster than JS)"""
        try:
            # Use Selenium's native DOM access instead of JS execution
            result_items = self.driver.find_elements(
                By.CSS_SELECTOR, "span.sc-w0koce-1.giBFzM"
            )

            multipliers = []
            for item in result_items:
                text = item.text.strip()
                if text.endswith("x"):
                    try:
                        value = float(text.replace("x", ""))
                        multipliers.append(value)
                    except ValueError:
                        continue

            # Reverse to get chronological order
            multipliers.reverse()

            if multipliers:
                self.log(f"Read {len(multipliers)} recent multipliers from page")
                self.log(f"  Range: {min(multipliers):.2f}x to {max(multipliers):.2f}x")
                return multipliers
            else:
                self.log("No multipliers found on page")
                return []

        except Exception as e:
            self.log(f"Error reading multipliers from page: {e}")
            return []

    def find_session_in_recent_multipliers(
        self, recent_page: List[float], min_consecutive: int = 5
    ) -> Optional[Tuple[int, int, List[float]]]:
        """Try to find last session's data in recent multipliers from page"""
        last_session = self.db.session_manager.get_last_session()

        if not last_session:
            self.log("No previous session found in database")
            return None

        session_id, last_timestamp, round_count = last_session

        self.log(f"Found session #{session_id} with {round_count} rounds")

        if round_count == 0:
            self.log(f"Last session #{session_id} is empty, will continue it")
            return (session_id, 0, recent_page)

        max_pattern = min(round_count, 20)

        for pattern_length in range(max_pattern, min_consecutive - 1, -1):
            db_pattern = self.db.session_manager.get_last_n_multipliers_from_session(
                session_id, pattern_length
            )

            if not db_pattern:
                continue

            for i in range(len(recent_page) - pattern_length + 1):
                page_slice = recent_page[i : i + pattern_length]

                matches = [abs(a - b) < 0.01 for a, b in zip(db_pattern, page_slice)]

                if all(matches):
                    match_end_pos = i + pattern_length
                    missing_rounds = recent_page[match_end_pos:]

                    self.log(f"✓ Found session match!")
                    self.log(
                        f"  Pattern: {pattern_length} rounds, Missing: {len(missing_rounds)}"
                    )

                    return (session_id, match_end_pos, missing_rounds)

        self.log(f"Could not find session #{session_id} in recent multipliers")
        return None

    def recover_or_create_session(self, start_balance: Optional[float] = None):
        """Attempt to recover last session or create new one"""
        self.log("=" * 60)
        self.log("SESSION RECOVERY")
        self.log("=" * 60)

        recent_page = self.read_recent_multipliers_from_page()

        if not recent_page:
            self.log("⚠️  No recent multipliers on page, creating new session")
            self.db.current_session_id = self.db.session_manager.create_session(
                start_balance
            )
            self.log(f"✓ Created new session #{self.db.current_session_id}")
            return

        match_result = self.find_session_in_recent_multipliers(recent_page)

        if match_result:
            session_id, match_pos, missing_rounds = match_result
            self.db.current_session_id = session_id
            self.log(f"✓ Continuing session #{session_id}")

            if missing_rounds:
                last_session_info = self.db.session_manager.get_last_session()
                if last_session_info and last_session_info[1]:
                    last_db_time = datetime.fromisoformat(last_session_info[1])
                else:
                    last_db_time = datetime.now() - timedelta(
                        seconds=60 * len(missing_rounds)
                    )

                current_time = datetime.now()

                self.db.session_manager.add_missing_rounds(
                    session_id, missing_rounds, last_db_time, current_time
                )

                self.log(f"✓ Added {len(missing_rounds)} missing rounds")

                if missing_rounds:
                    self.last_seen_multiplier = missing_rounds[-1]
            else:
                if recent_page:
                    self.last_seen_multiplier = recent_page[-1]
        else:
            self.db.current_session_id = self.db.session_manager.create_session(
                start_balance
            )
            self.log(f"✓ Created new session #{self.db.current_session_id}")

            import_all = self.config.get("import_recent_on_new_session", True)

            if import_all and recent_page:
                current_time = datetime.now()
                estimated_start = current_time - timedelta(
                    seconds=30 * len(recent_page)
                )

                self.db.session_manager.add_missing_rounds(
                    self.db.current_session_id,
                    recent_page,
                    estimated_start,
                    current_time,
                )

                self.log(f"✓ Imported {len(recent_page)} rounds")
                self.last_seen_multiplier = recent_page[-1]

        self.log("=" * 60)

    def init_driver(self) -> bool:
        """Initialize Chrome driver with caching"""
        try:
            if not UNDETECTED_AVAILABLE:
                self.log("ERROR: undetected-chromedriver not installed!")
                return False

            self.log("Initializing Chrome driver with cache...")

            # Create cache directory
            cache_dir = Path("./chromedriver_cache")
            cache_dir.mkdir(exist_ok=True)

            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--enable-webgl")
            options.add_argument("--disable-extensions")

            # Use cached driver
            self.driver = uc.Chrome(
                options=options,
                version_main=None,
                use_subprocess=True,
                driver_executable_path=None,  # Auto-download and cache
            )

            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(60)
            self.driver.set_script_timeout(60)
            self.wait = WebDriverWait(self.driver, 60)

            self.log("✓ Driver initialized with cache")
            return True
        except Exception as e:
            self.log(f"Failed to initialize driver: {e}")
            return False

    def login(self) -> bool:
        """Login to website"""
        try:
            self.log("Navigating to login page...")
            self.driver.get("https://1000bet.in")
            time.sleep(5)

            if "cloudflare" in self.driver.page_source.lower():
                self.log("WARNING: Cloudflare detected - waiting...")
                time.sleep(10)

            self.log("Clicking login button...")
            login_btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'a.loginDialog[automation="home_login_button"]')
                )
            )
            login_btn.click()
            time.sleep(2)

            self.log(f"Entering credentials: {self.username}")
            email_input = self.wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[automation="email_input"]')
                )
            )
            password_input = self.driver.find_element(
                By.CSS_SELECTOR, 'input[automation="password_input"]'
            )

            email_input.clear()
            for char in self.username:
                email_input.send_keys(char)
                time.sleep(0.05)
            time.sleep(0.5)

            password_input.clear()
            for char in self.password:
                password_input.send_keys(char)
                time.sleep(0.05)
            time.sleep(0.5)

            submit_btn = self.driver.find_element(
                By.CSS_SELECTOR, 'button[automation="login_button"]'
            )
            submit_btn.click()
            time.sleep(5)

            self.log("✓ Login successful!")
            return True

        except Exception as e:
            self.log(f"Login failed: {e}")
            return False

    def navigate_to_game(self) -> bool:
        """Navigate to game and switch to iframe"""
        try:
            self.log(f"Loading game: {self.game_url}")
            self.driver.get(self.game_url)
            time.sleep(5)

            self.log("Waiting for game iframe...")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )

            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            self.log(f"Found {len(iframes)} iframe(s)")

            if len(iframes) == 0:
                self.log("ERROR: No iframes found!")
                return False

            game_iframe = None
            for i, iframe in enumerate(iframes):
                iframe_src = iframe.get_attribute("src")
                if iframe_src and len(iframe_src) > 50:
                    game_iframe = iframe
                    break

            if not game_iframe:
                self.log("ERROR: Could not find game iframe!")
                return False

            self.driver.switch_to.frame(game_iframe)
            time.sleep(5)

            nested_iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if len(nested_iframes) > 0:
                self.driver.switch_to.frame(nested_iframes[0])
                self.log("✓ Switched to nested iframe")
                time.sleep(3)

            self.wait_for_dynamic_content()
            self.close_tutorial_popup()

            self.log("✓ Game loaded successfully!")
            return True

        except Exception as e:
            self.log(f"Failed to load game: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def wait_for_dynamic_content(self, max_wait: int = 40):
        """Wait for game elements using Python DOM"""
        try:
            start_time = time.time()
            last_visible_count = 0
            stable_count = 0

            while time.time() - start_time < max_wait:
                try:
                    # Use Python to find visible buttons
                    buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    visible_buttons = [btn for btn in buttons if btn.is_displayed()]
                    current_visible = len(visible_buttons)

                    if current_visible > last_visible_count:
                        last_visible_count = current_visible
                        stable_count = 0
                    elif current_visible == last_visible_count and current_visible > 3:
                        stable_count += 1
                        if stable_count >= 3:
                            time.sleep(2)
                            return True

                    time.sleep(1)
                except:
                    time.sleep(1)

            return False
        except:
            return False

    def close_tutorial_popup(self):
        """Close tutorial popup using Python DOM"""
        try:
            for attempt in range(30):
                buttons = self.driver.find_elements(By.CLASS_NAME, "Qthei")
                if buttons and len(buttons) > 0:
                    buttons[0].click()
                    self.log("✓ Tutorial popup closed")
                    time.sleep(2)
                    return
                time.sleep(1)
        except:
            pass

    def verify_and_setup_auto_cashout(
        self, strategy: StrategyState, max_retries: int = 2
    ) -> bool:
        """
        CRITICAL: Always verify auto-cashout before betting!
        Returns True only if auto-cashout is correctly set
        """
        for retry_attempt in range(max_retries):
            try:
                if retry_attempt > 0:
                    self.log(
                        f"[{strategy.name}] Retry {retry_attempt + 1}/{max_retries}"
                    )
                    time.sleep(0.5)

                # Step 1: Get current auto-cashout value using Python DOM
                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                if not panels:
                    raise Exception("Bet panel not found")

                auto_input = panels[0].find_element(
                    By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]'
                )
                current_value = auto_input.get_attribute("value")

                try:
                    current_cashout = float(current_value) if current_value else 0.0
                except ValueError:
                    current_cashout = 0.0

                # Step 2: Check if already correct
                if abs(current_cashout - strategy.auto_cashout) < 0.01:
                    self.log(
                        f"[{strategy.name}] ✓ Auto-cashout already set: {current_cashout}x"
                    )
                    return True

                # Step 3: Need to set it - click AUTO button
                self.log(
                    f"[{strategy.name}] Setting auto-cashout: {current_cashout}x → {strategy.auto_cashout}x"
                )

                buttons = panels[0].find_elements(By.TAG_NAME, "button")
                auto_button_clicked = False

                for btn in buttons:
                    if btn.is_displayed():
                        btn_text = btn.text.strip().lower()
                        if btn_text == "auto" or btn_text == "stop":
                            btn.click()
                            auto_button_clicked = True
                            break

                if not auto_button_clicked:
                    raise Exception("AUTO button not found")

                time.sleep(0.1)

                # Step 4: Enable auto-cashout toggle
                toggle = panels[0].find_element(
                    By.CSS_SELECTOR, 'input[data-testid="aut-co-tgl"]'
                )
                if not toggle.is_selected():
                    toggle.click()
                    time.sleep(0.1)

                # Step 5: Set the value
                from selenium.webdriver.common.action_chains import ActionChains
                from selenium.webdriver.common.keys import Keys

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", auto_input
                )
                time.sleep(0.05)

                actions = ActionChains(self.driver)
                actions.move_to_element(auto_input).click().perform()
                time.sleep(0.05)

                # Clear and type new value
                for _ in range(5):
                    auto_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.05)

                auto_input.send_keys(str(strategy.auto_cashout))
                time.sleep(0.05)

                # Step 6: VERIFY the value was set correctly
                final_value = auto_input.get_attribute("value")

                try:
                    final_cashout = float(final_value)
                except ValueError:
                    raise Exception(f"Invalid final value: {final_value}")

                if abs(final_cashout - strategy.auto_cashout) < 0.01:
                    self.log(
                        f"[{strategy.name}] ✓ Auto-cashout verified: {final_cashout}x"
                    )
                    return True
                else:
                    self.log(
                        f"[{strategy.name}] ⚠ Verification failed: expected {strategy.auto_cashout}x, got {final_cashout}x"
                    )
                    if retry_attempt < max_retries - 1:
                        continue
                    return False

            except Exception as e:
                self.log(f"[{strategy.name}] Setup error: {str(e)[:200]}")
                if retry_attempt == max_retries - 1:
                    return False

        return False

    def get_bettor_count(self) -> Optional[int]:
        """Get number of bettors using Python DOM"""
        try:
            span = self.driver.find_element(
                By.CSS_SELECTOR, 'span[data-testid="b-ct-spn"]'
            )
            count_text = span.text
            if count_text and count_text.strip().isdigit():
                return int(count_text)
            return None
        except:
            return None

    def get_bank_balance(self) -> Optional[float]:
        """Get current bank balance using Python DOM"""
        try:
            balance_div = self.driver.find_element(By.ID, "lblBalance")
            balance_text = balance_div.text
            if balance_text:
                balance_str = (
                    balance_text.strip()
                    .replace("IRT", "")
                    .replace(",", "")
                    .replace(" ", "")
                )
                try:
                    return float(balance_str)
                except ValueError:
                    return None
            return None
        except:
            return None

    def get_round_state(self) -> str:
        """
        Detect current round state
        Returns: 'betting', 'active', 'crashed', 'unknown'
        """
        try:
            # Check bet button text/state
            bet_button = self.driver.find_element(
                By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
            )
            button_text = bet_button.text.lower()

            # Check for disabled class
            button_classes = bet_button.get_attribute("class") or ""
            parent = bet_button.find_element(By.XPATH, "..")
            parent_classes = parent.get_attribute("class") or ""

            is_disabled = (
                "disabled" in button_classes.lower()
                or "disabled" in parent_classes.lower()
            )

            # Check main multiplier element
            try:
                main_mult = self.driver.find_element(By.CSS_SELECTOR, "span.ZmRXV")
                mult_classes = main_mult.get_attribute("class") or ""

                # 'false' in classes usually means crashed/ended
                has_ended = "false" in mult_classes
            except:
                has_ended = False

            # Determine state
            if "bet" in button_text and not is_disabled:
                return "betting"  # Can place bets
            elif is_disabled and not has_ended:
                return "active"  # Round is active (flying)
            elif has_ended:
                return "crashed"  # Round just ended
            else:
                return "unknown"

        except Exception as e:
            return "unknown"

    def detect_current_multiplier(self) -> Optional[Tuple[float, str]]:
        """
        Detect ended round multiplier using Python DOM (faster than JS)
        Returns: (multiplier, round_id) or None

        Round ID helps identify unique rounds even with duplicate multipliers
        """
        try:
            main_mult = self.driver.find_element(By.CSS_SELECTOR, "span.ZmRXV")

            if not main_mult:
                return None

            text = main_mult.text.strip()
            class_list = main_mult.get_attribute("class")

            # Check if round has ended
            has_ended = "false" in class_list

            # Check if we can bet (means round ended)
            try:
                bet_button = self.driver.find_element(
                    By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
                )
                can_bet = "bet" in bet_button.text.lower()

                # Also check not disabled
                button_classes = bet_button.get_attribute("class") or ""
                parent = bet_button.find_element(By.XPATH, "..")
                parent_classes = parent.get_attribute("class") or ""
                not_disabled = (
                    "disabled" not in button_classes.lower()
                    and "disabled" not in parent_classes.lower()
                )

                can_bet = can_bet and not_disabled
            except:
                can_bet = False

            round_ended = has_ended and can_bet

            if not round_ended:
                return None

            if "x" in text.lower():
                import re

                match = re.search(r"(\d+\.?\d*)x", text, re.IGNORECASE)
                if match:
                    mult = float(match.group(1))
                    if 1.0 <= mult <= 10000.0:
                        # Generate round ID from timestamp + multiplier + bettor count
                        # This ensures unique identification even for duplicate multipliers
                        current_time = time.time()

                        # Try to get bettor count for uniqueness
                        bettor_count = self.get_bettor_count() or 0

                        # Create unique round ID
                        round_id = f"{int(current_time)}_{mult}_{bettor_count}"

                        return (mult, round_id)
            return None
        except:
            return None

    def check_trigger(self, strategy: StrategyState) -> bool:
        """Check if trigger conditions are met for a strategy"""
        # Manual trigger overrides conditions
        if strategy.manual_trigger:
            self.log(f"[{strategy.name}] MANUAL TRIGGER ACTIVATED")
            return True

        recent = self.db.get_recent_multipliers(strategy.trigger_count)

        if len(recent) != strategy.trigger_count:
            return False

        all_under = all(m < strategy.trigger_threshold for m in recent)

        if all_under:
            self.log(
                f"[{strategy.name}] AUTO TRIGGER: Last {strategy.trigger_count} rounds under {strategy.trigger_threshold}x"
            )
            return True

        return False

    def is_betting_window_open(self) -> bool:
        """
        Check if betting window is currently open (not disabled)
        Returns True if we can place bets, False if window is closed
        """
        try:
            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                return False

            # Check if bet button is disabled
            bet_button = panels[0].find_element(
                By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
            )

            # Check for 'disabled' class on button or parent container
            button_classes = bet_button.get_attribute("class") or ""

            # Also check parent container
            parent = bet_button.find_element(By.XPATH, "..")
            parent_classes = parent.get_attribute("class") or ""

            # If either has 'disabled' in classes, betting window is closed
            if (
                "disabled" in button_classes.lower()
                or "disabled" in parent_classes.lower()
            ):
                return False

            # Additional check: try to see if button is actually clickable
            if not bet_button.is_displayed() or not bet_button.is_enabled():
                return False

            return True

        except Exception as e:
            # If we can't find elements, assume window is closed
            return False

    def wait_for_betting_window(
        self, timeout: int = 10, strategy_name: str = ""
    ) -> bool:
        """
        Wait for betting window to open (max timeout seconds)
        Returns True if window opened, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.is_betting_window_open():
                return True
            time.sleep(0.1)

        self.log(f"[{strategy_name}] ⚠ Timeout waiting for betting window")
        return False

    def place_bet(
        self, strategy: StrategyState, amount: float, max_retries: int = 2
    ) -> bool:
        """
        Place a bet - ONLY after auto-cashout verification!
        Includes betting window detection and retry logic
        """
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.log(f"[{strategy.name}] Retry {attempt + 1}/{max_retries}")
                    time.sleep(1)

                # CRITICAL: Check if betting window is open
                if not self.is_betting_window_open():
                    self.log(f"[{strategy.name}] Betting window closed, waiting...")

                    # Wait up to 10 seconds for window to open
                    if not self.wait_for_betting_window(
                        timeout=10, strategy_name=strategy.name
                    ):
                        if attempt < max_retries - 1:
                            continue
                        else:
                            self.log(
                                f"[{strategy.name}] ✗ Cannot place bet - window remained closed"
                            )
                            return False

                    self.log(f"[{strategy.name}] ✓ Betting window opened")

                from selenium.webdriver.common.keys import Keys

                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                if not panels:
                    raise Exception("Bet panel not found")

                # Enter bet amount
                bet_input = panels[0].find_element(
                    By.CSS_SELECTOR, 'input[data-testid="bp-inp"]'
                )

                # Double-check input is not disabled
                input_parent = bet_input.find_element(By.XPATH, "..")
                if "disabled" in (input_parent.get_attribute("class") or "").lower():
                    raise Exception("Bet input is disabled")

                bet_input.click()
                time.sleep(0.05)

                for _ in range(8):
                    bet_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.05)

                bet_input.send_keys(str(int(amount)))
                time.sleep(0.05)

                # Get bet button and verify it's clickable
                bet_button = panels[0].find_element(
                    By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
                )

                # Final check before clicking
                if not self.is_betting_window_open():
                    raise Exception("Betting window closed before click")

                # Use JavaScript click as fallback for intercepted clicks
                try:
                    bet_button.click()
                except Exception as click_error:
                    if "click intercepted" in str(click_error).lower():
                        self.log(
                            f"[{strategy.name}] Click intercepted, using JavaScript click"
                        )
                        self.driver.execute_script("arguments[0].click();", bet_button)
                    else:
                        raise

                time.sleep(0.1)

                self.log(f"[{strategy.name}] ✓ BET PLACED: {amount}")
                return True

            except Exception as e:
                error_msg = str(e)

                # Check for specific errors
                if "disabled" in error_msg.lower():
                    self.log(
                        f"[{strategy.name}] Betting panel disabled (round starting soon)"
                    )
                elif "click intercepted" in error_msg.lower():
                    self.log(f"[{strategy.name}] Click intercepted by overlay")
                elif "not clickable" in error_msg.lower():
                    self.log(f"[{strategy.name}] Button not clickable")
                else:
                    self.log(f"[{strategy.name}] Bet error: {error_msg[:200]}")

                # If last attempt, return failure
                if attempt == max_retries - 1:
                    return False

                # Otherwise, wait and retry
                time.sleep(1)

        return False

    def handle_result(self, strategy: StrategyState, multiplier: float):
        """Handle bet result for a strategy"""
        if multiplier >= strategy.auto_cashout:
            profit = strategy.current_bet * (strategy.auto_cashout - 1)
            strategy.total_profit += profit
            self.total_profit += profit
            self.db.add_bet(
                strategy.name, strategy.current_bet, "win", multiplier, profit
            )

            self.log(
                f"[{strategy.name}] ✓ WIN! {multiplier}x | Profit: +{profit:.0f} | Total: {self.total_profit:.0f}"
            )

            strategy.reset()
        else:
            loss = strategy.current_bet
            strategy.total_profit -= loss
            self.total_profit -= loss
            self.db.add_bet(
                strategy.name, strategy.current_bet, "loss", multiplier, -loss
            )
            strategy.consecutive_losses += 1
            strategy.current_bet = strategy.calc_next_bet()

            self.log(
                f"[{strategy.name}] ✗ LOSS! {multiplier}x | Loss: -{loss:.0f} | Total: {self.total_profit:.0f}"
            )
            self.log(
                f"[{strategy.name}]    Losses: {strategy.consecutive_losses} | Next bet: {strategy.current_bet:.0f}"
            )

        strategy.waiting_for_result = False

    def check_stop_conditions(self) -> bool:
        """Check if we should stop"""
        if self.total_profit <= -self.max_loss:
            self.log(f"STOP: Max loss reached ({abs(self.total_profit):.0f})")
            return False

        for name, strategy in self.strategies.items():
            if strategy.consecutive_losses >= strategy.max_consecutive_losses:
                self.log(
                    f"STOP: [{name}] Max consecutive losses ({strategy.consecutive_losses})"
                )
                return False

        return True

    def run(self):
        """Main bot loop - Production optimized"""
        try:
            self.log("=" * 60)
            self.log("CRASHER BOT - PRODUCTION OPTIMIZED")
            self.log("=" * 60)

            if not self.init_driver():
                return

            if not self.login():
                return

            if not self.navigate_to_game():
                return

            time.sleep(2)
            start_balance = self.get_bank_balance()

            self.recover_or_create_session(start_balance)

            self.prediction_analyzer = PredictionAnalyzer(self.db.conn, self.log)
            self.log("✓ Prediction analyzer initialized")

            self.log("=" * 60)
            self.log("ACTIVE STRATEGIES:")
            for name, strategy in self.strategies.items():
                self.log(
                    f"  [{name}] Trigger: {strategy.trigger_count} < {strategy.trigger_threshold}x | Cashout: {strategy.auto_cashout}x"
                )
            self.log("=" * 60)
            self.log("BOT RUNNING - Auto-reload enabled, Python DOM parsing active")
            self.log("=" * 60)

            self.running = True
            active_strategy_name = None
            last_logged_time = {}

            while self.running:
                # Check for config/strategy changes
                self.reload_strategies_if_changed()

                if not self.check_stop_conditions():
                    break

                # Detect multiplier with round ID
                round_result = self.detect_current_multiplier()

                if round_result:
                    new_mult, round_id = round_result

                    # Check if this is a new round (different round ID)
                    if round_id != self.last_round_id:
                        current_time = time.time()

                        # Additional safeguard: minimum 3 seconds between rounds
                        time_since_last_round = current_time - self.last_round_time
                        if self.last_round_time > 0 and time_since_last_round < 3.0:
                            time.sleep(0.1)
                            continue

                        # Update tracking
                        self.last_seen_multiplier = new_mult
                        self.last_round_id = round_id
                        self.last_round_time = current_time
                        self.rounds_since_setup += 1

                        bettor_count = self.get_bettor_count()
                        bank_balance = self.get_bank_balance()

                        log_parts = [f"Round ended: {new_mult}x"]
                        if bettor_count:
                            log_parts.append(f"Bettors: {bettor_count}")
                        if bank_balance is not None:
                            log_parts.append(f"Bank: {bank_balance:,.0f}")

                        self.log(" | ".join(log_parts))
                        self.db.add_multiplier(new_mult, bettor_count)cursor = self.db.conn.cursor()
                        cursor.execute("SELECT last_insert_rowid()")
                        current_mult_id = cursor.fetchone()[0]

                        # Run prediction analysis (only if no strategy is active)
                        if not self.strategy_active and not active_strategy_name:
                            try:
                                self.analyze_and_log_predictions(current_mult_id)
                            except Exception as e:
                                self.log(f"Prediction analysis error: {e}")

                    # Handle result for active strategy
                    if active_strategy_name:
                        active_strategy = self.strategies[active_strategy_name]
                        if active_strategy.waiting_for_result:
                            self.handle_result(active_strategy, new_mult)

                            if not active_strategy.waiting_for_result:
                                self.log(
                                    f"[{active_strategy_name}] Strategy cycle complete"
                                )
                                active_strategy_name = None

                    # Check for new strategy triggers
                    if not active_strategy_name:
                        for name, strategy in self.strategies.items():
                            if not strategy.waiting_for_result and self.check_trigger(
                                strategy
                            ):
                                self.log(f"[{name}] ⚡ STRATEGY ACTIVATED")

                                # Check round state before proceeding
                                round_state = self.get_round_state()
                                self.log(f"[{name}] Round state: {round_state}")

                                if round_state not in ["betting", "crashed"]:
                                    self.log(
                                        f"[{name}] Waiting for betting window (state: {round_state})..."
                                    )
                                    # Wait for betting window to open
                                    if not self.wait_for_betting_window(
                                        timeout=15, strategy_name=name
                                    ):
                                        self.log(
                                            f"[{name}] ✗ Betting window timeout, will retry next round"
                                        )
                                        strategy.manual_trigger = False
                                        continue

                                # CRITICAL: Verify auto-cashout BEFORE betting!
                                if not self.verify_and_setup_auto_cashout(strategy):
                                    self.log(
                                        f"[{name}] ✗ ABORTED - Auto-cashout verification failed!"
                                    )
                                    strategy.manual_trigger = False
                                    continue

                                # Small delay after auto-cashout setup
                                time.sleep(0.3)

                                # Double-check betting window is still open
                                if not self.is_betting_window_open():
                                    self.log(
                                        f"[{name}] ✗ Betting window closed after auto-cashout setup"
                                    )
                                    strategy.manual_trigger = False
                                    continue

                                bet_amount = strategy.calc_next_bet()

                                if self.place_bet(strategy, bet_amount):
                                    strategy.current_bet = bet_amount
                                    strategy.waiting_for_result = True
                                    active_strategy_name = name
                                    strategy.manual_trigger = False
                                    break
                                else:
                                    self.log(
                                        f"[{name}] ✗ Failed to place bet, will retry next round"
                                    )
                                    strategy.manual_trigger = False

                time.sleep(0.1)

        except KeyboardInterrupt:
            self.log("\n⏹ Bot stopped by user")
        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback

            self.log(traceback.format_exc())
        finally:
            self.running = False

            if self.db.current_session_id:
                final_balance = self.get_bank_balance()
                self.db.session_manager.update_session_end(
                    self.db.current_session_id, final_balance
                )

            self.log("=" * 60)
            self.log("SESSION SUMMARY:")
            self.log(f"   Session ID: {self.db.current_session_id}")
            self.log(f"   Total Profit/Loss: {self.total_profit:.0f}")

            for name, strategy in self.strategies.items():
                self.log(
                    f"   [{name}]: P/L={strategy.total_profit:.0f}, Losses={strategy.consecutive_losses}"
                )

            try:
                final_balance = self.get_bank_balance()
                if final_balance is not None:
                    self.log(f"   Final Balance: {final_balance:,.0f}")
            except:
                pass

            self.log("=" * 60)

            if self.driver:
                self.driver.quit()
            self.db.close()
            self.log("✓ Bot shut down cleanly")


# Global instance for API access
_bot_instance: Optional[MultiStrategyCrasherBot] = None


def get_bot_instance() -> Optional[MultiStrategyCrasherBot]:
    """Get global bot instance"""
    return _bot_instance


def set_bot_instance(bot: Optional[MultiStrategyCrasherBot]):
    """Set global bot instance"""
    global _bot_instance
    _bot_instance = bot


def main():
    try:
        bot = MultiStrategyCrasherBot(config_path="./bot_config.json")
        set_bot_instance(bot)
        bot.run()
    except FileNotFoundError:
        logger.error("Config file 'bot_config.json' not found!")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        set_bot_instance(None)


if __name__ == "__main__":
    main()
