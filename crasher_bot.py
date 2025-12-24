#!/usr/bin/env python3
"""
Crasher Bot - Multi-Strategy Version
Observes multipliers and manages multiple betting strategies simultaneously
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

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
    bet_multiplier: float  # Custom multiplier for losses (e.g., 2.0 for martingale, 1.5 for conservative)

    # Runtime state
    current_bet: float
    consecutive_losses: int
    total_profit: float
    waiting_for_result: bool
    is_active: bool  # Whether strategy is currently active

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


class Database:
    """Database for tracking bets and multipliers"""

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
    """Crasher bot with multiple strategies"""

    def __init__(self, config_path: str = "./bot_config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Account credentials
        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]

        # Global limits
        self.max_loss = float(self.config.get("max_loss", 100000000))

        # Load strategies
        self.strategies: Dict[str, StrategyState] = {}
        self._load_strategies()

        # Bot state
        self.driver = None
        self.wait = None
        self.db = Database()
        self.last_seen_multiplier = None
        self.running = False
        self.auto_cashout_configured = {}  # Track per strategy
        self.rounds_since_setup = 0
        self.total_profit = 0.0  # Global profit across all strategies

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
                bet_multiplier=float(
                    strategy_config.get("bet_multiplier", 2.0)
                ),  # Default to 2.0 (standard martingale)
                current_bet=float(strategy_config["base_bet"]),
                consecutive_losses=0,
                total_profit=0.0,
                waiting_for_result=False,
                is_active=False,
            )
            self.strategies[name] = strategy
            self.log(
                f"Loaded strategy: {name} - {strategy.trigger_count} under {strategy.trigger_threshold}x → cashout at {strategy.auto_cashout}x (multiplier: {strategy.bet_multiplier}x)"
            )

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

            # Find game iframe
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

            # Check for nested iframes
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

                # Click AUTO button
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

                # Enable auto cashout toggle
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

                # Set cashout value with scroll and proper wait
                from selenium.webdriver.common.action_chains import ActionChains
                from selenium.webdriver.common.keys import Keys

                panels = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-singlebetpart]"
                )
                auto_input = panels[0].find_element(
                    By.CSS_SELECTOR, 'input[data-testid="aut-co-inp"]'
                )

                # Scroll element into view
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", auto_input
                )
                time.sleep(0.1)

                # Use ActionChains for more reliable interaction
                actions = ActionChains(self.driver)
                actions.move_to_element(auto_input).click().perform()
                time.sleep(0.1)

                # Clear existing value
                for _ in range(5):
                    auto_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.1)

                # Enter new value
                auto_input.send_keys(str(strategy.auto_cashout))
                time.sleep(0.1)

                # Verify the value was set
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
        """Get current bank balance"""
        try:
            script = """
            var span = document.querySelector('span[data-testid="amount-box_amount"]');
            return span ? span.textContent : null;
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
        except:
            return None

    def detect_current_multiplier(self) -> Optional[float]:
        """Detect current/ended round multiplier"""
        try:
            script = """
            var mainMult = document.querySelector('span.ZmRXV');
            if (mainMult) {
                var hasEnded = mainMult.className.includes('false');
                return {text: mainMult.textContent.trim(), hasEnded: hasEnded};
            }
            return {found: false};
            """

            result = self.driver.execute_script(script)
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
        except:
            return None

    def check_trigger(self, strategy: StrategyState) -> bool:
        """Check if trigger conditions are met for a strategy"""
        recent = self.db.get_recent_multipliers(strategy.trigger_count)

        # Need EXACT count of multipliers to trigger (prevents false triggers on startup)
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

        # Check each strategy
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
            self.log("MULTI-STRATEGY CRASHER BOT STARTING")
            self.log("=" * 60)

            if not self.init_driver():
                return

            if not self.login():
                return

            if not self.navigate_to_game():
                return

            # Initial setup with first strategy's cashout (for session keep-alive)
            first_strategy = list(self.strategies.values())[0]
            if not self.setup_auto_cashout(first_strategy):
                self.log(f"WARNING: Could not setup initial auto cashout")

            self.log("=" * 60)
            self.log("ACTIVE STRATEGIES:")
            for name, strategy in self.strategies.items():
                self.log(f"  [{name}]")
                self.log(f"    Base Bet: {strategy.base_bet}")
                self.log(f"    Auto Cashout: {strategy.auto_cashout}x")
                self.log(
                    f"    Trigger: {strategy.trigger_count} rounds under {strategy.trigger_threshold}x"
                )
                self.log(f"    Bet Multiplier: {strategy.bet_multiplier}x (after loss)")
                self.log(
                    f"    Max Consecutive Losses: {strategy.max_consecutive_losses}"
                )
            self.log(f"  Global Max Loss: {self.max_loss}")
            self.log("=" * 60)
            self.log("STRATEGY RULES:")
            self.log("  - Only ONE strategy can bet at a time")
            self.log("  - Active strategy has exclusive access to bank")
            self.log(
                "  - Other strategies monitor but don't bet until active one finishes"
            )
            self.log("  - Auto-cashout configured ONLY when placing bet")
            self.log(
                f"  - Need EXACT {max(s.trigger_count for s in self.strategies.values())} rounds before any triggers (prevents false triggers)"
            )
            self.log("=" * 60)
            self.log("BOT RUNNING - Monitoring multipliers...")
            self.log("=" * 60)

            self.running = True
            active_strategy_name = None  # Track which strategy is currently active

            while self.running:
                if not self.check_stop_conditions():
                    break

                new_mult = self.detect_current_multiplier()

                if new_mult and new_mult != self.last_seen_multiplier:
                    self.last_seen_multiplier = new_mult
                    self.rounds_since_setup += 1

                    # Keep session alive every 20 rounds (use first strategy's cashout)
                    if self.rounds_since_setup >= 20:
                        self.log(
                            "Keeping session active (resetting auto-cashout to first strategy)..."
                        )
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

                    # Handle active strategy result first
                    if active_strategy_name:
                        active_strategy = self.strategies[active_strategy_name]
                        if active_strategy.waiting_for_result:
                            self.handle_result(active_strategy, new_mult)

                            # If strategy finished (no longer waiting), clear active status
                            if not active_strategy.waiting_for_result:
                                self.log(
                                    f"[{active_strategy_name}] Strategy finished, releasing bank"
                                )
                                active_strategy_name = None

                    # Only check for new triggers if NO strategy is currently active
                    if not active_strategy_name:
                        # Check all strategies for triggers (in order)
                        for name, strategy in self.strategies.items():
                            if not strategy.waiting_for_result and self.check_trigger(
                                strategy
                            ):
                                # This strategy triggered!
                                self.log(
                                    f"[{name}] Strategy ACTIVATED - Taking exclusive control of bank"
                                )

                                # Setup auto-cashout specifically for THIS strategy
                                self.log(
                                    f"[{name}] Configuring auto-cashout to {strategy.auto_cashout}x..."
                                )
                                if not self.setup_auto_cashout(strategy):
                                    self.log(
                                        f"[{name}] WARNING: Failed to setup auto-cashout, skipping bet"
                                    )
                                    continue

                                time.sleep(2)
                                bet_amount = strategy.calc_next_bet()

                                if self.place_bet(strategy, bet_amount):
                                    strategy.current_bet = bet_amount
                                    strategy.waiting_for_result = True
                                    active_strategy_name = (
                                        name  # Mark this strategy as active
                                    )
                                    break  # Only activate ONE strategy per round

                time.sleep(0.1)

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
