"""
Hot Streak Prediction Module - Updated with Database Combination Loading
Analyzes game state and loads combinations from database with timing data
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class PredictionMethod:
    """Base class for prediction methods"""

    def __init__(self, method_id: int, name: str, accuracy: float):
        self.method_id = method_id
        self.name = name
        self.accuracy = accuracy

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        """
        Check if method conditions are met
        Returns: {prediction: rounds, confidence: float, details: str} or None
        """
        raise NotImplementedError


class Method1_ProgressiveWindow(PredictionMethod):
    """Method 1: Progressive Window Probability (8.1/10)"""

    def __init__(self):
        super().__init__(1, "Progressive Window", 8.1)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        rounds_since_hot = game_state.get("rounds_since_last_hotstreak", 0)

        if rounds_since_hot == 0:
            return None

        # Loosened: trigger 3-8 rounds (was 3-6)
        if 3 <= rounds_since_hot <= 8:
            return {
                "prediction": 5,
                "confidence": 0.362,
                "details": f"Early window ({rounds_since_hot}r)",
            }
        # Add medium window
        elif 9 <= rounds_since_hot <= 15:
            return {
                "prediction": 12,
                "confidence": 0.229,
                "details": f"Medium window ({rounds_since_hot}r)",
            }

        return None


class Method2_CompositeSignal(PredictionMethod):
    """Method 2: Composite Multi-Signal (7.3/10)"""

    def __init__(self):
        super().__init__(2, "Composite Multi-Signal", 7.3)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        score = 0

        # Signal 1: Last streak type
        if game_state.get("last_streak_type") == "strong":
            score += 2
        elif game_state.get("last_streak_type") == "weak":
            score += 1

        # Signal 2: Last streak quality (loosened)
        if game_state.get("last_streak_average", 0) > 5.0:  # Was 6.0
            score += 1

        # Signal 3: Pre-pattern
        last_10 = game_state.get("last_10_before_streak", [])
        if len(last_10) == 10:
            above_2x = sum(1 for m in last_10 if m >= 2.0)
            if above_2x >= 4:
                score += 1

        # Signal 4: Post-momentum (loosened)
        first_10_after = game_state.get("first_10_after_streak", [])
        if len(first_10_after) == 10:
            above_2x = sum(1 for m in first_10_after if m >= 2.0)
            if above_2x >= 4:  # Was 5
                score += 2

        # Signal 5: No cold streak
        if not game_state.get("cold_streak_occurred", False):
            score += 1

        # Loosened: trigger at score 3+ (was 4+)
        if score < 3:
            return None

        if score >= 5:
            return {
                "prediction": 3,
                "confidence": 0.75,
                "details": f"Score:{score}/7 (Very strong)",
            }
        elif score >= 3:
            return {
                "prediction": 8,
                "confidence": 0.60,
                "details": f"Score:{score}/7 (Medium)",
            }

        return None


class Method3_StreakAverage(PredictionMethod):
    """Method 3: Streak Average Predictor (6.7/10)"""

    def __init__(self):
        super().__init__(3, "Streak Average", 6.7)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        avg = game_state.get("last_streak_average", 0)

        # Loosened: 4.0 instead of 6.0
        if avg == 0 or avg < 4.0:
            return None

        if avg >= 6.0:
            return {
                "prediction": 3,
                "confidence": 0.65,
                "details": "Extreme quality (>6x)",
            }
        else:  # 4.0-6.0
            return {
                "prediction": 7,
                "confidence": 0.50,
                "details": "High quality (4-6x)",
            }


class Method4_ColdStreak(PredictionMethod):
    """Method 4: Cold Streak Classifier (6.4/10)"""

    def __init__(self):
        super().__init__(4, "Cold Streak Classifier", 6.4)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        rounds_since_hot = game_state.get("rounds_since_last_hotstreak", 0)
        has_cold = game_state.get("cold_streak_occurred", False)

        if rounds_since_hot == 0:
            return None

        # Rule of 17: Special high-confidence signal
        if rounds_since_hot >= 17 and not has_cold:
            return {
                "prediction": 5,
                "confidence": 0.87,
                "details": "Rule of 17! (87% prob)",
            }

        # Loosened: Also trigger in critical zone (10-16 rounds)
        elif rounds_since_hot >= 10 and has_cold:
            return {
                "prediction": 12,
                "confidence": 0.55,
                "details": f"Critical zone ({rounds_since_hot}r)",
            }

        return None


class Method5_Momentum(PredictionMethod):
    """Method 5: Post-Streak Momentum Tracker (5.1/10)"""

    def __init__(self):
        super().__init__(5, "Momentum Tracker", 5.1)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        first_10 = game_state.get("first_10_after_streak", [])

        if len(first_10) < 10:
            return None

        above_2x = sum(1 for m in first_10 if m >= 2.0)

        # Loosened: trigger at 5+ instead of 7+
        if above_2x >= 7:
            return {
                "prediction": 2,
                "confidence": 0.75,
                "details": f"Very high momentum ({above_2x}/10)",
            }
        elif above_2x >= 5:
            return {
                "prediction": 5,
                "confidence": 0.60,
                "details": f"High momentum ({above_2x}/10)",
            }

        return None


class Method6_StreakType(PredictionMethod):
    """Method 6: Streak Type Momentum (5.0/10)"""

    def __init__(self):
        super().__init__(6, "Streak Type", 5.0)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        streak_type = game_state.get("last_streak_type")

        if not streak_type:
            return None

        # Loosened: trigger on both strong and weak
        if streak_type == "strong":
            return {
                "prediction": 5,
                "confidence": 0.65,
                "details": "Strong streak (80%+ ≥2x)",
            }
        else:  # weak
            return {
                "prediction": 10,
                "confidence": 0.45,
                "details": "Weak streak (70-79% ≥2x)",
            }


class Method7_Volatility(PredictionMethod):
    """Method 7: Volatility-Based Prediction (4.8/10)"""

    def __init__(self):
        super().__init__(7, "Volatility", 4.8)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        volatility = game_state.get("last_streak_volatility", 0)

        if volatility == 0 or volatility <= 30.0:  # ← Only high volatility
            return None

        return {"prediction": 11, "confidence": 0.48, "details": "High volatility"}


class Method8_SessionPattern(PredictionMethod):
    """Method 8: Session Pattern Recognition (3.9/10)"""

    def __init__(self):
        super().__init__(8, "Session Pattern", 3.9)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        session_id = game_state.get("session_id", 0)
        rounds_since_hot = game_state.get("rounds_since_last_hotstreak", 0)

        # Loosened: more sessions + earlier trigger
        high_activity_sessions = [60, 65, 11, 32, 34, 58]  # Was top 3, now top 6

        if session_id in high_activity_sessions and rounds_since_hot >= 8:  # Was 12
            return {
                "prediction": 10,
                "confidence": 0.45,
                "details": f"Active session #{session_id}",
            }

        return None


class Method9_PrePattern(PredictionMethod):
    """Method 9: Pre-Streak Pattern Detection (3.8/10)"""

    def __init__(self):
        super().__init__(9, "Pre-Pattern", 3.8)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        last_10 = game_state.get("recent_10_multipliers", [])

        if len(last_10) < 10:
            return None

        above_2x = sum(1 for m in last_10 if m >= 2.0)
        avg = sum(last_10) / 10
        max_val = max(last_10)

        # Loosened: 4+ rounds (was 5+), avg 3.0 (was 3.5)
        if above_2x >= 4 and avg >= 3.0 and max_val >= 6.0:  # All loosened
            return {
                "prediction": 8,
                "confidence": 0.50,
                "details": f"Signature match ({above_2x}/10 ≥2x, avg:{avg:.1f})",
            }

        return None


class Method10_Chain(PredictionMethod):
    """Method 10: Sequential Chain Analysis (3.3/10)"""

    def __init__(self):
        super().__init__(10, "Chain Analysis", 3.3)

    def check_trigger(self, game_state: Dict) -> Optional[Dict]:
        last_gap = game_state.get("last_hotstreak_gap", None)
        rounds_since_hot = game_state.get("rounds_since_last_hotstreak", 0)

        if last_gap is None:
            return None

        # Loosened: gap ≤5 (was ≤3), rounds 2-8 (was 2-6)
        if last_gap <= 5 and 2 <= rounds_since_hot <= 8:
            return {
                "prediction": last_gap + 1,
                "confidence": 0.40,
                "details": f"Chain pattern (gap:{last_gap}r, at {rounds_since_hot}r)",
            }

        return None


class PredictionAnalyzer:
    """Main analyzer that checks all methods and combinations from database"""

    def __init__(self, conn: sqlite3.Connection, log_func=None):
        self.conn = conn
        self.log = log_func or print
        self._init_signals_table()

        # Initialize all methods
        self.methods = [
            Method1_ProgressiveWindow(),
            Method2_CompositeSignal(),
            Method3_StreakAverage(),
            Method4_ColdStreak(),
            Method5_Momentum(),
            Method6_StreakType(),
            Method7_Volatility(),
            Method8_SessionPattern(),
            Method9_PrePattern(),
            Method10_Chain(),
        ]

        # Load combinations from database
        self.combinations = self._load_combinations_from_db()

    def _load_combinations_from_db(self) -> List[Dict]:
        """Load all combinations from the database with timing data"""
        cursor = self.conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    combo_id,
                    name,
                    short_name,
                    method_ids,
                    actual_accuracy,
                    avg_predicted_rounds,
                    earliest_prediction,
                    latest_prediction,
                    median_prediction,
                    prediction_mode,
                    prediction_accuracy_in_range
                FROM combinations
                ORDER BY actual_accuracy DESC
            """)

            combinations = []
            for row in cursor.fetchall():
                (
                    combo_id,
                    name,
                    short_name,
                    method_ids_str,
                    accuracy,
                    avg_pred,
                    earliest,
                    latest,
                    median,
                    pred_mode,
                    mode_acc,
                ) = row

                # Parse method IDs
                method_ids = [int(m) for m in method_ids_str.split(",")]

                combinations.append(
                    {
                        "combo_id": combo_id,
                        "name": name,
                        "short_name": short_name,
                        "methods": method_ids,
                        "accuracy": accuracy or 0,
                        "avg_predicted_rounds": avg_pred,
                        "earliest_prediction": earliest,
                        "latest_prediction": latest,
                        "median_prediction": median,
                        "prediction_mode": pred_mode,
                        "mode_accuracy": mode_acc,
                    }
                )

            self.log(f"✓ Loaded {len(combinations)} combinations from database")
            return combinations

        except sqlite3.OperationalError as e:
            self.log(f"⚠️  Could not load combinations from database: {e}")
            self.log("   Using empty combinations list")
            return []

    def _init_signals_table(self):
        """Create signals table for logging predictions"""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                multiplier_id INTEGER,
                method_id INTEGER NOT NULL,
                method_name TEXT NOT NULL,
                prediction_rounds INTEGER,
                confidence REAL,
                details TEXT,
                FOREIGN KEY (multiplier_id) REFERENCES multipliers(id)
            )
        """)
        self.conn.commit()

    def log_signal(
        self,
        multiplier_id: int,
        method_id: int,
        method_name: str,
        prediction: int,
        confidence: float,
        details: str,
    ):
        """Log a triggered method signal to database"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO signals (multiplier_id, method_id, method_name,
                               prediction_rounds, confidence, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (multiplier_id, method_id, method_name, prediction, confidence, details),
        )
        self.conn.commit()

    def analyze_round(self, game_state: Dict, current_multiplier_id: int):
        """
        Analyze current game state and check all methods
        Returns list of triggered methods and any matching combinations

        NOTE: This should only be called ONCE per round!
        """
        triggered_methods = []

        # Check each method
        for method in self.methods:
            result = method.check_trigger(game_state)

            if result:
                triggered_methods.append(
                    {
                        "method_id": method.method_id,
                        "method_name": method.name,
                        "accuracy": method.accuracy,
                        "prediction": result["prediction"],
                        "confidence": result["confidence"],
                        "details": result["details"],
                    }
                )

                # Log to database
                self.log_signal(
                    current_multiplier_id,
                    method.method_id,
                    method.name,
                    result["prediction"],
                    result["confidence"],
                    result["details"],
                )

        # Check for matching combinations from database
        matching_combinations = []
        if triggered_methods:
            triggered_ids = set(m["method_id"] for m in triggered_methods)

            for combo in self.combinations:
                combo_set = set(combo["methods"])
                if combo_set.issubset(triggered_ids):
                    matching_combinations.append(combo)

        return triggered_methods, matching_combinations

    def format_analysis_output(
        self, triggered_methods: List[Dict], matching_combinations: List[Dict]
    ) -> List[str]:
        """Format analysis results for logging with timing data"""
        output = []

        if not triggered_methods:
            return output

        # Log each triggered method
        for method in triggered_methods:
            line = (
                f"M{method['method_id']} ({method['method_name']}) "
                f"→ {method['prediction']}r ({method['confidence'] * 100:.0f}% conf) "
                f"| {method['details']} | Acc:{method['accuracy']}/10"
            )
            output.append(line)

        # Log matching combinations with timing data
        for combo in matching_combinations:
            methods_str = "+".join([f"M{m}" for m in combo["methods"]])

            # Build timing info
            timing_parts = []
            if (
                combo.get("earliest_prediction") is not None
                and combo.get("latest_prediction") is not None
            ):
                timing_parts.append(
                    f"Range: {combo['earliest_prediction']}-{combo['latest_prediction']}r"
                )
            if combo.get("median_prediction") is not None:
                timing_parts.append(f"Median: {combo['median_prediction']:.0f}r")
            if combo.get("prediction_mode"):
                timing_parts.append(f"Mode: {combo['prediction_mode']}")

            timing_str = " | ".join(timing_parts) if timing_parts else "No timing data"

            line = (
                f"🏆 COMBO #{combo['combo_id']}: {methods_str} ({combo['short_name']}) "
                f"→ Acc:{combo['accuracy']:.1f}% | {timing_str}"
            )
            output.append(line)

        return output


