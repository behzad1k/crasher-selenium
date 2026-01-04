#!/usr/bin/env python3
"""
Backfill Signals - Analyze Historical Multipliers
Applies all 10 prediction methods to existing multiplier data and fills signals table
"""

import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

# Import the prediction module
from prediction_module import (
    Method1_ProgressiveWindow,
    Method2_CompositeSignal,
    Method3_StreakAverage,
    Method4_ColdStreak,
    Method5_Momentum,
    Method6_StreakType,
    Method7_Volatility,
    Method8_SessionPattern,
    Method9_PrePattern,
    Method10_Chain,
    PredictionAnalyzer,
)


class GameStateBuilder:
    """Builds game state from historical multiplier data"""

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset for new session"""
        self.all_multipliers = []
        self.current_index = 0
        self.last_hotstreak = None
        self.last_hotstreak_index = -1
        self.cold_streak_detected = False
        self.last_hotstreak_gap = None

    def add_multipliers(self, multipliers: List[float]):
        """Add all multipliers for a session"""
        self.all_multipliers = multipliers
        self.current_index = 0

    def advance_to(self, index: int):
        """Advance to specific index and update state"""
        self.current_index = index
        self._update_hotstreak_detection()
        self._update_cold_streak()

    def _update_hotstreak_detection(self):
        """Detect hot streaks up to current index"""
        # Check for hot streaks in windows of 10-15 rounds
        for i in range(max(0, self.current_index - 50), self.current_index):
            for window_size in range(15, 12, -1):
                if i + window_size > self.current_index:
                    continue

                window = self.all_multipliers[i : i + window_size]
                above_2x = sum(1 for m in window if m >= 2.0)
                percentage = above_2x / window_size

                if percentage >= 0.70:  # Hot streak detected
                    streak_type = "strong" if percentage >= 0.80 else "weak"
                    avg = sum(window) / window_size
                    volatility = np.std(window) if len(window) > 2 else 0

                    # Calculate gap from last hotstreak
                    gap = None
                    if self.last_hotstreak_index >= 0:
                        gap = i - (
                            self.last_hotstreak_index + self.last_hotstreak["length"]
                        )

                    self.last_hotstreak = {
                        "type": streak_type,
                        "length": window_size,
                        "average": avg,
                        "volatility": volatility,
                        "multipliers": window.copy(),
                        "end_index": i + window_size - 1,
                    }
                    self.last_hotstreak_index = i
                    self.last_hotstreak_gap = gap
                    break

    def _update_cold_streak(self):
        """Check if cold streak occurred since last hot streak"""
        if self.last_hotstreak_index < 0:
            return

        streak_end = self.last_hotstreak_index + self.last_hotstreak["length"]

        # Look for 5+ consecutive <2.0x after hot streak
        consecutive_cold = 0
        for i in range(streak_end, self.current_index):
            if self.all_multipliers[i] < 2.0:
                consecutive_cold += 1
                if consecutive_cold >= 5:
                    self.cold_streak_detected = True
                    return
            else:
                consecutive_cold = 0

        self.cold_streak_detected = False

    def get_state_at_index(self, index: int, session_id: int) -> Dict:
        """Get game state at specific index"""
        self.advance_to(index)

        state = {
            "recent_10_multipliers": [],
            "rounds_since_last_hotstreak": 0,
            "last_streak_type": None,
            "last_streak_average": 0,
            "last_streak_volatility": 0,
            "last_10_before_streak": [],
            "first_10_after_streak": [],
            "cold_streak_occurred": False,
            "last_hotstreak_gap": None,
            "session_id": session_id,
        }

        # Recent 10 multipliers
        start_idx = max(0, index - 10)
        state["recent_10_multipliers"] = self.all_multipliers[start_idx:index]

        if self.last_hotstreak:
            streak_end = self.last_hotstreak_index + self.last_hotstreak["length"]
            rounds_since = index - streak_end

            state["rounds_since_last_hotstreak"] = rounds_since
            state["last_streak_type"] = self.last_hotstreak["type"]
            state["last_streak_average"] = self.last_hotstreak["average"]
            state["last_streak_volatility"] = self.last_hotstreak["volatility"]

            # 10 rounds before the streak
            before_start = max(0, self.last_hotstreak_index - 10)
            state["last_10_before_streak"] = self.all_multipliers[
                before_start : self.last_hotstreak_index
            ]

            # First 10 rounds after the streak
            after_end = min(len(self.all_multipliers), streak_end + 10)
            state["first_10_after_streak"] = self.all_multipliers[streak_end:after_end]

            state["cold_streak_occurred"] = self.cold_streak_detected
            state["last_hotstreak_gap"] = self.last_hotstreak_gap

        return state


def backfill_signals(
    db_path: str = "./crasher_data.db",
    session_ids: Optional[List[int]] = None,
    verbose: bool = True,
):
    """
    Backfill signals table with historical analysis

    Args:
        db_path: Path to database
        session_ids: List of session IDs to analyze (None = all sessions)
        verbose: Print progress
    """

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Initialize prediction analyzer
    analyzer = PredictionAnalyzer(conn, print if verbose else lambda x: None)

    # Get sessions to process
    if session_ids:
        placeholders = ",".join("?" * len(session_ids))
        cursor.execute(
            f"""
            SELECT DISTINCT session_id
            FROM multipliers
            WHERE session_id IN ({placeholders})
            ORDER BY session_id
        """,
            session_ids,
        )
    else:
        cursor.execute("""
            SELECT DISTINCT session_id
            FROM multipliers
            WHERE session_id IS NOT NULL
            ORDER BY session_id
        """)

    sessions = [row[0] for row in cursor.fetchall()]

    if not sessions:
        print("No sessions found to process!")
        return

    print(f"Processing {len(sessions)} session(s)...")
    print("=" * 80)

    total_signals = 0

    for session_idx, session_id in enumerate(sessions, 1):
        print(f"\n[{session_idx}/{len(sessions)}] Processing Session #{session_id}...")

        # Get all multipliers for this session
        cursor.execute(
            """
            SELECT id, multiplier, timestamp
            FROM multipliers
            WHERE session_id = ?
            ORDER BY id
        """,
            (session_id,),
        )

        rows = cursor.fetchall()
        if not rows:
            print(f"  No multipliers found for session {session_id}")
            continue

        multiplier_ids = [row[0] for row in rows]
        multipliers = [row[1] for row in rows]
        timestamps = [row[2] for row in rows]

        print(f"  Found {len(multipliers)} multipliers")
        print(f"  Range: {min(multipliers):.2f}x to {max(multipliers):.2f}x")

        # Build game state for this session
        state_builder = GameStateBuilder()
        state_builder.add_multipliers(multipliers)

        session_signals = 0

        # Analyze each round
        for i in range(len(multipliers)):
            multiplier_id = multiplier_ids[i]

            # Get game state at this point
            game_state = state_builder.get_state_at_index(i, session_id)

            # Run analysis
            triggered_methods, matching_combos = analyzer.analyze_round(
                game_state, multiplier_id
            )

            session_signals += len(triggered_methods)

            # Progress indicator
            if verbose and (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(multipliers)} rounds analyzed...")

        print(f"  ✓ Session #{session_id}: {session_signals} signals generated")
        total_signals += session_signals

    print("\n" + "=" * 80)
    print(f"BACKFILL COMPLETE!")
    print(f"Total signals generated: {total_signals}")
    print("=" * 80)

    # Show summary statistics
    cursor.execute("""
        SELECT
            method_name,
            COUNT(*) as count,
            AVG(confidence) as avg_confidence,
            AVG(prediction_rounds) as avg_prediction
        FROM signals
        GROUP BY method_name
        ORDER BY count DESC
    """)

    print("\nSignal Summary by Method:")
    print("-" * 80)
    print(f"{'Method':<30} {'Count':<10} {'Avg Conf':<12} {'Avg Predict'}")
    print("-" * 80)

    for row in cursor.fetchall():
        method_name, count, avg_conf, avg_pred = row
        print(
            f"{method_name:<30} {count:<10} {avg_conf * 100:>6.1f}% {avg_pred:>12.1f}r"
        )

    print("-" * 80)

    # Show top combinations that appeared
    print("\nAnalyzing combination frequency...")
    cursor.execute("""
        SELECT multiplier_id, GROUP_CONCAT(method_id) as methods
        FROM signals
        GROUP BY multiplier_id
        HAVING COUNT(*) >= 3
    """)

    combo_counts = {}
    for row in cursor.fetchall():
        methods = tuple(sorted([int(m) for m in row[1].split(",")]))
        combo_counts[methods] = combo_counts.get(methods, 0) + 1

    if combo_counts:
        print("\nMost Frequent Method Combinations (3+ methods):")
        print("-" * 80)

        sorted_combos = sorted(combo_counts.items(), key=lambda x: x[1], reverse=True)
        for methods, count in sorted_combos[:10]:
            methods_str = "+".join([f"M{m}" for m in methods])
            print(f"  {methods_str:<30} {count:>6} occurrences")

    conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill signals table with historical prediction analysis"
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        nargs="+",
        help="Specific session IDs to process (default: all sessions)",
    )
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing signals before backfilling"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Quiet mode (less output)"
    )

    args = parser.parse_args()

    # Connect and optionally clear
    if args.clear:
        print("Clearing existing signals...")
        conn = sqlite3.connect(args.db)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM signals")
        conn.commit()
        deleted = cursor.rowcount
        conn.close()
        print(f"✓ Deleted {deleted} existing signals\n")

    # Run backfill
    try:
        backfill_signals(
            db_path=args.db, session_ids=args.sessions, verbose=not args.quiet
        )
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
