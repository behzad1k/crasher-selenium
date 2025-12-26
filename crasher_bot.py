#!/usr/bin/env python3
"""
Crasher Bot - Enhanced with Session Recovery
Reads recent multipliers from page and matches with database to continue sessions
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

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

    def reset(self):
        """Reset strategy state after win"""
        self.current_bet = self.base_bet
        self.consecutive_losses = 0
        self.waiting_for_result = False

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

        # Check if multipliers table has session_id column
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

        # First, check if we have any sessions at all
        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]

        if session_count == 0:
            # No sessions exist yet - check if we have old multipliers without session_id
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
                # Create a session for old data
                cursor.execute("""
                    INSERT INTO sessions (start_timestamp, end_timestamp)
                    VALUES (
                        (SELECT MIN(timestamp) FROM multipliers WHERE session_id IS NULL),
                        (SELECT MAX(timestamp) FROM multipliers WHERE session_id IS NULL)
                    )
                """)
                new_session_id = cursor.lastrowid

                # Assign old multipliers to this session
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

                # Now fall through to normal query

        # Get the last session without end_timestamp (active session)
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

        # Reverse to get chronological order (oldest to newest)
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
        """
        Add missing rounds to database with estimated timestamps

        Args:
            session_id: Session to add rounds to
            multipliers: List of multipliers (chronological order)
            start_time: Time of first missing round (estimate)
            end_time: Time of last missing round (actual)
        """
        if not multipliers:
            return

        cursor = self.conn.cursor()

        # Calculate time per round
        total_seconds = (end_time - start_time).total_seconds()
        seconds_per_round = (
            total_seconds / len(multipliers) if len(multipliers) > 1 else 0
        )

        # Insert each missing round with estimated timestamp
        for i, mult in enumerate(multipliers):
            # Calculate timestamp for this round
            if i == len(multipliers) - 1:
                # Last round uses actual end_time
                timestamp = end_time
            else:
                # Estimate timestamp
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
                # Skip if duplicate (shouldn't happen, but just in case)
                pass

        self.conn.commit()


class Database:
    """Database for tracking bets and multipliers"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()
        # Will be set by bot after initialization
        self.log_func = None
        self.session_manager = None  # Initialize later with log function
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
    """Crasher bot with session recovery"""

    def __init__(self, config_path: str = "./bot_config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        self.max_loss = float(self.config.get("max_loss", 100000000))

        # Load strategies
        self.strategies: Dict[str, StrategyState] = {}
        self._load_strategies()

        # Bot state
        self.driver = None
        self.wait = None
        self.db = Database()
        self.db.set_logger(self.log)  # Set logger after db creation
        self.last_seen_multiplier = None
        self.last_round_time = 0  # Track time of last logged round
        self.running = False
        self.auto_cashout_configured = {}
        self.rounds_since_setup = 0
        self.total_profit = 0.0

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
        """
        Read recent multipliers from the page's result div
        Returns list in chronological order (oldest to newest)
        """
        try:
            script = """
            var resultItems = document.querySelectorAll('span.sc-w0koce-1.giBFzM');
            var multipliers = [];

            for (var i = 0; i < resultItems.length; i++) {
                var text = resultItems[i].textContent.trim();
                if (text.endsWith('x')) {
                    var value = parseFloat(text.replace('x', ''));
                    if (!isNaN(value)) {
                        multipliers.push(value);
                    }
                }
            }

            // Return in reverse order (oldest to newest)
            return multipliers.reverse();
            """

            multipliers = self.driver.execute_script(script)

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
        """
        Try to find last session's data in recent multipliers from page

        Args:
            recent_page: Recent multipliers from page (oldest to newest)
            min_consecutive: Minimum consecutive matches required

        Returns:
            (session_id, match_position, missing_multipliers) or None
            match_position is the index in recent_page where the match was found
        """
        last_session = self.db.session_manager.get_last_session()

        if not last_session:
            self.log("No previous session found in database")
            return None

        session_id, last_timestamp, round_count = last_session

        self.log(f"Found session #{session_id} with {round_count} rounds")
        self.log(f"  Last timestamp: {last_timestamp}")

        if round_count == 0:
            self.log(f"Last session #{session_id} is empty, will continue it")
            return (session_id, 0, recent_page)

        self.log(f"Searching for session #{session_id} in recent multipliers...")

        # Try different pattern lengths, starting from longest
        max_pattern = min(round_count, 20)
        self.log(
            f"  Will try pattern lengths from {max_pattern} down to {min_consecutive}"
        )

        for pattern_length in range(max_pattern, min_consecutive - 1, -1):
            db_pattern = self.db.session_manager.get_last_n_multipliers_from_session(
                session_id, pattern_length
            )

            if not db_pattern:
                continue

            self.log(
                f"  Trying pattern of {pattern_length} rounds: {db_pattern[:3]}...{db_pattern[-3:] if len(db_pattern) > 3 else ''}"
            )

            # Search for this pattern in recent_page
            for i in range(len(recent_page) - pattern_length + 1):
                page_slice = recent_page[i : i + pattern_length]

                # Check if patterns match (with small tolerance for floating point)
                matches = [abs(a - b) < 0.01 for a, b in zip(db_pattern, page_slice)]

                if all(matches):
                    # Found match!
                    match_end_pos = i + pattern_length
                    missing_rounds = recent_page[match_end_pos:]

                    self.log(f"✓ Found session match!")
                    self.log(f"  Pattern length: {pattern_length} rounds")
                    self.log(f"  Match position: {i} to {match_end_pos - 1}")
                    self.log(f"  DB pattern: {db_pattern[:5]}...")
                    self.log(f"  Page match: {page_slice[:5]}...")
                    self.log(f"  Missing rounds: {len(missing_rounds)}")

                    if missing_rounds:
                        self.log(
                            f"  Missing range: {min(missing_rounds):.2f}x to {max(missing_rounds):.2f}x"
                        )

                    return (session_id, match_end_pos, missing_rounds)

                # Debug: Show why first attempt didn't match
                if i == 0 and pattern_length == max_pattern:
                    mismatches = [
                        (a, b)
                        for a, b, m in zip(db_pattern, page_slice, matches)
                        if not m
                    ]
                    if mismatches:
                        self.log(
                            f"    No match at position 0 (mismatches: {mismatches[:3]})"
                        )

        self.log(f"Could not find session #{session_id} in recent multipliers")
        self.log(f"  DB last rounds: {db_pattern[:10] if db_pattern else []}")
        self.log(f"  Page first rounds: {recent_page[:10]}")
        return None

    def recover_or_create_session(self, start_balance: Optional[float] = None):
        """
        Attempt to recover last session or create new one
        """
        self.log("=" * 60)
        self.log("SESSION RECOVERY")
        self.log("=" * 60)

        # Read recent multipliers from page
        recent_page = self.read_recent_multipliers_from_page()

        if not recent_page:
            self.log("⚠️  No recent multipliers on page, creating new session")
            self.db.current_session_id = self.db.session_manager.create_session(
                start_balance
            )
            self.log(f"✓ Created new session #{self.db.current_session_id}")
            return

        # Try to find last session
        match_result = self.find_session_in_recent_multipliers(recent_page)

        if match_result:
            session_id, match_pos, missing_rounds = match_result

            # Continue existing session
            self.db.current_session_id = session_id
            self.log(f"✓ Continuing session #{session_id}")

            if missing_rounds:
                self.log(f"Adding {len(missing_rounds)} missing rounds to database...")

                # Get last timestamp from session
                last_session_info = self.db.session_manager.get_last_session()
                if last_session_info and last_session_info[1]:
                    last_db_time = datetime.fromisoformat(last_session_info[1])
                else:
                    # Fallback: estimate from now
                    last_db_time = datetime.now() - timedelta(
                        seconds=60 * len(missing_rounds)
                    )

                # Current time is now
                current_time = datetime.now()

                # Add missing rounds with estimated timestamps
                self.db.session_manager.add_missing_rounds(
                    session_id, missing_rounds, last_db_time, current_time
                )

                self.log(f"✓ Added {len(missing_rounds)} missing rounds")
                self.log(f"  Time range: {last_db_time} to {current_time}")

                # Set last seen to the most recent
                if missing_rounds:
                    self.last_seen_multiplier = missing_rounds[-1]
            else:
                self.log("✓ No missing rounds, database is up to date")

                # Set last seen to most recent from page
                if recent_page:
                    self.last_seen_multiplier = recent_page[-1]
        else:
            # Create new session
            self.db.current_session_id = self.db.session_manager.create_session(
                start_balance
            )
            self.log(f"✓ Created new session #{self.db.current_session_id}")

            # Optionally, import all recent rounds from page
            import_all = self.config.get("import_recent_on_new_session", True)

            if import_all and recent_page:
                self.log(f"Importing {len(recent_page)} recent rounds from page...")

                # Estimate timestamps (assume 30 seconds per round average)
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

                # Set last seen
                self.last_seen_multiplier = recent_page[-1]

        self.log("=" * 60)

    def init_driver(self) -> bool:
        """Initialize undetected Chrome driver"""
        try:
            if not UNDETECTED_AVAILABLE:
                self.log("ERROR: undetected-chromedriver not installed!")
                return False

            self.log("Initializing Chrome driver...")
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--enable-webgl")
            options.add_argument("--disable-extensions")

            self.driver = uc.Chrome(
                options=options, version_main=None, use_subprocess=True
            )
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.driver.set_script_timeout(15)
            self.wait = WebDriverWait(self.driver, 30)

            self.log("OK Driver initialized")
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

            self.log("OK Login successful!")
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
            self.log(f"Found {len(iframes)} iframe(s) on main page")

            if len(iframes) == 0:
                self.log("ERROR: No iframes found!")
                return False

            game_iframe = None
            for i, iframe in enumerate(iframes):
                iframe_src = iframe.get_attribute("src")
                if iframe_src and len(iframe_src) > 50:
                    game_iframe = iframe
                    self.log(f"Found game iframe at index {i}")
                    break

            if not game_iframe:
                self.log("ERROR: Could not find game iframe!")
                return False

            self.driver.switch_to.frame(game_iframe)
            time.sleep(5)

            nested_iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if len(nested_iframes) > 0:
                self.driver.switch_to.frame(nested_iframes[0])
                self.log("OK Switched to nested iframe")
                time.sleep(3)

            self.wait_for_dynamic_content()
            self.close_tutorial_popup()

            self.log("OK Game loaded successfully!")
            return True

        except Exception as e:
            self.log(f"Failed to load game: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def wait_for_dynamic_content(self, max_wait: int = 40):
        """Wait for game elements"""
        try:
            start_time = time.time()
            last_visible_count = 0
            stable_count = 0

            script = """
            var buttons = document.querySelectorAll('button');
            var visibleButtons = [];
            for (var i = 0; i < buttons.length; i++) {
                var btn = buttons[i];
                var isVisible = btn.offsetParent !== null;
                if (isVisible) {
                    visibleButtons.push({text: btn.textContent.trim()});
                }
            }
            return visibleButtons;
            """

            while time.time() - start_time < max_wait:
                try:
                    visible_buttons = self.driver.execute_script(script)
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
        """Close tutorial popup if it appears"""
        try:
            for attempt in range(30):
                script = """
                var buttons = document.getElementsByClassName('Qthei');
                if (buttons.length > 0) {
                    buttons[0].click();
                    return true;
                }
                return false;
                """
                if self.driver.execute_script(script):
                    self.log("OK Tutorial popup closed")
                    time.sleep(2)
                    return
                time.sleep(1)
        except:
            pass

    def setup_auto_cashout(self, strategy: StrategyState, max_retries: int = 3) -> bool:
        """Setup auto cashout for a specific strategy"""
        for retry_attempt in range(max_retries):
            try:
                if retry_attempt > 0:
                    self.log(
                        f"[{strategy.name}] Retry attempt {retry_attempt + 1}/{max_retries}"
                    )
                    time.sleep(2)

                auto_script = """
                try {
                    var panels = document.querySelectorAll('div[data-singlebetpart]');
                    var firstPanel = panels[0];
                    var buttons = firstPanel.querySelectorAll('button');
                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        if (btn.offsetParent !== null) {
                            if(btn.textContent.trim().toLowerCase() === 'auto'){
                                btn.click();
                                return {clicked: true};
                            }
                            else if (btn.textContent.trim().toLowerCase() === 'stop'){
                                return {clicked: true};
                            }
                        }
                    }
                    return {clicked: false};
                } catch(e) {
                    return {clicked: false, error: e.toString()};
                }
                """

                result = self.driver.execute_script(auto_script)
                if not result.get("clicked"):
                    raise Exception("AUTO button not found")

                time.sleep(0.2)

                toggle_script = """
                try {
                    var panels = document.querySelectorAll('div[data-singlebetpart]');
                    var toggle = panels[0].querySelector('input[data-testid="aut-co-tgl"]');
                    if (toggle && !toggle.checked) {
                        toggle.click();
                    }
                    return {found: toggle !== null};
                } catch(e) {
                    return {found: false};
                }
                """

                self.driver.execute_script(toggle_script)
                time.sleep(0.2)

                from selenium.webdriver.common.action_chains import ActionChains
                from selenium.webdriver.common.keys import Keys

                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                auto_input = panels[0].find_element(
                    By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]'
                )

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", auto_input
                )
                time.sleep(0.1)

                actions = ActionChains(self.driver)
                actions.move_to_element(auto_input).click().perform()
                time.sleep(0.1)

                for _ in range(5):
                    auto_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.1)

                auto_input.send_keys(str(strategy.auto_cashout))
                time.sleep(0.1)

                final_value = auto_input.get_attribute("value")

                if abs(float(final_value) - strategy.auto_cashout) < 0.01:
                    self.log(f"[{strategy.name}] ✓ Auto cashout set to {final_value}x")
                    self.auto_cashout_configured[strategy.name] = True
                    return True
                else:
                    self.log(
                        f"[{strategy.name}] WARNING: Expected {strategy.auto_cashout}, got {final_value}"
                    )
                    if retry_attempt < max_retries - 1:
                        continue
                    return False

            except Exception as e:
                self.log(f"[{strategy.name}] Setup error: {str(e)[:100]}")
                if retry_attempt == max_retries - 1:
                    return False

        return False

    def get_bettor_count(self) -> Optional[int]:
        """Get number of bettors"""
        try:
            script = """
            var span = document.querySelector('span[data-testid="b-ct-spn"]');
            return span ? span.textContent : null;
            """
            count_text = self.driver.execute_script(script)
            if count_text and str(count_text).strip().isdigit():
                return int(count_text)
            return None
        except:
            return None

    def get_bank_balance(self) -> Optional[float]:
        """Get current bank balance from lblBalance div"""
        try:
            script = """
            var balanceDiv = document.getElementById('lblBalance');
            return balanceDiv ? balanceDiv.textContent : null;
            """
            balance_text = self.driver.execute_script(script)
            if balance_text:
                # Remove 'IRT', commas, and any extra whitespace
                balance_str = (
                    str(balance_text)
                    .strip()
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

    def detect_current_multiplier(self) -> Optional[float]:
        """Detect current/ended round multiplier - only returns when round has truly ended"""
        try:
            script = """
            var mainMult = document.querySelector('span.ZmRXV');
            if (!mainMult) {
                return {found: false};
            }

            var text = mainMult.textContent.trim();
            var classList = mainMult.className;

            // Check if round has ended
            // When round is active, the className typically contains 'true'
            // When round has ended (crashed), it contains 'false'
            var hasEnded = classList.includes('false');

            // Additional check: look for "CRASHED" or similar indicators
            var crashedElement = document.querySelector('span.sc-w0koce-1') ||
                                 document.querySelector('[class*="crashed"]') ||
                                 document.querySelector('[class*="Crashed"]');

            // Also check if there's a "BETTING" or "WAITING" state indicator
            var bettingActive = document.querySelector('button[data-testid="b-btn"]');
            var isBetting = bettingActive && bettingActive.textContent.toLowerCase().includes('bet');

            // Round has ended if:
            // 1. hasEnded flag is true, AND
            // 2. We're in betting state (can place bets for next round)
            var roundEnded = hasEnded && isBetting;

            return {
                text: text,
                hasEnded: roundEnded,
                className: classList,
                isBetting: isBetting,
                debugInfo: {
                    hasEndedFlag: hasEnded,
                    canBet: isBetting,
                    finalDecision: roundEnded
                }
            };
            """

            result = self.driver.execute_script(script)

            if not result.get(
                "found", True
            ):  # Default to True if 'found' not in result
                return None

            if not result.get("hasEnded"):
                return None

            text = result.get("text", "")
            if "x" in text.lower():
                import re

                match = re.search(r"(\d+\.?\d*)x", text, re.IGNORECASE)
                if match:
                    mult = float(match.group(1))
                    if 1.0 <= mult <= 10000.0:
                        return mult
            return None
        except Exception as e:
            # Silently ignore errors during detection (common during transitions)
            return None

    def check_trigger(self, strategy: StrategyState) -> bool:
        """Check if trigger conditions are met for a strategy"""
        recent = self.db.get_recent_multipliers(strategy.trigger_count)

        if len(recent) != strategy.trigger_count:
            return False

        all_under = all(m < strategy.trigger_threshold for m in recent)

        if all_under:
            self.log(
                f"[{strategy.name}] TRIGGER: Last {strategy.trigger_count} rounds under {strategy.trigger_threshold}x"
            )
            return True

        return False

    def place_bet(self, strategy: StrategyState, amount: float) -> bool:
        """Place a bet for a strategy"""
        try:
            from selenium.webdriver.common.keys import Keys

            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                return False

            bet_input = panels[0].find_element(
                By.CSS_SELECTOR, 'input[data-testid="bp-inp"]'
            )
            bet_input.click()
            time.sleep(0.1)

            for _ in range(8):
                bet_input.send_keys(Keys.BACKSPACE)
            time.sleep(0.1)

            bet_input.send_keys(str(int(amount)))
            time.sleep(0.1)

            bet_button = panels[0].find_element(
                By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
            )
            bet_button.click()
            time.sleep(0.1)

            self.log(f"[{strategy.name}] BET PLACED: {amount}")
            return True

        except Exception as e:
            self.log(f"[{strategy.name}] Failed to place bet: {e}")
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
                f"[{strategy.name}] ✓ WIN! {multiplier}x | Profit: +{profit:.0f} | Strategy Total: {strategy.total_profit:.0f} | Global Total: {self.total_profit:.0f}"
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
                f"[{strategy.name}] ✗ LOSS! {multiplier}x | Loss: -{loss:.0f} | Strategy Total: {strategy.total_profit:.0f} | Global Total: {self.total_profit:.0f}"
            )
            self.log(
                f"[{strategy.name}]    Consecutive losses: {strategy.consecutive_losses} | Next bet: {strategy.current_bet:.0f}"
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
                    f"STOP: [{name}] Max consecutive losses reached ({strategy.consecutive_losses})"
                )
                return False

        return True

    def run(self):
        """Main bot loop"""
        try:
            self.log("=" * 60)
            self.log("MULTI-STRATEGY CRASHER BOT - ENHANCED")
            self.log("=" * 60)

            if not self.init_driver():
                return

            if not self.login():
                return

            if not self.navigate_to_game():
                return

            # Get initial balance
            time.sleep(2)
            start_balance = self.get_bank_balance()

            # Attempt session recovery
            self.recover_or_create_session(start_balance)

            # Initial setup
            first_strategy = list(self.strategies.values())[0]
            if not self.setup_auto_cashout(first_strategy):
                self.log(f"WARNING: Could not setup initial auto cashout")

            self.log("=" * 60)
            self.log("ACTIVE STRATEGIES:")
            for name, strategy in self.strategies.items():
                self.log(f"  [{name}]")
                self.log(
                    f"    Trigger: {strategy.trigger_count} rounds under {strategy.trigger_threshold}x"
                )
                self.log(f"    Cashout: {strategy.auto_cashout}x")
            self.log("=" * 60)
            self.log("BOT RUNNING - Monitoring multipliers...")
            self.log("=" * 60)

            self.running = True
            active_strategy_name = None
            last_logged_time = {}  # Track when each multiplier was last logged

            while self.running:
                if not self.check_stop_conditions():
                    break

                new_mult = self.detect_current_multiplier()

                if new_mult and new_mult != self.last_seen_multiplier:
                    # Additional safeguards to prevent duplicate logging
                    current_time = time.time()

                    # Safeguard 1: Minimum 3 seconds between rounds
                    time_since_last_round = current_time - self.last_round_time
                    if self.last_round_time > 0 and time_since_last_round < 3.0:
                        # Too soon after last round - likely still detecting ongoing round
                        time.sleep(0.1)
                        continue

                    # Safeguard 2: Don't log same multiplier value within 5 seconds
                    mult_key = f"{new_mult:.2f}"

                    if mult_key in last_logged_time:
                        time_since_last = current_time - last_logged_time[mult_key]
                        if time_since_last < 5.0:
                            # Same multiplier seen within 5 seconds - likely ongoing round
                            time.sleep(0.1)
                            continue

                    # Update tracking
                    last_logged_time[mult_key] = current_time
                    self.last_seen_multiplier = new_mult
                    self.last_round_time = current_time
                    self.rounds_since_setup += 1

                    # Clean up old entries from tracking dict (keep last 10)
                    if len(last_logged_time) > 10:
                        oldest_key = min(last_logged_time, key=last_logged_time.get)
                        del last_logged_time[oldest_key]

                    if self.rounds_since_setup >= 20:
                        self.log("Keeping session active...")
                        self.setup_auto_cashout(first_strategy)
                        self.rounds_since_setup = 0

                    bettor_count = self.get_bettor_count()
                    bank_balance = self.get_bank_balance()

                    log_parts = [f"Round ended: {new_mult}x"]
                    if bettor_count:
                        log_parts.append(f"Bettors: {bettor_count}")
                    if bank_balance is not None:
                        log_parts.append(f"Bank: {bank_balance:,.0f}")

                    self.log(" | ".join(log_parts))
                    self.db.add_multiplier(new_mult, bettor_count)

                    if active_strategy_name:
                        active_strategy = self.strategies[active_strategy_name]
                        if active_strategy.waiting_for_result:
                            self.handle_result(active_strategy, new_mult)

                            if not active_strategy.waiting_for_result:
                                self.log(f"[{active_strategy_name}] Strategy finished")
                                active_strategy_name = None

                    if not active_strategy_name:
                        for name, strategy in self.strategies.items():
                            if not strategy.waiting_for_result and self.check_trigger(
                                strategy
                            ):
                                self.log(f"[{name}] Strategy ACTIVATED")

                                if not self.setup_auto_cashout(strategy):
                                    self.log(
                                        f"[{name}] WARNING: Failed to setup auto-cashout"
                                    )
                                    continue

                                time.sleep(2)
                                bet_amount = strategy.calc_next_bet()

                                if self.place_bet(strategy, bet_amount):
                                    strategy.current_bet = bet_amount
                                    strategy.waiting_for_result = True
                                    active_strategy_name = name
                                    break

                time.sleep(0.1)

        except KeyboardInterrupt:
            self.log("\nBot stopped by user")
        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback

            self.log(traceback.format_exc())
        finally:
            self.running = False

            # Close session
            if self.db.current_session_id:
                final_balance = self.get_bank_balance()
                self.db.session_manager.update_session_end(
                    self.db.current_session_id, final_balance
                )

            self.log("=" * 60)
            self.log("SESSION SUMMARY:")
            self.log(f"   Session ID: {self.db.current_session_id}")
            self.log(f"   Global Total Profit/Loss: {self.total_profit:.0f}")

            for name, strategy in self.strategies.items():
                self.log(f"   [{name}]:")
                self.log(f"     Profit/Loss: {strategy.total_profit:.0f}")
                self.log(f"     Consecutive Losses: {strategy.consecutive_losses}")

            try:
                final_balance = self.get_bank_balance()
                if final_balance is not None:
                    self.log(f"   Final Bank Balance: {final_balance:,.0f}")
            except:
                pass

            self.log("=" * 60)

            if self.driver:
                self.driver.quit()
            self.db.close()
            self.log("Bot shut down")


def main():
    try:
        bot = MultiStrategyCrasherBot(config_path="./bot_config.json")
        bot.run()
    except FileNotFoundError:
        logger.error("Config file 'bot_config.json' not found!")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
