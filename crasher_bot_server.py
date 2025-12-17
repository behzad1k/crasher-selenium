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
    handlers=[logging.FileHandler("crasher_bot.log"), logging.StreamHandler()],
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
        # Load config
        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Config parameters
        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        self.base_bet = float(self.config["base_bet"])
        self.auto_cashout = float(self.config["auto_cashout"])
        self.trigger_threshold = float(self.config["trigger_threshold"])
        self.trigger_count = int(self.config["trigger_count"])
        self.max_loss = float(self.config["max_loss"])
        self.max_consecutive_losses = int(self.config["max_consecutive_losses"])

        # Bot state
        self.driver = None
        self.wait = None
        self.db = Database()
        self.current_bet = self.base_bet
        self.consecutive_losses = 0
        self.total_profit = 0.0
        self.waiting_for_result = False
        self.last_seen_multiplier = None
        self.running = False
        self.auto_cashout_configured = False  # Track if auto-cashout is set up
        self.rounds_since_setup = 0  # Track rounds since last auto-cashout setup

    def log(self, message: str):
        logger.info(message)

    def init_driver(self) -> bool:
        """Initialize undetected Chrome driver - SIMPLIFIED VERSION"""
        try:
            if not UNDETECTED_AVAILABLE:
                self.log("ERROR: undetected-chromedriver not installed!")
                self.log("Install with: pip install undetected-chromedriver")
                return False

            self.log("Initializing Chrome driver...")
            options = uc.ChromeOptions()

            # Basic required options
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            # options.add_argument("--headless=new")

            # WebGL support (required for game)
            options.add_argument("--use-gl=swiftshader")
            options.add_argument("--enable-webgl")

            # Anti-detection (simple version)
            options.add_argument("--disable-blink-features=AutomationControlled")

            # Create driver (minimal parameters to avoid compatibility issues)
            self.driver = uc.Chrome(options=options)

            # Set timeouts
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.wait = WebDriverWait(self.driver, 30)

            self.log("✓ Driver initialized (non-headless with Xvfb)")
            return True

        except Exception as e:
            self.log(f"Failed to initialize driver: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def login(self) -> bool:
        """Login to website"""
        try:
            self.log("Navigating to login page...")
            self.driver.get("https://1000bet.in")
            time.sleep(5)

            # Check for Cloudflare
            if "cloudflare" in self.driver.page_source.lower():
                self.log("⚠️  Cloudflare detected - waiting...")
                time.sleep(10)

            # Click login button
            self.log("Clicking login button...")
            login_btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'a.loginDialog[automation="home_login_button"]')
                )
            )
            login_btn.click()
            time.sleep(2)

            # Fill credentials
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

            # Submit
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

            # Wait for iframe - the game is in a single iframe
            self.log("Waiting for game iframe...")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )

            # Get all iframes on main page
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            self.log(f"Found {len(iframes)} iframe(s) on main page")

            if len(iframes) == 0:
                self.log("ERROR: No iframes found!")
                return False

            # Switch to the first iframe
            self.log("Switching to game iframe (first level)...")
            self.driver.switch_to.frame(iframes[0])

            # Log iframe src
            try:
                self.driver.switch_to.default_content()
                iframe_src = iframes[0].get_attribute("src")
                self.log(f"Game iframe src: {iframe_src}")
                self.driver.switch_to.frame(iframes[0])
            except:
                pass

            time.sleep(3)

            # Check for NESTED iframes inside the game iframe
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
                self.log("✓ Switched to nested iframe")
                time.sleep(3)
            else:
                self.log("No nested iframes found, staying in first iframe")

            # Wait for dynamic content to load
            self.log("Waiting for dynamic content to populate...")
            self.wait_for_dynamic_content()

            # Close tutorial popup if present
            self.close_tutorial_popup()

            self.log("✓ Game loaded successfully!")
            return True

        except Exception as e:
            self.log(f"Failed to load game: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def wait_for_dynamic_content(self, max_wait: int = 40):
        """Wait for the game's dynamic content to populate the DOM with VISIBLE elements"""
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
        """Close tutorial popup if it appears - uses JavaScript to access live DOM"""
        try:
            # Strategy 1: Use JavaScript to check live DOM for Qthei button
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
                        self.log("✓ Tutorial popup found, closing...")

                        # Click it using JavaScript
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
                            self.log("✓ Tutorial popup closed")
                            time.sleep(2)
                            return

                    time.sleep(1)

            except Exception as e:
                pass

            # Strategy 2: Check for popup_action buttons
            try:
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
                        self.log("✓ Tutorial popup found (popup_action), closing...")

                        # Click the last one using JavaScript
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
                            self.log("✓ Tutorial popup closed")
                            time.sleep(2)
                            return

                    time.sleep(1)

            except Exception as e:
                pass

        except Exception as e:
            pass

    def setup_auto_cashout(self) -> bool:
        """Setup auto cashout configuration - runs every 20 rounds to keep session active"""
        try:
            self.log(f"Setting up auto cashout at {self.auto_cashout}x...")

            # Step 1: Wait for and click the AUTO button in FIRST panel
            self.log("Looking for AUTO button in first panel...")

            max_attempts = 10
            auto_button_clicked = False

            for attempt in range(max_attempts):
                script = """
                // Find all betting panels
                var panels = document.querySelectorAll('div[data-singlebetpart]');
                if (panels.length === 0) return {found: false};

                // Use FIRST panel only
                var firstPanel = panels[0];

                // Find AUTO button within first panel
                var buttons = firstPanel.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    if (btn.textContent.trim() === 'Auto' && btn.offsetParent !== null) {
                        return {found: true, text: btn.textContent};
                    }
                }
                return {found: false};
                """

                result = self.driver.execute_script(script)

                if result.get("found"):
                    # Click the AUTO button in first panel
                    click_script = """
                    var panels = document.querySelectorAll('div[data-singlebetpart]');
                    var firstPanel = panels[0];
                    var buttons = firstPanel.querySelectorAll('button');

                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        if (btn.textContent.trim() === 'Auto' && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                    """

                    clicked = self.driver.execute_script(click_script)

                    if clicked:
                        self.log("✓ AUTO button clicked (first panel)")
                        auto_button_clicked = True
                        time.sleep(1)
                        break

                if attempt % 2 == 0:
                    self.log(
                        f"Waiting for AUTO button... (attempt {attempt + 1}/{max_attempts})"
                    )
                time.sleep(1)

            if not auto_button_clicked:
                self.log("⚠️  AUTO button not found after waiting")
                return False

            # Step 2: Enable Auto Cashout toggle in FIRST panel
            self.log("Enabling Auto Cashout toggle in first panel...")

            script = """
            var panels = document.querySelectorAll('div[data-singlebetpart]');
            var firstPanel = panels[0];

            // Find the Auto Cashout toggle within first panel
            var toggle = firstPanel.querySelector('input[data-testid="aut-co-tgl"]');
            if (toggle) {
                if (!toggle.checked) {
                    toggle.click();
                }
                return {found: true, enabled: toggle.checked};
            }
            return {found: false};
            """

            result = self.driver.execute_script(script)

            if not result.get("found"):
                self.log("⚠️  Auto Cashout toggle not found in first panel!")
                return False

            self.log("✓ Auto Cashout toggle enabled")
            time.sleep(1.5)

            # Step 3: Set the auto cashout value in FIRST panel
            self.log(f"Setting auto cashout value to {self.auto_cashout}x...")

            try:
                from selenium.webdriver.common.keys import Keys

                # Find first panel, then find input within it
                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                if not panels:
                    self.log("⚠️  No betting panels found!")
                    return False

                first_panel = panels[0]
                auto_input = first_panel.find_element(
                    By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]'
                )

                auto_input.click()
                time.sleep(0.2)

                # Select all and delete
                for _i in range(0, 4):
                    auto_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.2)

                # Type new value
                auto_input.send_keys(str(self.auto_cashout))
                time.sleep(0.3)

                # Verify
                final_value = auto_input.get_attribute("value")
                self.log(f"✓ Auto cashout set to {final_value}x")

                if float(final_value) != self.auto_cashout:
                    self.log(
                        f"⚠️  Warning: Expected {self.auto_cashout}, got {final_value}"
                    )

            except Exception as e:
                self.log(f"⚠️  Failed to set auto cashout: {e}")
                return False

            time.sleep(1)

            # Mark as configured and reset counter
            self.auto_cashout_configured = True
            self.rounds_since_setup = 0
            self.log("✓ Auto cashout configuration complete!")

            return True

        except Exception as e:
            self.log(f"Setup auto cashout failed: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def validate_auto_cashout(self) -> bool:
        """Validate that auto cashout is properly configured"""
        try:
            # Check if auto cashout input shows correct value
            cashout_inputs = self.driver.find_elements(
                By.XPATH, "//input[@type='text'] | //input[@type='number']"
            )

            for inp in cashout_inputs:
                try:
                    value = inp.get_attribute("value")
                    if value and float(value) == self.auto_cashout:
                        return True
                except:
                    continue

            return False
        except:
            return False

    def get_recent_multipliers_from_ui(self) -> List[float]:
        """Extract recent multipliers from the top bar (class sc-w0koce-1 giBFzM)"""
        try:
            script = """
            // Find multipliers in the recent bar with class 'sc-w0koce-1 giBFzM'
            var multiplierSpans = document.querySelectorAll('span.sc-w0koce-1.giBFzM');
            var multipliers = [];

            for (var i = 0; i < multiplierSpans.length; i++) {
                var text = multiplierSpans[i].textContent.trim();
                if (text.includes('x')) {
                    multipliers.push(text);
                }
            }

            return multipliers;
            """

            mult_texts = self.driver.execute_script(script)

            if not mult_texts:
                return []

            # Parse multipliers
            multipliers = []
            for text in mult_texts:
                try:
                    # Extract number from "1.45x" format
                    mult_str = text.replace("x", "").replace("X", "").strip()
                    mult = float(mult_str)
                    if 1.0 <= mult <= 10000.0:
                        multipliers.append(mult)
                except:
                    continue

            # Return most recent (first 20)
            return multipliers[:20] if len(multipliers) > 20 else multipliers

        except Exception as e:
            return []

    def get_bettor_count(self) -> Optional[int]:
        """Get the number of bettors for current round using live DOM"""
        try:
            # Use JavaScript to find the bettor count in live DOM
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
        """Get current bank balance from the UI"""
        try:
            # Use JavaScript to find the bank balance in live DOM
            script = """
            var span = document.querySelector('span[data-testid="amount-box_amount"]');
            if (span) {
                return span.textContent || span.innerText;
            }
            return null;
            """

            balance_text = self.driver.execute_script(script)

            if balance_text:
                # Remove any currency symbols, commas, or spaces
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
        """Detect the current/ended round multiplier from center (class ZmRXV)"""
        try:
            script = """
            // Find main multiplier with class 'ZmRXV'
            var mainMult = document.querySelector('span.ZmRXV');
            if (mainMult) {
                var text = mainMult.textContent.trim();
                var className = mainMult.className;

                // Check if round has ended (class contains 'false' means not animating = ended)
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

            # Only return multiplier if round has ended
            if not result.get("hasEnded"):
                return None

            # Parse multiplier
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

    def is_red_color(self, color_str: str) -> bool:
        """Check if color is red"""
        try:
            if not color_str or "rgb" not in color_str.lower():
                return False

            import re

            numbers = re.findall(r"\d+", color_str)
            if len(numbers) >= 3:
                r, g, b = int(numbers[0]), int(numbers[1]), int(numbers[2])
                # Red: high R, low G and B
                return r > 150 and g < 100 and b < 100

            return False
        except:
            return False

    def check_trigger(self) -> bool:
        """Check if trigger conditions are met"""
        recent = self.db.get_recent_multipliers(self.trigger_count)

        if len(recent) < self.trigger_count:
            return False

        # Check if all are under threshold
        all_under = all(m < self.trigger_threshold for m in recent)

        if all_under:
            self.log(f"🎯 TRIGGER! Last {self.trigger_count} rounds: {recent}")
            return True

        return False

    def enter_bet_amount(self, amount: float) -> bool:
        """Enter bet amount in FIRST betting panel only"""
        try:
            from selenium.webdriver.common.keys import Keys

            # Find first panel
            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                self.log("⚠️  No betting panels found!")
                return False

            first_panel = panels[0]

            # Find bet input within first panel
            bet_input = first_panel.find_element(
                By.CSS_SELECTOR, 'input[data-testid="bp-inp"]'
            )

            # Click to focus
            bet_input.click()
            time.sleep(0.2)

            # Select all and delete
            for _i in range(0, 8):
                bet_input.send_keys(Keys.BACKSPACE)
            time.sleep(0.2)

            # Type new amount
            bet_input.send_keys(str(int(amount)))
            time.sleep(0.3)

            # Verify
            final_value = bet_input.get_attribute("value")
            self.log(f"✓ Bet amount set to {final_value} (first panel)")

            return True

        except Exception as e:
            self.log(f"Failed to enter bet amount: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def click_bet_button(self) -> bool:
        """Click the BET button in FIRST panel using data-testid="b-btn" """
        try:
            # Find first panel
            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "div[data-singlebetpart]"
            )
            if not panels:
                self.log("⚠️  No betting panels found!")
                return False

            first_panel = panels[0]

            # Find BET button within first panel using data-testid
            bet_button = first_panel.find_element(
                By.CSS_SELECTOR, 'button[data-testid="b-btn"]'
            )

            # Click it
            bet_button.click()
            self.log("✓ BET button clicked (first panel)")
            time.sleep(0.5)

            return True

        except Exception as e:
            self.log(f"Failed to click bet button: {e}")
            import traceback

            self.log(traceback.format_exc())
            return False

    def place_bet(self, amount: float) -> bool:
        """Place a bet with the specified amount"""
        # Enter bet amount
        if not self.enter_bet_amount(amount):
            return False

        # Click bet button
        if not self.click_bet_button():
            return False

        self.waiting_for_result = True
        return True

    def calc_next_bet(self) -> float:
        """Calculate next bet amount using martingale"""
        if self.consecutive_losses == 0:
            return self.base_bet
        return self.base_bet * (2**self.consecutive_losses)

    def handle_result(self, multiplier: float):
        """Handle bet result"""
        if multiplier >= self.auto_cashout:
            # Win!
            profit = self.current_bet * (self.auto_cashout - 1)
            self.total_profit += profit
            self.db.add_bet(self.current_bet, "win", multiplier, profit)
            self.consecutive_losses = 0
            self.current_bet = self.base_bet

            self.log(
                f"✅ WIN! {multiplier}x | Profit: +{profit:.0f} | Total: {self.total_profit:.0f}"
            )
        else:
            # Loss
            loss = self.current_bet
            self.total_profit -= loss
            self.db.add_bet(self.current_bet, "loss", multiplier, -loss)
            self.consecutive_losses += 1
            self.current_bet = self.calc_next_bet()

            self.log(
                f"❌ LOSS! {multiplier}x | Loss: -{loss:.0f} | Total: {self.total_profit:.0f}"
            )
            self.log(
                f"   Consecutive losses: {self.consecutive_losses} | Next bet: {self.current_bet:.0f}"
            )

        self.waiting_for_result = False

    def check_stop_conditions(self) -> bool:
        """Check if we should stop"""
        if self.total_profit <= -self.max_loss:
            self.log(f"🛑 STOP: Max loss reached ({abs(self.total_profit):.0f})")
            return False

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.log(
                f"🛑 STOP: Max consecutive losses reached ({self.consecutive_losses})"
            )
            return False

        return True

    def run(self):
        """Main bot loop"""
        try:
            self.log("=" * 60)
            self.log("🤖 CRASHER BOT STARTING")
            self.log("=" * 60)

            # Initialize
            if not self.init_driver():
                return

            # Login
            if not self.login():
                return

            # Navigate to game
            if not self.navigate_to_game():
                return

            # Setup auto cashout
            if not self.setup_auto_cashout():
                self.log("⚠️  Failed to setup auto cashout, but continuing...")

            # Show configuration
            self.log("=" * 60)
            self.log("📋 CONFIGURATION:")
            self.log(f"   Base Bet: {self.base_bet}")
            self.log(f"   Auto Cashout: {self.auto_cashout}x")
            self.log(
                f"   Trigger: {self.trigger_count} rounds under {self.trigger_threshold}x"
            )
            self.log(f"   Max Loss: {self.max_loss}")
            self.log(f"   Max Consecutive Losses: {self.max_consecutive_losses}")
            self.log("=" * 60)
            self.log("🎰 BOT RUNNING - Monitoring multipliers...")
            self.log("=" * 60)

            self.running = True

            # Main loop
            while self.running:
                # Check stop conditions
                if not self.check_stop_conditions():
                    break

                # Detect new multiplier
                new_mult = self.detect_current_multiplier()

                if new_mult and new_mult != self.last_seen_multiplier:
                    self.last_seen_multiplier = new_mult

                    # Increment round counter
                    self.rounds_since_setup += 1

                    # Re-setup auto-cashout every 20 rounds to keep session active
                    if self.rounds_since_setup >= 2:
                        self.log(
                            "🔄 Re-setting up auto-cashout (keeping session active)..."
                        )
                        self.setup_auto_cashout()

                    # Get bettor count for this round
                    bettor_count = self.get_bettor_count()

                    # Get bank balance
                    bank_balance = self.get_bank_balance()

                    # Log round info with bank balance
                    log_parts = [f"🎲 Round ended: {new_mult}x"]

                    if bettor_count:
                        log_parts.append(f"Bettors: {bettor_count}")

                    if bank_balance is not None:
                        log_parts.append(f"💰 Bank: {bank_balance:,.0f}")

                    self.log(" | ".join(log_parts))

                    # Save to database with bettor count
                    self.db.add_multiplier(new_mult, bettor_count)

                    # Handle result if we were waiting
                    if self.waiting_for_result:
                        self.handle_result(new_mult)

                    # Check trigger and place bet
                    if not self.waiting_for_result and self.check_trigger():
                        time.sleep(2)
                        bet_amount = self.calc_next_bet()
                        self.log(f"💰 Placing bet: {bet_amount}")

                        if self.place_bet(bet_amount):
                            self.current_bet = bet_amount
                        else:
                            self.log("⚠️  Failed to place bet!")

                time.sleep(0.5)

        except KeyboardInterrupt:
            self.log("\n⚠️  Bot stopped by user")
        except Exception as e:
            self.log(f"❌ Error: {e}")
        finally:
            self.running = False
            self.log("=" * 60)
            self.log("📊 SESSION SUMMARY:")
            self.log(f"   Total Profit/Loss: {self.total_profit:.0f}")
            self.log(f"   Consecutive Losses: {self.consecutive_losses}")

            # Get final bank balance
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
            self.log("🛑 Bot shut down")


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
