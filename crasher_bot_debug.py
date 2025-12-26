#!/usr/bin/env python3
"""
Crasher Bot - Debug Version with Performance Monitoring
Tracks timing metrics to identify delay sources
"""

import json
import logging
import sqlite3
import time
import psutil
import platform
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

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
    format="%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("crasher_bot_debug.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class TimingMetrics:
    """Track timing for performance analysis"""
    round_start_time: Optional[float] = None
    detection_time: Optional[float] = None
    db_write_time: Optional[float] = None
    total_delay: Optional[float] = None
    
    # Network/Browser metrics
    script_execution_time: Optional[float] = None
    dom_query_time: Optional[float] = None
    
    def reset(self):
        self.round_start_time = None
        self.detection_time = None
        self.db_write_time = None
        self.total_delay = None
        self.script_execution_time = None
        self.dom_query_time = None


@dataclass
class SystemMetrics:
    """System resource metrics"""
    cpu_percent: float
    ram_percent: float
    ram_available_mb: float
    network_sent_mb: float
    network_recv_mb: float
    timestamp: datetime
    
    def __str__(self):
        return (f"CPU: {self.cpu_percent:.1f}% | "
                f"RAM: {self.ram_percent:.1f}% ({self.ram_available_mb:.0f}MB free) | "
                f"Net: ↑{self.network_sent_mb:.2f}MB ↓{self.network_recv_mb:.2f}MB")


class PerformanceMonitor:
    """Monitor system and network performance"""
    
    def __init__(self):
        self.net_io_start = psutil.net_io_counters()
        self.round_timings = deque(maxlen=100)  # Keep last 100 rounds
        
    def get_system_metrics(self) -> SystemMetrics:
        """Get current system metrics"""
        net_io = psutil.net_io_counters()
        
        # Calculate network usage since start
        net_sent_mb = (net_io.bytes_sent - self.net_io_start.bytes_sent) / (1024 * 1024)
        net_recv_mb = (net_io.bytes_recv - self.net_io_start.bytes_recv) / (1024 * 1024)
        
        mem = psutil.virtual_memory()
        
        return SystemMetrics(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_percent=mem.percent,
            ram_available_mb=mem.available / (1024 * 1024),
            network_sent_mb=net_sent_mb,
            network_recv_mb=net_recv_mb,
            timestamp=datetime.now()
        )
    
    def add_round_timing(self, metrics: TimingMetrics):
        """Add timing metrics for a round"""
        self.round_timings.append(metrics)
    
    def get_timing_stats(self) -> Dict:
        """Get statistics on round timings"""
        if not self.round_timings:
            return {}
        
        delays = [m.total_delay for m in self.round_timings if m.total_delay is not None]
        detection_times = [m.detection_time for m in self.round_timings if m.detection_time is not None]
        script_times = [m.script_execution_time for m in self.round_timings if m.script_execution_time is not None]
        
        return {
            'avg_delay': sum(delays) / len(delays) if delays else 0,
            'max_delay': max(delays) if delays else 0,
            'min_delay': min(delays) if delays else 0,
            'avg_detection': sum(detection_times) / len(detection_times) if detection_times else 0,
            'avg_script_exec': sum(script_times) / len(script_times) if script_times else 0,
            'sample_size': len(self.round_timings)
        }


