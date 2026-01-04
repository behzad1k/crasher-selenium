#!/usr/bin/env python3
"""
Signal Fact-Checking System
Analyzes prediction accuracy by comparing signals to actual hot streak occurrences
"""

import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np


class FactCheckAnalyzer:
    """Analyzes signal accuracy against actual outcomes"""

    # Top 10 combinations definition
    TOP_COMBINATIONS = [
        {
            "combo_id": 1,
            "methods": [1, 3, 4, 5, 6],
            "name": "The Champion",
            "short_name": "M1+M3+M4+M5+M6",
            "initial_accuracy": 67.7,
        },
        {
            "combo_id": 2,
            "methods": [1, 4, 5, 6],
            "name": "The Efficient (BEST)",
            "short_name": "M1+M4+M5+M6",
            "initial_accuracy": 67.7,
        },
        {
            "combo_id": 3,
            "methods": [1, 2, 4, 5],
            "name": "Precision Striker",
            "short_name": "M1+M2+M4+M5",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 4,
            "methods": [3, 4, 5, 6],
            "name": "Pure Predictor",
            "short_name": "M3+M4+M5+M6",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 5,
            "methods": [2, 3, 4, 6],
            "name": "Composite Specialist",
            "short_name": "M2+M3+M4+M6",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 6,
            "methods": [1, 3, 4, 5],
            "name": "Core Four",
            "short_name": "M1+M3+M4+M5",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 7,
            "methods": [2, 4, 6],
            "name": "Minimalist",
            "short_name": "M2+M4+M6",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 8,
            "methods": [1, 3, 5, 6],
            "name": "Balanced Five",
            "short_name": "M1+M3+M5+M6",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 9,
            "methods": [1, 2, 4, 6],
            "name": "Strategic Four",
            "short_name": "M1+M2+M4+M6",
            "initial_accuracy": 67.4,
        },
        {
            "combo_id": 10,
            "methods": [3, 4, 5],
            "name": "Essential Three",
            "short_name": "M3+M4+M5",
            "initial_accuracy": 67.3,
        },
    ]

    def __init__(self, db_path: str, verbose: bool = True):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.verbose = verbose
        self._init_tables()

    def log(self, message: str):
        if self.verbose:
            print(message)

    def _init_tables(self):
        """Create all necessary tables"""
        cursor = self.conn.cursor()

        # Methods table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS methods (
                method_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                short_title TEXT NOT NULL,
                initial_accuracy REAL NOT NULL,
                actual_accuracy REAL DEFAULT NULL,
                adjusted_accuracy REAL DEFAULT NULL,
                description TEXT NOT NULL,
                total_signals INTEGER DEFAULT 0,
                checked_signals INTEGER DEFAULT 0,
                successful_signals INTEGER DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Signal fact-check table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_fact_check (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                method_id INTEGER NOT NULL,
                predicted_rounds INTEGER NOT NULL,
                actual_rounds INTEGER,
                successful BOOLEAN,
                margin_error INTEGER,
                confidence REAL,
                session_id INTEGER,
                signal_timestamp DATETIME,
                checked_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (signal_id) REFERENCES signals(id),
                FOREIGN KEY (method_id) REFERENCES methods(method_id)
            )
        """)

        # Combinations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS combinations (
                combo_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                method_ids TEXT NOT NULL,
                initial_accuracy REAL NOT NULL,
                actual_accuracy REAL DEFAULT NULL,
                adjusted_accuracy REAL DEFAULT NULL,
                total_occurrences INTEGER DEFAULT 0,
                checked_occurrences INTEGER DEFAULT 0,
                successful_occurrences INTEGER DEFAULT 0,
                avg_confidence REAL DEFAULT NULL,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Combination fact-check table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS combination_fact_check (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                combo_id INTEGER NOT NULL,
                multiplier_id INTEGER NOT NULL,
                predicted_rounds INTEGER NOT NULL,
                actual_rounds INTEGER,
                successful BOOLEAN,
                margin_error INTEGER,
                avg_confidence REAL,
                method_count INTEGER,
                session_id INTEGER,
                timestamp DATETIME,
                checked_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (combo_id) REFERENCES combinations(combo_id),
                FOREIGN KEY (multiplier_id) REFERENCES multipliers(id)
            )
        """)

        self.conn.commit()
        self.log("✓ Tables initialized")

    def populate_methods_table(self):
        """Populate methods table with initial data"""
        cursor = self.conn.cursor()

        methods = [
            (
                1,
                "Progressive Window Probability",
                "M1",
                8.1,
                "Tracks time since last hot streak, uses probability windows (0-5r: 36%, 6-15r: 23%, etc.)",
            ),
            (
                2,
                "Composite Multi-Signal Predictor",
                "M2",
                7.3,
                "Combines 5 signals: streak type, quality, pre-pattern, momentum, cold streak status",
            ),
            (
                3,
                "Streak Average Multiplier Predictor",
                "M3",
                6.7,
                "Analyzes quality of last hot streak by average multiplier (extreme >10x, high 6-10x, etc.)",
            ),
            (
                4,
                "Cold Streak Binary Classifier",
                "M4",
                6.4,
                "Identifies cold streak patterns, implements 'Rule of 17' (87% accuracy when triggered)",
            ),
            (
                5,
                "Post-Streak Momentum Tracker",
                "M5",
                5.1,
                "Analyzes first 10 rounds after hot streak for momentum (high: 5+ rounds ≥2x)",
            ),
            (
                6,
                "Streak Type Momentum",
                "M6",
                5.0,
                "Differentiates strong (80%+ ≥2x) vs weak (65-79% ≥2x) streaks for timing",
            ),
            (
                7,
                "Volatility-Based Prediction",
                "M7",
                4.8,
                "Calculates streak volatility (std dev) to predict timing (high vol = 11r, low = 12r)",
            ),
            (
                8,
                "Session Pattern Recognition",
                "M8",
                3.9,
                "Identifies high-activity sessions with tighter hot streak intervals",
            ),
            (
                9,
                "Pre-Streak Pattern Detection",
                "M9",
                3.8,
                "Looks for signature pattern in last 10 rounds (4+ ≥2x, avg 3.5x, spike ≥7x)",
            ),
            (
                10,
                "Sequential Chain Analysis",
                "M10",
                3.3,
                "Detects chains of hot streaks with ≤5 round gaps (33.5% continuation probability)",
            ),
        ]

        # Clear existing and insert
        cursor.execute("DELETE FROM methods")
        cursor.executemany(
            """
            INSERT INTO methods (method_id, title, short_title, initial_accuracy, description)
            VALUES (?, ?, ?, ?, ?)
        """,
            methods,
        )

        self.conn.commit()
        self.log(f"✓ Populated {len(methods)} methods")

    def populate_combinations_table(self):
        """Populate combinations table"""
        cursor = self.conn.cursor()

        cursor.execute("DELETE FROM combinations")

        for combo in self.TOP_COMBINATIONS:
            method_ids_str = ",".join(map(str, combo["methods"]))
            cursor.execute(
                """
                INSERT INTO combinations (combo_id, name, short_name, method_ids, initial_accuracy)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    combo["combo_id"],
                    combo["name"],
                    combo["short_name"],
                    method_ids_str,
                    combo["initial_accuracy"],
                ),
            )

        self.conn.commit()
        self.log(f"✓ Populated {len(self.TOP_COMBINATIONS)} combinations")

    def detect_next_hotstreak(
        self, multipliers: List[float], start_index: int
    ) -> Optional[int]:
        """
        Detect when the next hot streak occurs after start_index
        Returns: rounds until next hot streak, or None if not found
        """
        # Look ahead for hot streaks
        for i in range(start_index, len(multipliers)):
            # Try different window sizes (15 down to 10)
            for window_size in range(15, 12, -1):
                if i + window_size > len(multipliers):
                    continue

                window = multipliers[i : i + window_size]
                above_2x = sum(1 for m in window if m >= 2.0)
                percentage = above_2x / window_size

                if percentage >= 0.70:  # Hot streak detected
                    return i - start_index

        return None

    def fact_check_signals(self, min_lookahead_rounds: int = 20):
        """
        Fact-check all signals by comparing predictions to actual outcomes

        Args:
            min_lookahead_rounds: Minimum rounds needed ahead to check signal
        """
        cursor = self.conn.cursor()

        self.log("\n" + "=" * 80)
        self.log("FACT-CHECKING SIGNALS")
        self.log("=" * 80)

        # Clear existing fact-checks
        cursor.execute("DELETE FROM signal_fact_check")
        self.conn.commit()

        # Get all sessions
        cursor.execute("""
            SELECT DISTINCT m.session_id
            FROM signals s
            JOIN multipliers m ON s.multiplier_id = m.id
            WHERE m.session_id IS NOT NULL
            ORDER BY m.session_id
        """)

        sessions = [row[0] for row in cursor.fetchall()]
        self.log(f"\nProcessing {len(sessions)} sessions...")

        total_checked = 0
        total_skipped = 0

        for session_idx, session_id in enumerate(sessions, 1):
            self.log(f"\n[{session_idx}/{len(sessions)}] Session #{session_id}...")

            # Get all multipliers for this session
            cursor.execute(
                """
                SELECT id, multiplier
                FROM multipliers
                WHERE session_id = ?
                ORDER BY id
            """,
                (session_id,),
            )

            rows = cursor.fetchall()
            multiplier_id_to_index = {row[0]: idx for idx, row in enumerate(rows)}
            multipliers = [row[1] for row in rows]

            self.log(f"  Total rounds: {len(multipliers)}")

            # Get all signals for this session
            cursor.execute(
                """
                SELECT s.id, s.multiplier_id, s.method_id, s.prediction_rounds,
                       s.confidence, s.timestamp
                FROM signals s
                JOIN multipliers m ON s.multiplier_id = m.id
                WHERE m.session_id = ?
                ORDER BY m.id
            """,
                (session_id,),
            )

            signals = cursor.fetchall()
            self.log(f"  Total signals: {len(signals)}")

            session_checked = 0
            session_skipped = 0

            for (
                signal_id,
                mult_id,
                method_id,
                predicted_rounds,
                confidence,
                timestamp,
            ) in signals:
                # Get index of this multiplier
                if mult_id not in multiplier_id_to_index:
                    session_skipped += 1
                    continue

                signal_index = multiplier_id_to_index[mult_id]

                # Calculate required lookahead (prediction + margin)
                required_lookahead = predicted_rounds + 10
                available_rounds = len(multipliers) - signal_index - 1

                # Skip if insufficient data
                if available_rounds < required_lookahead:
                    session_skipped += 1
                    continue

                # Detect next hot streak
                actual_rounds = self.detect_next_hotstreak(
                    multipliers, signal_index + 1
                )

                if actual_rounds is None:
                    # No hot streak found in available data
                    session_skipped += 1
                    continue

                # Check success (within ±10 rounds)
                margin_error = abs(actual_rounds - predicted_rounds)
                successful = margin_error <= 10

                # Record fact-check
                cursor.execute(
                    """
                    INSERT INTO signal_fact_check
                    (signal_id, method_id, predicted_rounds, actual_rounds,
                     successful, margin_error, confidence, session_id, signal_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        signal_id,
                        method_id,
                        predicted_rounds,
                        actual_rounds,
                        successful,
                        margin_error,
                        confidence,
                        session_id,
                        timestamp,
                    ),
                )

                session_checked += 1

            self.log(f"  ✓ Checked: {session_checked}, Skipped: {session_skipped}")
            total_checked += session_checked
            total_skipped += session_skipped

        self.conn.commit()

        self.log(f"\n{'=' * 80}")
        self.log(f"Total signals checked: {total_checked:,}")
        self.log(f"Total signals skipped: {total_skipped:,}")
        self.log(f"{'=' * 80}")

    def update_method_accuracies(self):
        """Update method accuracies based on fact-checks"""
        cursor = self.conn.cursor()

        self.log("\nUpdating method accuracies...")

        cursor.execute("""
            SELECT
                method_id,
                COUNT(*) as total,
                SUM(CASE WHEN successful THEN 1 ELSE 0 END) as successful
            FROM signal_fact_check
            GROUP BY method_id
        """)

        for method_id, total, successful in cursor.fetchall():
            actual_accuracy = (successful / total * 100) if total > 0 else None

            # Get initial accuracy
            cursor.execute(
                "SELECT initial_accuracy FROM methods WHERE method_id = ?", (method_id,)
            )
            initial_accuracy = cursor.fetchone()[0]

            # Calculate adjusted accuracy (average of initial and actual)
            if actual_accuracy is not None:
                adjusted_accuracy = (initial_accuracy + actual_accuracy) / 2
            else:
                adjusted_accuracy = initial_accuracy

            # Update method
            cursor.execute(
                """
                UPDATE methods
                SET actual_accuracy = ?,
                    adjusted_accuracy = ?,
                    total_signals = (SELECT COUNT(*) FROM signals WHERE method_id = ?),
                    checked_signals = ?,
                    successful_signals = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE method_id = ?
            """,
                (
                    actual_accuracy,
                    adjusted_accuracy,
                    method_id,
                    total,
                    successful,
                    method_id,
                ),
            )

            cursor.execute(
                "SELECT short_title FROM methods WHERE method_id = ?", (method_id,)
            )
            short_title = cursor.fetchone()[0]

            self.log(
                f"  {short_title}: {actual_accuracy:.1f}% actual (checked {total:,} signals)"
            )

        self.conn.commit()
        self.log("✓ Method accuracies updated")

    def fact_check_combinations(self, min_lookahead_rounds: int = 20):
        """Fact-check combination predictions"""
        cursor = self.conn.cursor()

        self.log("\n" + "=" * 80)
        self.log("FACT-CHECKING COMBINATIONS")
        self.log("=" * 80)

        # Clear existing
        cursor.execute("DELETE FROM combination_fact_check")
        self.conn.commit()

        # Get all sessions
        cursor.execute("""
            SELECT DISTINCT m.session_id
            FROM signals s
            JOIN multipliers m ON s.multiplier_id = m.id
            WHERE m.session_id IS NOT NULL
            ORDER BY m.session_id
        """)

        sessions = [row[0] for row in cursor.fetchall()]

        total_checked = 0
        combo_counts = {combo["combo_id"]: 0 for combo in self.TOP_COMBINATIONS}

        for session_idx, session_id in enumerate(sessions, 1):
            self.log(f"\n[{session_idx}/{len(sessions)}] Session #{session_id}...")

            # Get all multipliers
            cursor.execute(
                """
                SELECT id, multiplier
                FROM multipliers
                WHERE session_id = ?
                ORDER BY id
            """,
                (session_id,),
            )

            rows = cursor.fetchall()
            multiplier_id_to_index = {row[0]: idx for idx, row in enumerate(rows)}
            multipliers = [row[1] for row in rows]

            # Find all multipliers with signals
            cursor.execute(
                """
                SELECT
                    s.multiplier_id,
                    GROUP_CONCAT(s.method_id ORDER BY s.method_id) as method_combo,
                    COUNT(*) as method_count,
                    MIN(m.timestamp) as timestamp
                FROM signals s
                JOIN multipliers m ON s.multiplier_id = m.id
                WHERE m.session_id = ?
                GROUP BY s.multiplier_id
            """,
                (session_id,),
            )

            session_checked = 0

            for mult_id, method_combo, method_count, timestamp in cursor.fetchall():
                # Get all methods that triggered
                method_ids = set(int(m) for m in method_combo.split(","))

                # Check which Top 10 combinations are present
                # A combination is "present" if ALL its methods triggered
                matched_combos = []
                for combo in self.TOP_COMBINATIONS:
                    combo_set = set(combo["methods"])
                    if combo_set.issubset(method_ids):  # All combo methods are present
                        matched_combos.append(combo)

                if not matched_combos:
                    continue

                # Get index
                if mult_id not in multiplier_id_to_index:
                    continue

                signal_index = multiplier_id_to_index[mult_id]

                # Get predictions from the methods in each combo
                for combo in matched_combos:
                    # Get predictions only from methods in THIS combo
                    cursor.execute(
                        """
                        SELECT
                            AVG(prediction_rounds) as avg_prediction,
                            AVG(confidence) as avg_confidence
                        FROM signals
                        WHERE multiplier_id = ?
                        AND method_id IN ({})
                    """.format(",".join("?" * len(combo["methods"]))),
                        [mult_id] + combo["methods"],
                    )

                    result = cursor.fetchone()
                    if not result or result[0] is None:
                        continue

                    avg_pred, avg_conf = result
                    predicted_rounds = int(round(avg_pred))

                    # Check lookahead
                    required_lookahead = predicted_rounds + 10
                    available_rounds = len(multipliers) - signal_index - 1

                    if available_rounds < required_lookahead:
                        continue

                    # Detect next hot streak
                    actual_rounds = self.detect_next_hotstreak(
                        multipliers, signal_index + 1
                    )

                    if actual_rounds is None:
                        continue

                    # Check success
                    margin_error = abs(actual_rounds - predicted_rounds)
                    successful = margin_error <= 10

                    # Record
                    cursor.execute(
                        """
                        INSERT INTO combination_fact_check
                        (combo_id, multiplier_id, predicted_rounds, actual_rounds,
                         successful, margin_error, avg_confidence, method_count,
                         session_id, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            combo["combo_id"],
                            mult_id,
                            predicted_rounds,
                            actual_rounds,
                            successful,
                            margin_error,
                            avg_conf,
                            len(combo["methods"]),
                            session_id,
                            timestamp,
                        ),
                    )

                    total_checked += 1
                    session_checked += 1
                    combo_counts[combo["combo_id"]] += 1

            self.log(f"  ✓ Checked {session_checked} combination occurrences")

        self.conn.commit()

        self.log(f"\n{'=' * 80}")
        self.log(f"Total combination occurrences checked: {total_checked:,}")
        self.log(f"\nBreakdown by combination:")
        for combo in self.TOP_COMBINATIONS:
            count = combo_counts[combo["combo_id"]]
            self.log(f"  #{combo['combo_id']} {combo['short_name']}: {count:,}")
        self.log(f"{'=' * 80}")

    def update_combination_accuracies(self):
        """Update combination accuracies based on fact-checks"""
        cursor = self.conn.cursor()

        self.log("\nUpdating combination accuracies...")

        cursor.execute("""
            SELECT
                combo_id,
                COUNT(*) as total,
                SUM(CASE WHEN successful THEN 1 ELSE 0 END) as successful,
                AVG(avg_confidence) as avg_conf
            FROM combination_fact_check
            GROUP BY combo_id
        """)

        for combo_id, total, successful, avg_conf in cursor.fetchall():
            actual_accuracy = (successful / total * 100) if total > 0 else None

            # Get initial accuracy
            cursor.execute(
                "SELECT initial_accuracy FROM combinations WHERE combo_id = ?",
                (combo_id,),
            )
            initial_accuracy = cursor.fetchone()[0]

            # Adjusted accuracy
            if actual_accuracy is not None:
                adjusted_accuracy = (initial_accuracy + actual_accuracy) / 2
            else:
                adjusted_accuracy = initial_accuracy

            # Update - simplified, just use total from fact-checks
            cursor.execute(
                """
                UPDATE combinations
                SET actual_accuracy = ?,
                    adjusted_accuracy = ?,
                    total_occurrences = ?,
                    checked_occurrences = ?,
                    successful_occurrences = ?,
                    avg_confidence = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE combo_id = ?
            """,
                (
                    actual_accuracy,
                    adjusted_accuracy,
                    total,
                    total,
                    successful,
                    avg_conf,
                    combo_id,
                ),
            )

            cursor.execute(
                "SELECT short_name FROM combinations WHERE combo_id = ?", (combo_id,)
            )
            short_name = cursor.fetchone()[0]

            self.log(
                f"  {short_name}: {actual_accuracy:.1f}% actual (checked {total:,})"
            )

        self.conn.commit()
        self.log("✓ Combination accuracies updated")

    def generate_report(self):
        """Generate comprehensive accuracy report"""
        cursor = self.conn.cursor()

        print("\n" + "=" * 80)
        print("FACT-CHECK RESULTS REPORT")
        print("=" * 80)

        # Method performance
        print("\n" + "=" * 80)
        print("METHOD PERFORMANCE")
        print("=" * 80)

        cursor.execute("""
            SELECT
                short_title,
                title,
                initial_accuracy,
                actual_accuracy,
                adjusted_accuracy,
                checked_signals,
                successful_signals
            FROM methods
            ORDER BY method_id
        """)

        print(
            f"\n{'ID':<4} {'Initial':<8} {'Actual':<8} {'Adjusted':<9} {'Checked':<10} {'Success':<10} {'Title'}"
        )
        print("-" * 100)

        for row in cursor.fetchall():
            short, title, initial, actual, adjusted, checked, successful = row
            actual_str = f"{actual:.1f}%" if actual is not None else "N/A"
            adjusted_str = f"{adjusted:.1f}%" if adjusted is not None else "N/A"
            success_str = f"{successful:,}/{checked:,}" if checked > 0 else "N/A"

            print(
                f"{short:<4} {initial:>6.1f}% {actual_str:>7} {adjusted_str:>8} {checked:>9,} {success_str:>9} {title[:40]}"
            )

        # Combination performance
        print("\n" + "=" * 80)
        print("COMBINATION PERFORMANCE")
        print("=" * 80)

        cursor.execute("""
            SELECT
                combo_id,
                short_name,
                initial_accuracy,
                actual_accuracy,
                adjusted_accuracy,
                checked_occurrences,
                successful_occurrences
            FROM combinations
            ORDER BY combo_id
        """)

        print(
            f"\n{'#':<3} {'Initial':<8} {'Actual':<8} {'Adjusted':<9} {'Checked':<10} {'Success':<10} {'Name'}"
        )
        print("-" * 100)

        for row in cursor.fetchall():
            combo_id, name, initial, actual, adjusted, checked, successful = row
            actual_str = f"{actual:.1f}%" if actual is not None else "N/A"
            adjusted_str = f"{adjusted:.1f}%" if adjusted is not None else "N/A"
            success_str = f"{successful:,}/{checked:,}" if checked > 0 else "N/A"

            print(
                f"{combo_id:<3} {initial:>6.1f}% {actual_str:>7} {adjusted_str:>8} {checked:>9,} {success_str:>9} {name}"
            )

        # Summary statistics
        print("\n" + "=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)

        # Overall method accuracy
        cursor.execute("""
            SELECT
                AVG(actual_accuracy) as avg_actual,
                AVG(adjusted_accuracy) as avg_adjusted,
                SUM(checked_signals) as total_checked,
                SUM(successful_signals) as total_successful
            FROM methods
            WHERE actual_accuracy IS NOT NULL
        """)

        avg_actual, avg_adjusted, total_checked, total_successful = cursor.fetchone()
        overall_rate = (
            (total_successful / total_checked * 100)
            if total_checked and total_checked > 0
            else 0
        )

        print(f"\nMethods:")
        if avg_actual is not None:
            print(f"  Average Actual Accuracy: {avg_actual:.1f}%")
        else:
            print(f"  Average Actual Accuracy: N/A")
        if avg_adjusted is not None:
            print(f"  Average Adjusted Accuracy: {avg_adjusted:.1f}%")
        else:
            print(f"  Average Adjusted Accuracy: N/A")
        print(
            f"  Overall Success Rate: {overall_rate:.1f}% ({total_successful or 0:,}/{total_checked or 0:,})"
        )

        # Overall combination accuracy
        cursor.execute("""
            SELECT
                AVG(actual_accuracy) as avg_actual,
                AVG(adjusted_accuracy) as avg_adjusted,
                SUM(checked_occurrences) as total_checked,
                SUM(successful_occurrences) as total_successful
            FROM combinations
            WHERE actual_accuracy IS NOT NULL
        """)

        avg_actual, avg_adjusted, total_checked, total_successful = cursor.fetchone()
        overall_rate = (
            (total_successful / total_checked * 100)
            if total_checked and total_checked > 0
            else 0
        )

        print(f"\nCombinations:")
        if avg_actual is not None:
            print(f"  Average Actual Accuracy: {avg_actual:.1f}%")
        else:
            print(f"  Average Actual Accuracy: N/A")
        if avg_adjusted is not None:
            print(f"  Average Adjusted Accuracy: {avg_adjusted:.1f}%")
        else:
            print(f"  Average Adjusted Accuracy: N/A")
        print(
            f"  Overall Success Rate: {overall_rate:.1f}% ({total_successful or 0:,}/{total_checked or 0:,})"
        )

        print("\n" + "=" * 80)

    def close(self):
        self.conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fact-check signal predictions against actual outcomes"
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--min-lookahead",
        type=int,
        default=20,
        help="Minimum rounds needed ahead to check signal (default: 20)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Quiet mode (less output)"
    )

    args = parser.parse_args()

    try:
        analyzer = FactCheckAnalyzer(args.db, verbose=not args.quiet)

        # Initialize tables
        analyzer.populate_methods_table()
        analyzer.populate_combinations_table()

        # Fact-check signals
        analyzer.fact_check_signals(args.min_lookahead)
        analyzer.update_method_accuracies()

        # Fact-check combinations
        analyzer.fact_check_combinations(args.min_lookahead)
        analyzer.update_combination_accuracies()

        # Generate report
        analyzer.generate_report()

        analyzer.close()

        print("\n✅ Fact-checking complete!")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