def create_game_state_tracker():
    """
    Helper class to track game state for prediction analysis
    Can be integrated into the main bot
    """

    class GameStateTracker:
        def __init__(self):
            self.recent_multipliers = []
            self.last_hotstreak = None
            self.last_hotstreak_end_round = 0
            self.current_round = 0
            self.cold_streak_active = False
            self.cold_streak_start = 0

        def add_multiplier(self, multiplier: float):
            """Add new multiplier and update tracking"""
            self.current_round += 1
            self.recent_multipliers.append(multiplier)

            # Keep last 50 for analysis
            if len(self.recent_multipliers) > 50:
                self.recent_multipliers.pop(0)

            # Detect hot streaks (simplified - 10-15 consecutive with 65%+ ≥2.0x)
            self._detect_hotstreak()

            # Detect cold streaks (5+ consecutive <2.0x)
            self._detect_coldstreak(multiplier)

        def _detect_hotstreak(self):
            """Detect if we're in/just ended a hot streak"""
            # Check windows of 10-15 rounds
            for window_size in range(15, 12, -1):
                if len(self.recent_multipliers) < window_size:
                    continue

                window = self.recent_multipliers[-window_size:]
                above_2x = sum(1 for m in window if m >= 2.0)
                percentage = above_2x / window_size

                if percentage >= 0.70:  # Weak or strong hot streak
                    streak_type = "strong" if percentage >= 0.80 else "weak"
                    avg = sum(window) / window_size

                    import numpy as np

                    volatility = np.std(window) if len(window) > 2 else 0

                    self.last_hotstreak = {
                        "type": streak_type,
                        "length": window_size,
                        "average": avg,
                        "volatility": volatility,
                        "multipliers": window.copy(),
                        "end_round": self.current_round,
                    }
                    self.last_hotstreak_end_round = self.current_round
                    break

        def _detect_coldstreak(self, multiplier: float):
            """Detect cold streaks"""
            if multiplier < 2.0:
                if not self.cold_streak_active:
                    self.cold_streak_active = True
                    self.cold_streak_start = self.current_round
            else:
                if self.cold_streak_active:
                    streak_length = self.current_round - self.cold_streak_start
                    if streak_length >= 5:
                        pass  # Cold streak ended
                    self.cold_streak_active = False

        def get_game_state(self) -> Dict:
            """Get current game state for prediction analysis"""
            state = {
                "recent_10_multipliers": self.recent_multipliers[-10:]
                if len(self.recent_multipliers) >= 10
                else [],
                "rounds_since_last_hotstreak": 0,
                "last_streak_type": None,
                "last_streak_average": 0,
                "last_streak_volatility": 0,
                "last_10_before_streak": [],
                "first_10_after_streak": [],
                "cold_streak_occurred": False,
                "last_hotstreak_gap": None,
                "session_id": 0,
            }

            if self.last_hotstreak:
                rounds_since = self.current_round - self.last_hotstreak_end_round
                state["rounds_since_last_hotstreak"] = rounds_since
                state["last_streak_type"] = self.last_hotstreak["type"]
                state["last_streak_average"] = self.last_hotstreak["average"]
                state["last_streak_volatility"] = self.last_hotstreak["volatility"]

                # Get 10 rounds before the streak
                streak_start_idx = (
                    len(self.recent_multipliers)
                    - self.last_hotstreak["length"]
                    - rounds_since
                )
                if streak_start_idx >= 10:
                    state["last_10_before_streak"] = self.recent_multipliers[
                        streak_start_idx - 10 : streak_start_idx
                    ]

                # Get first 10 rounds after the streak
                streak_end_idx = len(self.recent_multipliers) - rounds_since
                if rounds_since >= 10:
                    state["first_10_after_streak"] = self.recent_multipliers[
                        streak_end_idx : streak_end_idx + 10
                    ]

            return state

    return GameStateTracker()