class DebugDatabase:
    """Database with performance metrics logging"""
    
    def __init__(self, db_path: str = "./crasher_data_debug.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()
        
    def _init_tables(self):
        cursor = self.conn.cursor()
        
        # Original multipliers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Performance metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER,
                multiplier REAL,
                detection_delay_ms INTEGER,
                script_execution_ms INTEGER,
                db_write_ms INTEGER,
                total_delay_ms INTEGER,
                cpu_percent REAL,
                ram_percent REAL,
                ram_available_mb REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (round_id) REFERENCES multipliers(id)
            )
        """)
        
        # System snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cpu_percent REAL,
                ram_percent REAL,
                ram_available_mb REAL,
                network_sent_mb REAL,
                network_recv_mb REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
    
    def add_multiplier(self, multiplier: float, bettor_count: Optional[int] = None) -> int:
        """Add multiplier and return its ID"""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO multipliers (multiplier, bettor_count) VALUES (?, ?)",
            (multiplier, bettor_count),
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def add_performance_metrics(self, round_id: int, multiplier: float, 
                               timing: TimingMetrics, system: SystemMetrics):
        """Log performance metrics for a round"""
        cursor = self.conn.cursor()
        
        detection_ms = int(timing.detection_time * 1000) if timing.detection_time else None
        script_ms = int(timing.script_execution_time * 1000) if timing.script_execution_time else None
        db_ms = int(timing.db_write_time * 1000) if timing.db_write_time else None
        total_ms = int(timing.total_delay * 1000) if timing.total_delay else None
        
        cursor.execute("""
            INSERT INTO performance_metrics 
            (round_id, multiplier, detection_delay_ms, script_execution_ms, 
             db_write_ms, total_delay_ms, cpu_percent, ram_percent, ram_available_mb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (round_id, multiplier, detection_ms, script_ms, db_ms, total_ms,
              system.cpu_percent, system.ram_percent, system.ram_available_mb))
        
        self.conn.commit()
    
    def add_system_snapshot(self, system: SystemMetrics):
        """Log system snapshot"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO system_snapshots 
            (cpu_percent, ram_percent, ram_available_mb, network_sent_mb, network_recv_mb)
            VALUES (?, ?, ?, ?, ?)
        """, (system.cpu_percent, system.ram_percent, system.ram_available_mb,
              system.network_sent_mb, system.network_recv_mb))
        self.conn.commit()
    
    def get_recent_multipliers(self, count: int) -> List[float]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT multiplier FROM multipliers ORDER BY id DESC LIMIT ?", (count,)
        )
        return [row[0] for row in reversed(cursor.fetchall())]
    
    def close(self):
        self.conn.close()


