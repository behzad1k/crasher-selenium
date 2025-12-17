#!/usr/bin/env python3
"""
Crasher Bot - Clean Server Version
Observes multipliers, detects trigger, and bets with martingale strategy
"""

import json
import logging
import sqlite3
import time
from typing import List, Optional

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


class Database:
    """Simple database for tracking bets and multipliers"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bet_amount REAL NOT NULL,
                outcome TEXT CHECK(outcome IN ('win', 'loss')),
                multiplier REAL,
                profit_loss REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_multiplier(self, multiplier: float, bettor_count: Optional[int] = None):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO multipliers (multiplier, bettor_count) VALUES (?, ?)",
            (multiplier, bettor_count),
        )
        self.conn.commit()

    def get_recent_multipliers(self, count: int) -> List[float]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT multiplier FROM multipliers ORDER BY id DESC LIMIT ?", (count,)
        )
        return [row[0] for row in reversed(cursor.fetchall())]

    def add_bet(
        self, bet_amount: float, outcome: str, multiplier: float, profit_loss: float
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO bets (bet_amount, outcome, multiplier, profit_loss) VALUES (?, ?, ?, ?)",
            (bet_amount, outcome, multiplier, profit_loss),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


class CrasherBot:
    """Crasher bot with trigger detection and martingale betting"""

    def __init__(self, config_path: str = "./bot_config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        self.base_bet = float(self.config["base_bet"])
        self.auto_cashout = float(self.config["auto_cashout"])
        self.trigger_threshold = float(self.config["trigger_threshold"])
        self.trigger_count = int(self.config["trigger_count"])
        self.max_loss = float(self.config["max_loss"])
        self.max_consecutive_losses = int(self.config["max_consecutive_losses"])

        self.driver = None
        self.wait = None
        self.db = Database()
        self.current_bet = self.base_bet
        self.consecutive_losses = 0
        self.total_profit = 0.0
        self.waiting_for_result = False
        self.last_seen_multiplier = None
        self.running = False
        self.auto_cashout_configured = False
        self.rounds_since_setup = 0

    def log(self, message: str):
        try:
            logger.info(message)
        except UnicodeEncodeError:
            clean_msg = message.encode("ascii", "ignore").decode("ascii")
            logger.info(clean_msg)

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
            options.add_argument("--disable-extensions-file-access-check")
            options.add_argument("--disable-extensions-http-throttling")

            self.driver = uc.Chrome(
                options=options, version_main=None, use_subprocess=True
            )
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.driver.set_script_timeout(15)  # Set default script timeout
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

            # Find the GAME iframe (the one with actual src URL, not tracking pixel)
            self.log("Finding game iframe (looking for one with src)...")
            game_iframe = None
            game_iframe_index = -1

            for i, iframe in enumerate(iframes):
                iframe_src = iframe.get_attribute("src")
                if iframe_src and len(iframe_src) > 50:  # Game iframe has long URL
                    game_iframe = iframe
                    game_iframe_index = i
                    self.log(f"Found game iframe at index {i}")
                    self.log(f"Game iframe src: {iframe_src[:80]}...")
                    break

            if not game_iframe:
                self.log("ERROR: Could not find game iframe with src!")
                return False

            self.log(f"Switching to game iframe (index {game_iframe_index})...")
            self.driver.switch_to.frame(game_iframe)
            time.sleep(5)  # Give iframe time to load

            self.log("Checking for nested iframes inside game iframe...")
            nested_iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

            if len(nested_iframes) > 0:
                self.log(
                    f"Found {len(nested_iframes)} nested iframe(s)! Switching to first nested iframe..."
                )
                try:
                    nested_src = nested_iframes[0].get_attribute("src")
                    self.log(f"Nested iframe src: {nested_src}")
                except:
                    pass

                self.driver.switch_to.frame(nested_iframes[0])
                self.log("OK Switched to nested iframe")
                time.sleep(3)
            else:
                self.log("No nested iframes found, staying in first iframe")

            self.log("Waiting for dynamic content to populate...")
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
                var isVisible = btn.offsetParent !== null &&
                               window.getComputedStyle(btn).display !== 'none' &&
                               window.getComputedStyle(btn).visibility !== 'hidden';
                if (isVisible) {
                    visibleButtons.push({
                        text: btn.textContent.trim(),
                        className: btn.className
                    });
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

                except Exception as e:
                    time.sleep(1)

            return False

        except Exception as e:
            return False

    def close_tutorial_popup(self):
        """Close tutorial popup if it appears"""
        try:
            for attempt in range(30):
                script = """
                var buttons = document.getElementsByClassName('Qthei');
                if (buttons.length > 0) {
                    return {found: true, count: buttons.length, visible: buttons[0].offsetParent !== null};
                }
                return {found: false};
                """
                result = self.driver.execute_script(script)

                if result.get("found"):
                    self.log("OK Tutorial popup found, closing...")
                    click_script = """
                    var buttons = document.getElementsByClassName('Qthei');
                    if (buttons.length > 0) {
                        buttons[0].click();
                        return true;
                    }
                    return false;
                    """
                    clicked = self.driver.execute_script(click_script)
                    if clicked:
                        self.log("OK Tutorial popup closed")
                        time.sleep(2)
                        return
                time.sleep(1)

            for attempt in range(30):
                script = """
                var buttons = document.getElementsByClassName('popup_action');
                if (buttons.length > 0) {
                    return {found: true, count: buttons.length};
                }
                return {found: false};
                """
                result = self.driver.execute_script(script)

                if result.get("found"):
                    self.log("OK Tutorial popup found (popup_action), closing...")
                    click_script = """
                    var buttons = document.getElementsByClassName('popup_action');
                    if (buttons.length > 0) {
                        buttons[buttons.length - 1].click();
                        return true;
                    }
                    return false;
                    """
                    clicked = self.driver.execute_script(click_script)
                    if clicked:
                        self.log("OK Tutorial popup closed")
                        time.sleep(2)
                        return
                time.sleep(1)

        except Exception as e:
            pass

    def setup_auto_cashout(self, max_retries: int = 3) -> bool:
        """Setup auto cashout configuration with retries"""
        for retry_attempt in range(max_retries):
            try:
                if retry_attempt > 0:
                    self.log(
                        f"Retrying auto cashout setup (attempt {retry_attempt + 1}/{max_retries})..."
                    )
                    time.sleep(3)

                self.driver.set_script_timeout(10)  # 10 second timeout per script

                self.log(f"Setting up auto cashout at {self.auto_cashout}x...")
                self.log("Looking for AUTO button in first panel...")

                max_attempts = 15
                auto_button_clicked = False

                for attempt in range(max_attempts):
                    try:
                        script = """
                        try {
                            var panels = document.querySelectorAll('div[data-singlebetpart]');
                            if (!panels || panels.length === 0) return {found: false, error: 'no panels'};
                            var firstPanel = panels[0];
                            if (!firstPanel) return {found: false, error: 'no first panel'};
                            var buttons = firstPanel.querySelectorAll('button');
                            if (!buttons) return {found: false, error: 'no buttons'};
                            for (var i = 0; i < buttons.length; i++) {
                                var btn = buttons[i];
                                if (btn && btn.textContent && btn.offsetParent !== null) {
                                    if(btn.textContent.trim() === 'Auto'){
                                        return {found: true, text: btn.textContent.trim()};
                                    }
                                    else if (btn.textContent.trim() === 'Stop'){
                                        return {found: true, text: btn.textContent.trim()};
                                    }
                                }
                            }
                            return {found: false, error: 'auto button not visible'};
                        } catch(e) {
                            return {found: false, error: e.toString()};
                        }
                        """

                        result = self.driver.execute_script(script)

                        if result.get("found"):
                            click_script = """
                            try {
                                var panels = document.querySelectorAll('div[data-singlebetpart]');
                                var firstPanel = panels[0];
                                var buttons = firstPanel.querySelectorAll('button');
                                for (var i = 0; i < buttons.length; i++) {
                                    var btn = buttons[i];
                                    if (btn.textContent.trim() === 'Auto' && btn.offsetParent !== null) {
                                        btn.click();
                                        return {clicked: true};
                                    }
                                }
                                return {clicked: false};
                            } catch(e) {
                                return {clicked: false, error: e.toString()};
                            }
                            """

                            clicked_result = self.driver.execute_script(click_script)

                            if (
                                clicked_result.get("clicked")
                                or result.get("text") == "Stop"
                            ):
                                self.log("OK AUTO button clicked (first panel)")
                                auto_button_clicked = True
                                time.sleep(1)
                                break

                        time.sleep(1)

                    except TimeoutException:
                        self.log(
                            f"Script timeout on attempt {attempt + 1}, retrying..."
                        )
                        time.sleep(1)
                        continue

                if not auto_button_clicked:
                    raise Exception("AUTO button not found after waiting")

                self.log("Enabling Auto Cashout toggle in first panel...")

                toggle_script = """
                try {
                    var panels = document.querySelectorAll('div[data-singlebetpart]');
                    var firstPanel = panels[0];
                    var toggle = firstPanel.querySelector('input[data-testid="aut-co-tgl"]');
                    if (toggle) {
                        if (!toggle.checked) {
                            toggle.click();
                        }
                        return {found: true, enabled: toggle.checked};
                    }
                    return {found: false};
                } catch(e) {
                    return {found: false, error: e.toString()};
                }
                """

                result = self.driver.execute_script(toggle_script)

                if not result.get("found"):
                    raise Exception("Auto Cashout toggle not found in first panel")

                self.log("OK Auto Cashout toggle enabled")
                time.sleep(1.5)

                self.log(f"Setting auto cashout value to {self.auto_cashout}x...")

                # Use Selenium native methods with shorter timeout for input
                try:
                    from selenium.webdriver.common.keys import Keys

                    panels = self.driver.find_elements(
                        By.CSS_SELECTOR, "div[data-singlebetpart]"
                    )
                    if not panels:
                        raise Exception("No betting panels found")

                    first_panel = panels[0]

                    # Wait for input to be present and clickable
                    auto_input = WebDriverWait(first_panel, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]')
                        )
                    )

                    # Clear and set value
                    auto_input.click()
                    time.sleep(0.3)

                    # Clear existing value
                    for _i in range(0, 4):
                        auto_input.send_keys(Keys.BACKSPACE)
                    time.sleep(0.2)

                    # Enter new value
                    auto_input.send_keys(str(self.auto_cashout))
                    time.sleep(0.5)

                    # Verify the value was set
                    final_value = auto_input.get_attribute("value")
                    self.log(f"OK Auto cashout set to {final_value}x")

                    if float(final_value) != self.auto_cashout:
                        self.log(
                            f"WARNING: Expected {self.auto_cashout}, got {final_value}"
                        )
                        # Try one more time
                        auto_input.click()
                        time.sleep(0.2)
                        for _i in range(0, 4):
                            auto_input.send_keys(Keys.BACKSPACE)
                        time.sleep(0.2)
                        auto_input.send_keys(str(self.auto_cashout))
                        time.sleep(0.5)
                        final_value = auto_input.get_attribute("value")
                        self.log(f"Retry: Auto cashout now set to {final_value}x")

                except TimeoutException:
                    raise Exception("Timeout waiting for auto cashout input field")
                except Exception as e:
                    raise Exception(f"Failed to set auto cashout value: {e}")

                time.sleep(1)

                self.auto_cashout_configured = True
                self.rounds_since_setup = 0
                self.log("OK Auto cashout configuration complete!")

                return True

            except TimeoutException as e:
                self.log(f"Setup timeout on attempt {retry_attempt + 1}: {e}")
                if retry_attempt == max_retries - 1:
                    return False
                continue

            except Exception as e:
                self.log(f"Setup failed on attempt {retry_attempt + 1}: {e}")
                if retry_attempt == max_retries - 1:
                    import traceback

                    self.log(traceback.format_exc())
                    return False
                continue

        return False

    def get_bettor_count(self) -> Optional[int]:
        """Get number of bettors"""
        try:
            script = """
            var span = document.querySelector('span[data-testid="b-ct-spn"]');
            if (span) {
                return span.textContent || span.innerText;
            }
            return null;
            """

            count_text = self.driver.execute_script(script)

            if count_text and str(count_text).strip().isdigit():
                return int(count_text)

            return None

        except Exception as e:
            return None

    def get_bank_balance(self) -> Optional[float]:
        """Get current bank balance"""
        try:
            script = """
            var span = document.querySelector('span[data-testid="amount-box_amount"]');
            if (span) {
                return span.textContent || span.innerText;
            }
            return null;
            """

            balance_text = self.driver.execute_script(script)

            if balance_text:
                balance_str = (
                    str(balance_text).strip().replace(",", "").replace(" ", "")
                )
                try:
                    return float(balance_str)
                except ValueError:
                    return None

            return None

        except Exception as e:
            return None

    def detect_current_multiplier(self) -> Optional[float]:
        """Detect current/ended round multiplier"""
        try:
            script = """
            var mainMult = document.querySelector('span.ZmRXV');
            if (mainMult) {
                var text = mainMult.textContent.trim();
                var className = mainMult.className;
                var hasEnded = className.includes('false');
                return {
                    found: true,
                    text: text,
                    hasEnded: hasEnded
                };
            }
            return {found: false};
            """

            result = self.driver.execute_script(script)

            if not result.get("found"):
                return None

            if not result.get("hasEnded"):
                return None

            text = result.get("text", "")
            if "x" in text.lower():
                import re

                match = re.search(r"(\d+\.?\d*)x", text, re.IGNORECASE)
                if match:
                    mult_str = match.group(1)
                    mult = float(mult_str)
                    if 1.0 <= mult <= 10000.0:
                        return mult

            return None

        except Exception as e:
            return None

    def check_trigger(self) -> bool:
        """Check if trigger conditions are met"""
        recent = self.db.get_recent_multipliers(self.trigger_count)

        if len(recent) < self.trigger_count:
            return False

        all_under = all(m < self.trigger_threshold for m in recent)

        if all_under:
            self.log(f"TRIGGER: Last {self.trigger_count} rounds: {recent}")
            return True

        return False

    def enter_bet_amount(self, amount: float) -> bool:
        """Enter bet amount in FIRST betting panel"""
        try:
            from selenium.webdriver.common.keys import Keys

            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                self.log("WARNING: No betting panels found!")
                return False

            first_panel = panels[0]

            bet_input = WebDriverWait(first_panel, 5).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[data-testid="bp-inp"]')
                )
            )

            bet_input.click()
            time.sleep(0.2)

            # Clear existing value
            for _i in range(0, 8):
                bet_input.send_keys(Keys.BACKSPACE)
            time.sleep(0.2)

            bet_input.send_keys(str(int(amount)))
            time.sleep(0.3)

            final_value = bet_input.get_attribute("value")
            self.log(f"OK Bet amount set to {final_value} (first panel)")

            return True

        except Exception as e:
            self.log(f"Failed to enter bet amount: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def click_bet_button(self) -> bool:
        """Click the BET button in FIRST panel"""
        try:
            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                self.log("WARNING: No betting panels found!")
                return False

            first_panel = panels[0]

            bet_button = first_panel.find_element(
                By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
            )

            bet_button.click()
            self.log("OK BET button clicked (first panel)")
            time.sleep(0.5)

            return True

        except Exception as e:
            self.log(f"Failed to click bet button: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def place_bet(self, amount: float) -> bool:
        """Place a bet"""
        if not self.enter_bet_amount(amount):
            return False

        if not self.click_bet_button():
            return False

        self.waiting_for_result = True
        return True

    def calc_next_bet(self) -> float:
        """Calculate next bet using martingale"""
        if self.consecutive_losses == 0:
            return self.base_bet
        return self.base_bet * (2**self.consecutive_losses)

    def handle_result(self, multiplier: float):
        """Handle bet result"""
        if multiplier >= self.auto_cashout:
            profit = self.current_bet * (self.auto_cashout - 1)
            self.total_profit += profit
            self.db.add_bet(self.current_bet, "win", multiplier, profit)
            self.consecutive_losses = 0
            self.current_bet = self.base_bet

            self.log(
                f"SUCCESS: WIN! {multiplier}x | Profit: +{profit:.0f} | Total: {self.total_profit:.0f}"
            )
        else:
            loss = self.current_bet
            self.total_profit -= loss
            self.db.add_bet(self.current_bet, "loss", multiplier, -loss)
            self.consecutive_losses += 1
            self.current_bet = self.calc_next_bet()

            self.log(
                f"ERROR: LOSS! {multiplier}x | Loss: -{loss:.0f} | Total: {self.total_profit:.0f}"
            )
            self.log(
                f"   Consecutive losses: {self.consecutive_losses} | Next bet: {self.current_bet:.0f}"
            )

        self.waiting_for_result = False

    def check_stop_conditions(self) -> bool:
        """Check if we should stop"""
        if self.total_profit <= -self.max_loss:
            self.log(f"STOP: Max loss reached ({abs(self.total_profit):.0f})")
            return False

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.log(
                f"STOP: Max consecutive losses reached ({self.consecutive_losses})"
            )
            return False

        return True

    def run(self):
        """Main bot loop"""
        try:
            self.log("=" * 60)
            self.log("CRASHER BOT STARTING")
            self.log("=" * 60)

            if not self.init_driver():
                return

            if not self.login():
                return

            if not self.navigate_to_game():
                return

            # Try setup with retries
            setup_success = False
            for i in range(3):
                if self.setup_auto_cashout():
                    setup_success = True
                    break
                self.log(f"Setup attempt {i + 1} failed, retrying in 5 seconds...")
                time.sleep(5)

            if not setup_success:
                self.log("WARNING: Could not setup auto cashout after 3 attempts")
                self.log(
                    "Bot will continue monitoring, but betting may not work properly"
                )

            self.log("=" * 60)
            self.log("CONFIGURATION:")
            self.log(f"   Base Bet: {self.base_bet}")
            self.log(f"   Auto Cashout: {self.auto_cashout}x")
            self.log(
                f"   Trigger: {self.trigger_count} rounds under {self.trigger_threshold}x"
            )
            self.log(f"   Max Loss: {self.max_loss}")
            self.log(f"   Max Consecutive Losses: {self.max_consecutive_losses}")
            self.log("=" * 60)
            self.log("BOT RUNNING - Monitoring multipliers...")
            self.log("=" * 60)

            self.running = True

            while self.running:
                if not self.check_stop_conditions():
                    break

                new_mult = self.detect_current_multiplier()

                if new_mult and new_mult != self.last_seen_multiplier:
                    self.last_seen_multiplier = new_mult

                    self.rounds_since_setup += 1

                    if self.rounds_since_setup >= 2:
                        self.log(
                            "Re-setting up auto-cashout (keeping session active)..."
                        )
                        self.setup_auto_cashout()

                    bettor_count = self.get_bettor_count()

                    bank_balance = self.get_bank_balance()

                    log_parts = [f"Round ended: {new_mult}x"]

                    if bettor_count:
                        log_parts.append(f"Bettors: {bettor_count}")

                    if bank_balance is not None:
                        log_parts.append(f"Bank: {bank_balance:,.0f}")

                    self.log(" | ".join(log_parts))

                    self.db.add_multiplier(new_mult, bettor_count)

                    if self.waiting_for_result:
                        self.handle_result(new_mult)

                    if not self.waiting_for_result and self.check_trigger():
                        time.sleep(2)
                        bet_amount = self.calc_next_bet()
                        self.log(f"Placing bet: {bet_amount}")

                        if self.place_bet(bet_amount):
                            self.current_bet = bet_amount
                        else:
                            self.log("WARNING: Failed to place bet!")

                time.sleep(0.5)

        except KeyboardInterrupt:
            self.log("\nBot stopped by user")
        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback

            self.log(traceback.format_exc())
        finally:
            self.running = False
            self.log("=" * 60)
            self.log("SESSION SUMMARY:")
            self.log(f"   Total Profit/Loss: {self.total_profit:.0f}")
            self.log(f"   Consecutive Losses: {self.consecutive_losses}")

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
        bot = CrasherBot(config_path="./bot_config.json")
        bot.run()
    except FileNotFoundError:
        logger.error("Config file 'bot_config.json' not found!")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
