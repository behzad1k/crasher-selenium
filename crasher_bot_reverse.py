#!/usr/bin/env python3
"""
Crasher Bot - Classic Martingale Strategy
Waits for N consecutive rounds >= threshold, then bets expecting to reach cashout target
CRITICAL: Excludes rounds we've bet on from future trigger windows
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

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
        logging.FileHandler("crasher_bot_classic.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class StrategyState:
    """Track state for classic martingale strategy"""

    name: str
    base_bet: float
    auto_cashout: float
    threshold: float  # We wait for rounds >= this
    trigger_count: int
    max_consecutive_losses: int
    bet_multiplier: float

    # Runtime state
    current_bet: float
    consecutive_losses: int  # Track losses for martingale progression
    total_profit: float
    waiting_for_result: bool
    is_active: bool
    excluded_round_ids: Set[int] = field(default_factory=set)  # Round IDs we've bet on

    def reset_after_win(self):
        """Reset after a win"""
        self.current_bet = self.base_bet
        self.consecutive_losses = 0
        self.waiting_for_result = False

    def increase_after_loss(self):
        """Increase bet after a loss (classic martingale)"""
        self.consecutive_losses += 1
        self.current_bet = self.base_bet * (
            self.bet_multiplier**self.consecutive_losses
        )
        self.waiting_for_result = False

    def calc_current_bet(self) -> float:
        """Get current bet amount based on consecutive losses"""
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

    def __init__(self, db_path: str = "./crasher_data_classic.db"):
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
                round_id INTEGER,
                consecutive_losses INTEGER,
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
        return cursor.lastrowid

    def get_recent_multipliers_with_ids(self, count: int) -> List[Tuple[int, float]]:
        """Get recent multipliers with their IDs from current session"""
        if self.current_session_id is None:
            return []

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, multiplier FROM multipliers WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.current_session_id, count),
        )
        return [(row[0], row[1]) for row in reversed(cursor.fetchall())]

    def add_bet(
        self,
        strategy_name: str,
        bet_amount: float,
        outcome: str,
        multiplier: float,
        profit_loss: float,
        round_id: int,
        consecutive_losses: int,
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO bets (strategy_name, bet_amount, outcome, multiplier, profit_loss,
                            round_id, consecutive_losses)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                strategy_name,
                bet_amount,
                outcome,
                multiplier,
                profit_loss,
                round_id,
                consecutive_losses,
            ),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class ClassicMartingaleBot:
    """Crasher bot with classic martingale strategy"""

    def __init__(self, config_path: str = "./bot_config_classic.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        self.max_loss = float(self.config.get("max_loss", 100000000))

        # Load strategy
        self.strategy = self._load_strategy()

        # Bot state
        self.driver = None
        self.wait = None
        self.db = Database()
        self.db.set_logger(self.log)
        self.last_seen_multiplier = None
        self.last_round_time = 0
        self.running = False
        self.auto_cashout_configured = False
        self.rounds_since_setup = 0
        self.total_profit = 0.0

    def _load_strategy(self) -> StrategyState:
        """Load strategy from config"""
        if "strategy" not in self.config:
            raise ValueError("No 'strategy' section found in config file!")

        s = self.config["strategy"]
        strategy = StrategyState(
            name=s["name"],
            base_bet=float(s["base_bet"]),
            auto_cashout=float(s["auto_cashout"]),
            threshold=float(s["threshold"]),
            trigger_count=int(s["trigger_count"]),
            max_consecutive_losses=int(s.get("max_consecutive_losses", 20)),
            bet_multiplier=float(s.get("bet_multiplier", 2.0)),
            current_bet=float(s["base_bet"]),
            consecutive_losses=0,
            total_profit=0.0,
            waiting_for_result=False,
            is_active=False,
        )
        self.log(f"Loaded CLASSIC MARTINGALE strategy: {strategy.name}")
        self.log(
            f"  Trigger: {strategy.trigger_count} consecutive rounds >= {strategy.threshold}x"
        )
        self.log(f"  Then bet on NEXT round with cashout at {strategy.auto_cashout}x")
        self.log(f"  WIN if multiplier >= {strategy.auto_cashout}x")
        self.log(f"  LOSS: Multiply bet by {strategy.bet_multiplier}x")
        self.log(f"  WIN: Reset to base bet ${strategy.base_bet}")
        return strategy

    def log(self, message: str):
        try:
            logger.info(message)
        except UnicodeEncodeError:
            clean_msg = message.encode("ascii", "ignore").decode("ascii")
            logger.info(clean_msg)

    def read_recent_multipliers_from_page(self) -> List[float]:
        """Read recent multipliers from the page's result div"""
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

            return multipliers.reverse();
            """

            multipliers = self.driver.execute_script(script)

            if multipliers:
                self.log(f"Read {len(multipliers)} recent multipliers from page")
                return multipliers
            else:
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
            return None

        session_id, last_timestamp, round_count = last_session

        self.log(f"Found session #{session_id} with {round_count} rounds")

        if round_count == 0:
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
                    self.log(f"  Missing rounds: {len(missing_rounds)}")

                    return (session_id, match_end_pos, missing_rounds)

        return None

    def recover_or_create_session(self, start_balance: Optional[float] = None):
        """Attempt to recover last session or create new one"""
        self.log("=" * 60)
        self.log("SESSION RECOVERY")
        self.log("=" * 60)

        recent_page = self.read_recent_multipliers_from_page()

        if not recent_page:
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

            self.driver = uc.Chrome(
                options=options, version_main=None, use_subprocess=True
            )
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.wait = WebDriverWait(self.driver, 30)

            self.log("✓ Driver initialized")
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

            self.log("Clicking login button...")
            login_btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'a.loginDialog[automation="home_login_button"]')
                )
            )
            login_btn.click()
            time.sleep(2)

            self.log(f"Entering credentials...")
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
            self.log(f"Loading game...")
            self.driver.get(self.game_url)
            time.sleep(5)

            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )

            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

            game_iframe = None
            for i, iframe in enumerate(iframes):
                iframe_src = iframe.get_attribute("src")
                if iframe_src and len(iframe_src) > 50:
                    game_iframe = iframe
                    break

            if not game_iframe:
                return False

            self.driver.switch_to.frame(game_iframe)
            time.sleep(5)

            nested_iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if len(nested_iframes) > 0:
                self.driver.switch_to.frame(nested_iframes[0])
                time.sleep(3)

            self.wait_for_dynamic_content()
            self.close_tutorial_popup()

            self.log("✓ Game loaded!")
            return True

        except Exception as e:
            self.log(f"Failed to load game: {e}")
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
                if (buttons[i].offsetParent !== null) {
                    visibleButtons.push({text: buttons[i].textContent.trim()});
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
                    self.log("✓ Tutorial popup closed")
                    time.sleep(2)
                    return
                time.sleep(1)
        except:
            pass

    def setup_auto_cashout(self, max_retries: int = 5) -> bool:
        """Setup auto cashout with robust timing and state handling"""
        self.log(f" Auto Cashout started")

        for retry_attempt in range(max_retries):
            try:
                if retry_attempt > 0:
                    self.log(f"  Retry attempt {retry_attempt + 1}/{max_retries}")
                    time.sleep(2)  # Wait longer between retries

                # Find the first betting panel
                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                self.log(f" Panel Found")
                if not panels:
                    raise Exception("Betting panel not found")

                first_panel = panels[0]

                # Step 1: Check current mode and only click AUTO if needed
                buttons = first_panel.find_elements(By.TAG_NAME, "button")
                current_mode = None
                auto_button = None
                self.log(f" Buttons Found")

                for btn in buttons:
                    try:
                        if btn.is_displayed() and btn.is_enabled():
                            button_text = btn.text.strip().lower()
                            if button_text in ["auto", "stop"]:
                                current_mode = button_text
                                auto_button = btn
                                break
                    except:
                        continue

                if not auto_button:
                    raise Exception("AUTO/STOP button not found")

                # Only click if we're NOT already in AUTO mode
                if current_mode == "auto":
                    self.log("  ✓ Switching to AUTO mode...")
                    WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable(auto_button)
                    )
                    self.log(f"Auto Button clicked")

                    auto_button.click()
                    time.sleep(0.2)
                elif current_mode == "stop":
                    self.log("  ✓ Already in AUTO mode")
                else:
                    raise Exception(f"Unexpected button state: {current_mode}")

                # Step 2: Wait for auto cashout controls to appear
                time.sleep(0.2)

                # Step 3: Check and enable auto cashout toggle if needed
                try:
                    toggle = WebDriverWait(first_panel, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, 'input[data-testid="aut-co-tgl"]')
                        )
                    )
                    self.log(f"Toggle Found")

                    # Wait for toggle to be interactable
                    time.sleep(0.2)

                    # Check if toggle is already selected
                    is_selected = toggle.is_selected()

                    if not is_selected:
                        # Click the label for better reliability
                        toggle_label = first_panel.find_element(
                            By.CSS_SELECTOR,
                            'label[data-testid="toggle-label"][for="autocashout0"]',
                        )
                        self.log(f"Toggle Label Found")

                        WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable(toggle_label)
                        )
                        toggle_label.click()
                        self.log(f"Toggle Label Clicked")

                        time.sleep(0.1)
                        self.log("  ✓ Enabled auto cashout toggle")
                    else:
                        self.log("  ✓ Auto cashout toggle already enabled")

                except Exception as e:
                    self.log(f"  ⚠️ Toggle issue: {e}")
                    # Continue anyway, might already be enabled

                # Step 4: Wait for input to be ready and interactable
                time.sleep(0.1)

                # Step 5: Find and interact with auto cashout input using ActionChains
                auto_input = WebDriverWait(first_panel, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]')
                    )
                )

                self.log(f"Input Found")

                # Wait for it to be enabled and visible
                for wait_attempt in range(10):
                    self.log(f"Waiting for auto input")

                    if auto_input.is_displayed() and auto_input.is_enabled():
                        break
                    time.sleep(0.3)
                else:
                    raise Exception("Auto cashout input not interactable after waiting")

                # Read current value
                current_value = auto_input.get_attribute("value")
                self.log(f"  Current auto cashout value: {current_value}")

                # Use ActionChains to clear and set the value
                actions = ActionChains(self.driver)

                # Click the input to focus it
                actions.move_to_element(auto_input).click().perform()
                time.sleep(0.2)
                self.log(f"Input clicked")

                # Use multiple backspaces to ensure it's cleared
                for _ in range(4):
                    actions.send_keys(Keys.BACKSPACE).perform()
                    time.sleep(0.05)

                self.log(f"Deleted")

                # Enter new value
                actions.send_keys(str(self.strategy.auto_cashout)).perform()
                time.sleep(0.2)
                self.log(f"new inputed")

                # Step 6: Verify the value was set correctly
                final_value = auto_input.get_attribute("value")

                # Try to parse the value (handle both "2.5" and "2,5" formats)
                try:
                    final_float = float(final_value.replace(",", ".").replace(" ", ""))
                except:
                    final_float = 0.0

                self.log(f"  Final auto cashout value: {final_value}")

                if abs(final_float - self.strategy.auto_cashout) < 0.01:
                    self.log(f"✓ Auto cashout successfully set to {final_value}x")
                    self.auto_cashout_configured = True
                    return True
                else:
                    self.log(
                        f"  ⚠️ Value mismatch: expected {self.strategy.auto_cashout}, got {final_value}"
                    )
                    if retry_attempt < max_retries - 1:
                        self.log(f"  Retrying...")
                        continue
                    return False

            except TimeoutException as e:
                self.log(f"  ⚠️ Timeout on attempt {retry_attempt + 1}: {e}")
                if retry_attempt == max_retries - 1:
                    return False

            except Exception as e:
                self.log(f"  ⚠️ Attempt {retry_attempt + 1} failed: {e}")
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
        """Get current bank balance"""
        try:
            script = """
            var balanceDiv = document.getElementById('lblBalance');
            return balanceDiv ? balanceDiv.textContent : null;
            """
            balance_text = self.driver.execute_script(script)
            if balance_text:
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
        """Detect current/ended round multiplier"""
        try:
            script = """
            var mainMult = document.querySelector('span.ZmRXV');
            if (!mainMult) {
                return {found: false};
            }

            var text = mainMult.textContent.trim();
            var classList = mainMult.className;

            var hasEnded = classList.includes('false');
            var bettingActive = document.querySelector('button[data-testid="b-btn"]');
            var isBetting = bettingActive && bettingActive.textContent.toLowerCase().includes('bet');

            var roundEnded = hasEnded && isBetting;

            return {
                text: text,
                hasEnded: roundEnded,
                className: classList,
                isBetting: isBetting
            };
            """

            result = self.driver.execute_script(script)

            if not result.get("found", True):
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
            return None

    def check_trigger(self) -> bool:
        """
        Check if trigger conditions are met
        CRITICAL: Excludes rounds we've bet on from trigger windows
        """
        recent_with_ids = self.db.get_recent_multipliers_with_ids(
            self.strategy.trigger_count
        )

        if len(recent_with_ids) != self.strategy.trigger_count:
            return False

        # Extract multipliers and round IDs
        window_ids = [rid for rid, _ in recent_with_ids]
        window_mults = [mult for _, mult in recent_with_ids]

        # CRITICAL CHECK: Skip if ANY round in this window has been bet on
        if any(rid in self.strategy.excluded_round_ids for rid in window_ids):
            return False

        # Check if all rounds are >= threshold
        all_above = all(m >= self.strategy.threshold for m in window_mults)

        if all_above:
            self.log(f"[{self.strategy.name}] ✅ TRIGGER FOUND!")
            self.log(f"  Trigger rounds: {window_ids}")
            self.log(f"  Multipliers: {window_mults}")
            self.log(f"  All >= {self.strategy.threshold}x")
            return True

        return False

    def place_bet(self, amount: float) -> bool:
        """Place a bet"""
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

            self.log(f"[{self.strategy.name}] 💰 BET PLACED: ${amount:,.0f}")
            return True

        except Exception as e:
            self.log(f"[{self.strategy.name}] ❌ Failed to place bet: {e}")
            return False

    def handle_result(self, multiplier: float, round_id: int):
        """Handle bet result using CLASSIC MARTINGALE"""
        # WIN: multiplier >= auto_cashout
        if multiplier >= self.strategy.auto_cashout:
            profit = self.strategy.current_bet * (self.strategy.auto_cashout - 1)
            self.strategy.total_profit += profit
            self.total_profit += profit

            self.db.add_bet(
                self.strategy.name,
                self.strategy.current_bet,
                "win",
                multiplier,
                profit,
                round_id,
                self.strategy.consecutive_losses,
            )

            self.log(
                f"[{self.strategy.name}] ✅ WIN! {multiplier:.2f}x >= {self.strategy.auto_cashout}x"
            )
            self.log(f"  Profit: +${profit:,.0f} | Total: ${self.total_profit:,.0f}")

            # CLASSIC MARTINGALE: Reset to base bet after WIN
            self.strategy.reset_after_win()
            self.log(f"  Reset to base bet: ${self.strategy.base_bet:,.0f}")

        else:
            # LOSS: multiplier < auto_cashout
            loss = self.strategy.current_bet
            self.strategy.total_profit -= loss
            self.total_profit -= loss

            self.db.add_bet(
                self.strategy.name,
                self.strategy.current_bet,
                "loss",
                multiplier,
                -loss,
                round_id,
                self.strategy.consecutive_losses,
            )

            self.log(
                f"[{self.strategy.name}] ❌ LOSS! {multiplier:.2f}x < {self.strategy.auto_cashout}x"
            )
            self.log(f"  Loss: -${loss:,.0f} | Total: ${self.total_profit:,.0f}")

            # CLASSIC MARTINGALE: Increase bet after LOSS
            self.strategy.increase_after_loss()
            self.log(f"  Consecutive losses: {self.strategy.consecutive_losses}")
            self.log(
                f"  Next bet: ${self.strategy.current_bet:,.0f} ({self.strategy.bet_multiplier}x increase)"
            )

    def check_stop_conditions(self) -> bool:
        """Check if we should stop"""
        if self.total_profit <= -self.max_loss:
            self.log(f"🛑 STOP: Max loss reached (${abs(self.total_profit):,.0f})")
            return False

        if self.strategy.consecutive_losses >= self.strategy.max_consecutive_losses:
            self.log(
                f"🛑 STOP: Max consecutive losses reached ({self.strategy.consecutive_losses})"
            )
            return False

        return True

    def run(self):
        """Main bot loop"""
        try:
            self.log("=" * 60)
            self.log("CLASSIC MARTINGALE CRASHER BOT")
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

            if not self.setup_auto_cashout():
                self.log(f"⚠️ WARNING: Could not setup initial auto cashout")

            self.log("=" * 60)
            self.log("STRATEGY CONFIGURATION:")
            self.log(f"  Name: {self.strategy.name}")
            self.log(
                f"  Trigger: {self.strategy.trigger_count} consecutive rounds >= {self.strategy.threshold}x"
            )
            self.log(f"  Base bet: ${self.strategy.base_bet:,.0f}")
            self.log(f"  Auto cashout: {self.strategy.auto_cashout}x")
            self.log(f"  Bet multiplier: {self.strategy.bet_multiplier}x (on LOSS)")
            self.log(
                f"  Max consecutive losses: {self.strategy.max_consecutive_losses}"
            )
            self.log("=" * 60)
            self.log("🤖 BOT RUNNING - Monitoring multipliers...")
            self.log("=" * 60)

            self.running = True
            last_logged_time = {}

            while self.running:
                if not self.check_stop_conditions():
                    break

                new_mult = self.detect_current_multiplier()

                if new_mult and new_mult != self.last_seen_multiplier:
                    current_time = time.time()

                    # Safeguards against duplicate logging
                    time_since_last_round = current_time - self.last_round_time
                    if self.last_round_time > 0 and time_since_last_round < 3.0:
                        time.sleep(0.1)
                        continue

                    mult_key = f"{new_mult:.2f}"
                    if mult_key in last_logged_time:
                        time_since_last = current_time - last_logged_time[mult_key]
                        if time_since_last < 5.0:
                            time.sleep(0.1)
                            continue

                    # Update tracking
                    last_logged_time[mult_key] = current_time
                    self.last_seen_multiplier = new_mult
                    self.last_round_time = current_time
                    self.rounds_since_setup += 1

                    # Clean up tracking dict
                    if len(last_logged_time) > 10:
                        oldest_key = min(last_logged_time, key=last_logged_time.get)
                        del last_logged_time[oldest_key]

                    # Keep session active
                    if self.rounds_since_setup >= 20:
                        self.setup_auto_cashout()
                        self.rounds_since_setup = 0

                    bettor_count = self.get_bettor_count()
                    bank_balance = self.get_bank_balance()

                    # Add multiplier to database and get its ID
                    round_id = self.db.add_multiplier(new_mult, bettor_count)

                    log_parts = [f"📊 Round #{round_id}: {new_mult:.2f}x"]
                    if bettor_count:
                        log_parts.append(f"👥 {bettor_count}")
                    if bank_balance is not None:
                        log_parts.append(f"💰 ${bank_balance:,.0f}")

                    self.log(" | ".join(log_parts))

                    # Handle active bet result
                    if self.strategy.waiting_for_result:
                        self.handle_result(new_mult, round_id)

                        # Mark this round as excluded
                        self.strategy.excluded_round_ids.add(round_id)

                    # Check for new trigger (only if not waiting for result)
                    elif not self.strategy.waiting_for_result:
                        if self.check_trigger():
                            if not self.setup_auto_cashout():
                                self.log(f"⚠️ WARNING: Failed to setup auto-cashout")
                                continue

                            time.sleep(0.5)
                            bet_amount = self.strategy.calc_current_bet()

                            if self.place_bet(bet_amount):
                                self.strategy.current_bet = bet_amount
                                self.strategy.waiting_for_result = True

                time.sleep(0.1)

        except KeyboardInterrupt:
            self.log("\n⏹️ Bot stopped by user")
        except Exception as e:
            self.log(f"❌ ERROR: {e}")
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
            self.log(f"  Session ID: {self.db.current_session_id}")
            self.log(f"  Total Profit/Loss: ${self.total_profit:,.0f}")
            self.log(f"  Consecutive Losses: {self.strategy.consecutive_losses}")
            self.log(f"  Excluded Rounds: {len(self.strategy.excluded_round_ids)}")

            try:
                final_balance = self.get_bank_balance()
                if final_balance is not None:
                    self.log(f"  Final Bank Balance: ${final_balance:,.0f}")
            except:
                pass

            self.log("=" * 60)

            if self.driver:
                self.driver.quit()
            self.db.close()
            self.log("🔴 Bot shut down")


def main():
    try:
        bot = ClassicMartingaleBot(config_path="./bot_config_classic.json")
        bot.run()
    except FileNotFoundError:
        logger.error("Config file 'bot_config_classic.json' not found!")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