class DebugCrasherBot:
    """Debug version of bot with performance monitoring"""
    
    def __init__(self, config_path: str = "./bot_config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        
        self.username = self.config["username"]
        self.password = self.config["password"]
        self.game_url = self.config["game_url"]
        
        self.driver = None
        self.wait = None
        self.db = DebugDatabase()
        self.perf_monitor = PerformanceMonitor()
        self.last_seen_multiplier = None
        self.running = False
        self.round_count = 0
        
        # Log system info
        self.log_system_info()
    
    def log_system_info(self):
        """Log system information"""
        self.log("=" * 80)
        self.log("SYSTEM INFORMATION:")
        self.log(f"  OS: {platform.system()} {platform.release()}")
        self.log(f"  Architecture: {platform.machine()}")
        self.log(f"  Python: {platform.python_version()}")
        self.log(f"  CPU Cores: {psutil.cpu_count(logical=False)} physical, {psutil.cpu_count()} logical")
        
        mem = psutil.virtual_memory()
        self.log(f"  RAM: {mem.total / (1024**3):.1f} GB total, {mem.available / (1024**3):.1f} GB available")
        
        try:
            import selenium
            self.log(f"  Selenium: {selenium.__version__}")
        except:
            pass
        
        try:
            self.log(f"  Chrome Driver: undetected-chromedriver {uc.__version__ if hasattr(uc, '__version__') else 'unknown'}")
        except:
            pass
        
        self.log("=" * 80)
    
    def log(self, message: str):
        try:
            logger.info(message)
        except UnicodeEncodeError:
            clean_msg = message.encode("ascii", "ignore").decode("ascii")
            logger.info(clean_msg)
    
    def init_driver(self) -> bool:
        """Initialize Chrome driver"""
        try:
            if not UNDETECTED_AVAILABLE:
                self.log("ERROR: undetected-chromedriver not installed!")
                return False
            
            self.log("Initializing Chrome driver...")
            start_time = time.time()
            
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
            
            init_time = time.time() - start_time
            self.log(f"OK Driver initialized in {init_time:.2f}s")
            return True
        except Exception as e:
            self.log(f"Failed to initialize driver: {e}")
            return False
    
    def login(self) -> bool:
        """Login to website"""
        try:
            self.log("Navigating to login page...")
            start_time = time.time()
            self.driver.get("https://1000bet.in")
            load_time = time.time() - start_time
            self.log(f"Page loaded in {load_time:.2f}s")
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
        """Navigate to game"""
        try:
            self.log(f"Loading game: {self.game_url}")
            start_time = time.time()
            self.driver.get(self.game_url)
            load_time = time.time() - start_time
            self.log(f"Game page loaded in {load_time:.2f}s")
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
            
            self.close_tutorial_popup()
            self.log("OK Game loaded successfully!")
            return True
            
        except Exception as e:
            self.log(f"Failed to load game: {e}")
            return False
    
    def close_tutorial_popup(self):
        """Close tutorial popup"""
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
    
    def detect_current_multiplier(self) -> tuple[Optional[float], TimingMetrics]:
        """
        Detect current/ended round multiplier with timing metrics
        Returns: (multiplier, timing_metrics)
        """
        timing = TimingMetrics()
        
        try:
            # Measure script execution time
            script_start = time.time()
            
            script = """
            var startTime = performance.now();
            var mainMult = document.querySelector('span.ZmRXV');
            var domQueryTime = performance.now() - startTime;
            
            if (mainMult) {
                var hasEnded = mainMult.className.includes('false');
                return {
                    text: mainMult.textContent.trim(), 
                    hasEnded: hasEnded,
                    domQueryTime: domQueryTime
                };
            }
            return {found: false, domQueryTime: domQueryTime};
            """
            
            result = self.driver.execute_script(script)
            timing.script_execution_time = time.time() - script_start
            
            if result.get('domQueryTime'):
                timing.dom_query_time = result['domQueryTime'] / 1000.0  # Convert to seconds
            
            if not result.get("hasEnded"):
                return None, timing
            
            text = result.get("text", "")
            if "x" in text.lower():
                import re
                match = re.search(r"(\d+\.?\d*)x", text, re.IGNORECASE)
                if match:
                    mult = float(match.group(1))
                    if 1.0 <= mult <= 10000.0:
                        return mult, timing
            
            return None, timing
            
        except Exception as e:
            self.log(f"Error detecting multiplier: {e}")
            return None, timing
    
    def get_bettor_count(self) -> Optional[int]:
        """Get bettor count"""
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
    
    def run_debug_mode(self, max_rounds: int = 100):
        """
        Run in debug mode monitoring performance
        
        Args:
            max_rounds: Maximum rounds to monitor (0 = unlimited)
        """
        try:
            self.log("=" * 80)
            self.log("DEBUG MODE - PERFORMANCE MONITORING")
            self.log(f"Will monitor {max_rounds if max_rounds > 0 else 'unlimited'} rounds")
            self.log("=" * 80)
            
            if not self.init_driver():
                return
            
            if not self.login():
                return
            
            if not self.navigate_to_game():
                return
            
            self.log("=" * 80)
            self.log("STARTING MONITORING...")
            self.log("Monitoring metrics:")
            self.log("  - Round detection delay")
            self.log("  - Script execution time")
            self.log("  - Database write time")
            self.log("  - System resources (CPU, RAM)")
            self.log("  - Network usage")
            self.log("=" * 80)
            
            self.running = True
            snapshot_counter = 0
            
            while self.running:
                # Take system snapshot every 10 rounds
                if snapshot_counter % 10 == 0:
                    system_metrics = self.perf_monitor.get_system_metrics()
                    self.db.add_system_snapshot(system_metrics)
                
                snapshot_counter += 1
                
                # Detect multiplier with timing
                new_mult, timing = self.detect_current_multiplier()
                
                if new_mult and new_mult != self.last_seen_multiplier:
                    timing.detection_time = time.time()
                    self.last_seen_multiplier = new_mult
                    self.round_count += 1
                    
                    # Get system metrics at detection time
                    system_metrics = self.perf_monitor.get_system_metrics()
                    
                    # Get additional info
                    bettor_count = self.get_bettor_count()
                    
                    # Write to database and measure time
                    db_start = time.time()
                    round_id = self.db.add_multiplier(new_mult, bettor_count)
                    timing.db_write_time = time.time() - db_start
                    
                    # Calculate total delay (this is approximate - real round end time unknown)
                    timing.total_delay = timing.script_execution_time + timing.db_write_time
                    
                    # Log performance metrics
                    self.db.add_performance_metrics(round_id, new_mult, timing, system_metrics)
                    self.perf_monitor.add_round_timing(timing)
                    
                    # Build detailed log message
                    log_parts = [
                        f"Round #{self.round_count}: {new_mult}x",
                        f"Detection: {timing.detection_time:.3f}s",
                    ]
                    
                    if timing.script_execution_time:
                        log_parts.append(f"Script: {timing.script_execution_time*1000:.1f}ms")
                    
                    if timing.dom_query_time:
                        log_parts.append(f"DOM: {timing.dom_query_time*1000:.1f}ms")
                    
                    if timing.db_write_time:
                        log_parts.append(f"DB: {timing.db_write_time*1000:.1f}ms")
                    
                    if bettor_count:
                        log_parts.append(f"Bettors: {bettor_count}")
                    
                    self.log(" | ".join(log_parts))
                    self.log(f"  System: {system_metrics}")
                    
                    # Show timing stats every 10 rounds
                    if self.round_count % 10 == 0:
                        stats = self.perf_monitor.get_timing_stats()
                        self.log("─" * 80)
                        self.log(f"TIMING STATS (last {stats['sample_size']} rounds):")
                        self.log(f"  Avg Total Delay: {stats['avg_delay']*1000:.1f}ms")
                        self.log(f"  Min/Max Delay: {stats['min_delay']*1000:.1f}ms / {stats['max_delay']*1000:.1f}ms")
                        self.log(f"  Avg Script Exec: {stats['avg_script_exec']*1000:.1f}ms")
                        self.log(f"  Avg Detection: {stats['avg_detection']:.3f}s")
                        self.log("─" * 80)
                    
                    # Stop if max rounds reached
                    if max_rounds > 0 and self.round_count >= max_rounds:
                        self.log(f"\nReached {max_rounds} rounds, stopping...")
                        break
                
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            self.log("\nMonitoring stopped by user")
        except Exception as e:
            self.log(f"ERROR: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.running = False
            self.show_final_report()
            
            if self.driver:
                self.driver.quit()
            self.db.close()
            self.log("Monitoring shut down")
    
    def show_final_report(self):
        """Show final performance report"""
        self.log("\n" + "=" * 80)
        self.log("FINAL PERFORMANCE REPORT")
        self.log("=" * 80)
        
        stats = self.perf_monitor.get_timing_stats()
        
        self.log(f"Total Rounds Monitored: {self.round_count}")
        
        if stats:
            self.log(f"\nTIMING ANALYSIS:")
            self.log(f"  Average Total Delay: {stats['avg_delay']*1000:.1f}ms")
            self.log(f"  Minimum Delay: {stats['min_delay']*1000:.1f}ms")
            self.log(f"  Maximum Delay: {stats['max_delay']*1000:.1f}ms")
            self.log(f"  Average Script Execution: {stats['avg_script_exec']*1000:.1f}ms")
            self.log(f"  Average Detection Time: {stats['avg_detection']:.3f}s")
            
            # Calculate delay classification
            if stats['avg_delay'] > 10:  # > 10 seconds
                self.log(f"\n⚠️  HIGH DELAY DETECTED ({stats['avg_delay']:.1f}s average)")
                self.log("Possible causes:")
                self.log("  - Slow network connection")
                self.log("  - High server latency")
                self.log("  - Browser/Selenium overhead")
                self.log("  - Insufficient system resources")
            elif stats['avg_delay'] > 5:  # > 5 seconds
                self.log(f"\n⚠️  MODERATE DELAY DETECTED ({stats['avg_delay']:.1f}s average)")
                self.log("Possible causes:")
                self.log("  - Network latency")
                self.log("  - System resource constraints")
            else:
                self.log(f"\n✓ Normal performance ({stats['avg_delay']*1000:.0f}ms average)")
        
        # Get system metrics summary
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT AVG(cpu_percent), AVG(ram_percent), AVG(ram_available_mb)
                FROM performance_metrics
            """)
            cpu_avg, ram_avg, ram_avail = cursor.fetchone()
            
            self.log(f"\nSYSTEM RESOURCE USAGE:")
            self.log(f"  Average CPU: {cpu_avg:.1f}%")
            self.log(f"  Average RAM: {ram_avg:.1f}% ({ram_avail:.0f}MB available)")
            
            if cpu_avg > 80:
                self.log("  ⚠️  High CPU usage detected")
            if ram_avg > 80:
                self.log("  ⚠️  High RAM usage detected")
        except:
            pass
        
        self.log("\n" + "=" * 80)
        self.log("Full metrics saved to: crasher_data_debug.db")
        self.log("Detailed logs saved to: crasher_bot_debug.log")
        self.log("=" * 80)


def main():
    import sys
    
    max_rounds = 100  # Default: monitor 100 rounds
    
    if len(sys.argv) > 1:
        try:
            max_rounds = int(sys.argv[1])
        except:
            print("Usage: python crasher_bot_debug.py [max_rounds]")
            print("Example: python crasher_bot_debug.py 50")
            sys.exit(1)
    
    try:
        bot = DebugCrasherBot(config_path="./bot_config.json")
        bot.run_debug_mode(max_rounds=max_rounds)
    except FileNotFoundError:
        logger.error("Config file 'bot_config.json' not found!")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
