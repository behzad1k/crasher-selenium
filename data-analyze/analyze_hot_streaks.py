#!/usr/bin/env python3
"""
Hot Streak Analysis - Multiple Definitions
Analyzes "hot streaks" using three different definitions:
1. Consecutive rounds over 2x (strict)
2. Consecutive rounds over 2x with 1-3 under-2x allowance (lenient)
3. Time windows with high average multiplier (normalized at 100x)
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np


class HotStreakAnalyzer:
    """Analyze hot streaks with multiple definitions"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path)
        self.threshold = 2.0  # Base threshold for "hot"
        self.normalize_cap = 100.0  # Cap for extreme multipliers

    def load_data_by_session(self) -> Dict[int, List[Tuple]]:
        """
        Load all multipliers grouped by session
        Returns: {session_id: [(timestamp, multiplier, bettor_count, round_id), ...]}
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                session_id,
                timestamp,
                multiplier,
                bettor_count,
                id
            FROM multipliers
            WHERE session_id IS NOT NULL
            ORDER BY session_id, timestamp
        """)

        rows = cursor.fetchall()

        if not rows:
            print("❌ No data found with session assignments!")
            return {}

        sessions = {}
        for session_id, timestamp_str, multiplier, bettor_count, round_id in rows:
            if session_id not in sessions:
                sessions[session_id] = []

            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            sessions[session_id].append((timestamp, multiplier, bettor_count, round_id))

        return sessions

    def find_strict_hot_streaks(self, sessions: Dict[int, List[Tuple]]) -> List[Dict]:
        """
        Definition 1: Consecutive rounds ALL over threshold (strict)
        Returns: List of hot streak dictionaries
        """
        all_streaks = []

        for session_id, rounds in sessions.items():
            current_streak = []

            for timestamp, multiplier, bettor_count, round_id in rounds:
                if multiplier >= self.threshold:
                    # Over threshold - add to current streak
                    current_streak.append(
                        {
                            "timestamp": timestamp,
                            "multiplier": multiplier,
                            "bettor_count": bettor_count,
                            "round_id": round_id,
                        }
                    )
                else:
                    # Under threshold - save current streak if exists
                    if len(current_streak) >= 8:  # Minimum 2 rounds for a streak
                        all_streaks.append(
                            {
                                "session_id": session_id,
                                "length": len(current_streak),
                                "start_time": current_streak[0]["timestamp"],
                                "end_time": current_streak[-1]["timestamp"],
                                "start_round_id": current_streak[0]["round_id"],
                                "end_round_id": current_streak[-1]["round_id"],
                                "multipliers": [
                                    r["multiplier"] for r in current_streak
                                ],
                                "bettor_counts": [
                                    r["bettor_count"]
                                    for r in current_streak
                                    if r["bettor_count"] is not None
                                ],
                                "avg_multiplier": sum(
                                    r["multiplier"] for r in current_streak
                                )
                                / len(current_streak),
                                "max_multiplier": max(
                                    r["multiplier"] for r in current_streak
                                ),
                                "min_multiplier": min(
                                    r["multiplier"] for r in current_streak
                                ),
                                "type": "strict",
                            }
                        )
                    current_streak = []

            # Don't forget last streak
            if len(current_streak) >= 8:
                all_streaks.append(
                    {
                        "session_id": session_id,
                        "length": len(current_streak),
                        "start_time": current_streak[0]["timestamp"],
                        "end_time": current_streak[-1]["timestamp"],
                        "start_round_id": current_streak[0]["round_id"],
                        "end_round_id": current_streak[-1]["round_id"],
                        "multipliers": [r["multiplier"] for r in current_streak],
                        "bettor_counts": [
                            r["bettor_count"]
                            for r in current_streak
                            if r["bettor_count"] is not None
                        ],
                        "avg_multiplier": sum(r["multiplier"] for r in current_streak)
                        / len(current_streak),
                        "max_multiplier": max(r["multiplier"] for r in current_streak),
                        "min_multiplier": min(r["multiplier"] for r in current_streak),
                        "type": "strict",
                        "incomplete": True,
                    }
                )

        return all_streaks

    def find_lenient_hot_streaks(
        self, sessions: Dict[int, List[Tuple]], max_dips: int = 3
    ) -> List[Dict]:
        """
        Definition 2: Consecutive rounds over threshold with allowance for 1-3 dips below
        Returns: List of hot streak dictionaries
        """
        all_streaks = []

        for session_id, rounds in sessions.items():
            current_streak = []
            consecutive_dips = 0

            for timestamp, multiplier, bettor_count, round_id in rounds:
                if multiplier >= self.threshold:
                    # Over threshold
                    current_streak.append(
                        {
                            "timestamp": timestamp,
                            "multiplier": multiplier,
                            "bettor_count": bettor_count,
                            "round_id": round_id,
                            "is_dip": False,
                        }
                    )
                    consecutive_dips = 0  # Reset dip counter

                elif len(current_streak) > 0 and consecutive_dips < max_dips:
                    # Under threshold but within allowance
                    current_streak.append(
                        {
                            "timestamp": timestamp,
                            "multiplier": multiplier,
                            "bettor_count": bettor_count,
                            "round_id": round_id,
                            "is_dip": True,
                        }
                    )
                    consecutive_dips += 1

                else:
                    # Too many dips or no active streak - save current streak
                    if len(current_streak) >= 8:
                        over_threshold_count = sum(
                            1 for r in current_streak if not r["is_dip"]
                        )
                        dip_count = sum(1 for r in current_streak if r["is_dip"])

                        all_streaks.append(
                            {
                                "session_id": session_id,
                                "length": len(current_streak),
                                "over_threshold_count": over_threshold_count,
                                "dip_count": dip_count,
                                "start_time": current_streak[0]["timestamp"],
                                "end_time": current_streak[-1]["timestamp"],
                                "start_round_id": current_streak[0]["round_id"],
                                "end_round_id": current_streak[-1]["round_id"],
                                "multipliers": [
                                    r["multiplier"] for r in current_streak
                                ],
                                "is_dip": [r["is_dip"] for r in current_streak],
                                "bettor_counts": [
                                    r["bettor_count"]
                                    for r in current_streak
                                    if r["bettor_count"] is not None
                                ],
                                "avg_multiplier": sum(
                                    r["multiplier"] for r in current_streak
                                )
                                / len(current_streak),
                                "max_multiplier": max(
                                    r["multiplier"] for r in current_streak
                                ),
                                "min_multiplier": min(
                                    r["multiplier"] for r in current_streak
                                ),
                                "type": "lenient",
                            }
                        )
                    current_streak = []
                    consecutive_dips = 0

            # Don't forget last streak
            if len(current_streak) >= 8:
                over_threshold_count = sum(1 for r in current_streak if not r["is_dip"])
                dip_count = sum(1 for r in current_streak if r["is_dip"])

                all_streaks.append(
                    {
                        "session_id": session_id,
                        "length": len(current_streak),
                        "over_threshold_count": over_threshold_count,
                        "dip_count": dip_count,
                        "start_time": current_streak[0]["timestamp"],
                        "end_time": current_streak[-1]["timestamp"],
                        "start_round_id": current_streak[0]["round_id"],
                        "end_round_id": current_streak[-1]["round_id"],
                        "multipliers": [r["multiplier"] for r in current_streak],
                        "is_dip": [r["is_dip"] for r in current_streak],
                        "bettor_counts": [
                            r["bettor_count"]
                            for r in current_streak
                            if r["bettor_count"] is not None
                        ],
                        "avg_multiplier": sum(r["multiplier"] for r in current_streak)
                        / len(current_streak),
                        "max_multiplier": max(r["multiplier"] for r in current_streak),
                        "min_multiplier": min(r["multiplier"] for r in current_streak),
                        "type": "lenient",
                        "incomplete": True,
                    }
                )

        return all_streaks

    def find_window_hot_streaks(
        self,
        sessions: Dict[int, List[Tuple]],
        window_size: int = 10,
        avg_threshold: float = 3.0,
    ) -> List[Dict]:
        """
        Definition 3: Sliding time windows with high average (normalized at 100x)
        Returns: List of hot window dictionaries
        """
        all_windows = []

        for session_id, rounds in sessions.items():
            if len(rounds) < window_size:
                continue

            # Sliding window
            for i in range(len(rounds) - window_size + 1):
                window = rounds[i : i + window_size]

                # Normalize multipliers at 100x
                normalized_mults = [
                    min(mult, self.normalize_cap) for _, mult, _, _ in window
                ]
                avg_mult = sum(normalized_mults) / len(normalized_mults)

                if avg_mult >= avg_threshold:
                    timestamp_start = window[0][0]
                    timestamp_end = window[-1][0]

                    all_windows.append(
                        {
                            "session_id": session_id,
                            "window_size": window_size,
                            "start_time": timestamp_start,
                            "end_time": timestamp_end,
                            "start_round_id": window[0][3],
                            "end_round_id": window[-1][3],
                            "raw_multipliers": [mult for _, mult, _, _ in window],
                            "normalized_multipliers": normalized_mults,
                            "avg_multiplier": avg_mult,
                            "max_multiplier": max(mult for _, mult, _, _ in window),
                            "min_multiplier": min(mult for _, mult, _, _ in window),
                            "bettor_counts": [
                                bc for _, _, bc, _ in window if bc is not None
                            ],
                            "over_100_count": sum(
                                1 for _, mult, _, _ in window if mult > 100
                            ),
                            "type": "window",
                        }
                    )

        return all_windows

    def get_context_rounds(
        self, round_id: int, before: int = 10, after: int = 10
    ) -> Dict:
        """Get rounds before and after a specific round"""
        cursor = self.conn.cursor()

        # Get the session_id and timestamp of the target round
        cursor.execute(
            """
            SELECT session_id, timestamp
            FROM multipliers
            WHERE id = ?
        """,
            (round_id,),
        )

        result = cursor.fetchone()
        if not result:
            return {"before": [], "after": []}

        session_id, timestamp_str = result

        # Get rounds before (same session, earlier timestamp)
        cursor.execute(
            """
            SELECT id, timestamp, multiplier, bettor_count
            FROM multipliers
            WHERE session_id = ?
              AND timestamp <= ?
              AND id < ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (session_id, timestamp_str, round_id, before),
        )

        before_rounds = [
            {
                "id": rid,
                "timestamp": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                "multiplier": mult,
                "bettor_count": bc,
            }
            for rid, ts, mult, bc in reversed(cursor.fetchall())
        ]

        # Get rounds after (same session, later timestamp)
        cursor.execute(
            """
            SELECT id, timestamp, multiplier, bettor_count
            FROM multipliers
            WHERE session_id = ?
              AND timestamp >= ?
              AND id > ?
            ORDER BY timestamp ASC
            LIMIT ?
        """,
            (session_id, timestamp_str, round_id, after),
        )

        after_rounds = [
            {
                "id": rid,
                "timestamp": datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                "multiplier": mult,
                "bettor_count": bc,
            }
            for rid, ts, mult, bc in cursor.fetchall()
        ]

        return {"before": before_rounds, "after": after_rounds}

    def analyze_all_definitions(self) -> Dict[str, List[Dict]]:
        """Analyze hot streaks using all three definitions"""
        print("Loading data by session...")
        sessions = self.load_data_by_session()

        if not sessions:
            return {}

        total_rounds = sum(len(rounds) for rounds in sessions.values())
        print(f"Loaded {total_rounds:,} rounds across {len(sessions)} sessions")

        results = {}

        # Definition 1: Strict consecutive
        print(
            f"\nAnalyzing Definition 1: Strict Consecutive (all ≥ {self.threshold}x)..."
        )
        strict_streaks = self.find_strict_hot_streaks(sessions)
        strict_streaks.sort(key=lambda x: x["length"], reverse=True)
        results["strict"] = strict_streaks
        print(f"  Found {len(strict_streaks)} strict hot streaks")
        if strict_streaks:
            print(f"  Longest: {strict_streaks[0]['length']} rounds")

        # Definition 2: Lenient (with 1-3 dips allowed)
        print(
            f"\nAnalyzing Definition 2: Lenient (≥ {self.threshold}x with 1-3 dips allowed)..."
        )
        lenient_streaks = self.find_lenient_hot_streaks(sessions, max_dips=3)
        lenient_streaks.sort(key=lambda x: x["length"], reverse=True)
        results["lenient"] = lenient_streaks
        print(f"  Found {len(lenient_streaks)} lenient hot streaks")
        if lenient_streaks:
            print(f"  Longest: {lenient_streaks[0]['length']} rounds")

        # Definition 3: Window-based
        print(
            f"\nAnalyzing Definition 3: Window-based (10-round avg ≥ 3.0x, capped at 100x)..."
        )
        window_streaks = self.find_window_hot_streaks(
            sessions, window_size=10, avg_threshold=3.0
        )
        window_streaks.sort(key=lambda x: x["avg_multiplier"], reverse=True)
        results["window"] = window_streaks
        print(f"  Found {len(window_streaks)} hot windows")
        if window_streaks:
            print(f"  Highest avg: {window_streaks[0]['avg_multiplier']:.2f}x")

        return results

    def generate_top_streaks_report(
        self, results: Dict[str, List[Dict]], output_path: str, top_n: int = 50
    ):
        """Generate detailed report of top streaks with context"""

        report_lines = []
        report_lines.append("=" * 120)
        report_lines.append("HOT STREAK ANALYSIS - TOP 50 WITH CONTEXT")
        report_lines.append("=" * 120)

        # Definition 1: Strict
        report_lines.append("\n" + "=" * 120)
        report_lines.append("DEFINITION 1: STRICT CONSECUTIVE (All rounds ≥ 2.0x)")
        report_lines.append("=" * 120)

        strict_streaks = results.get("strict", [])
        for rank, streak in enumerate(strict_streaks[:top_n], 1):
            context = self.get_context_rounds(
                streak["start_round_id"], before=10, after=10
            )

            report_lines.append(f"\n{'─' * 120}")
            report_lines.append(f"RANK #{rank} - {streak['length']} consecutive rounds")
            report_lines.append(f"{'─' * 120}")
            report_lines.append(f"Session: {streak['session_id']}")
            report_lines.append(
                f"Period: {streak['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {streak['end_time'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
            report_lines.append(f"Average Multiplier: {streak['avg_multiplier']:.2f}x")
            report_lines.append(
                f"Range: {streak['min_multiplier']:.2f}x - {streak['max_multiplier']:.2f}x"
            )

            # Before context
            if context["before"]:
                before_mults = [r["multiplier"] for r in context["before"]]
                report_lines.append(
                    f"\n10 Rounds BEFORE: {', '.join(f'{m:.2f}' for m in before_mults)}"
                )

            # The streak itself
            if len(streak["multipliers"]) <= 30:
                streak_str = ", ".join(f"{m:.2f}" for m in streak["multipliers"])
            else:
                first_15 = ", ".join(f"{m:.2f}" for m in streak["multipliers"][:15])
                last_15 = ", ".join(f"{m:.2f}" for m in streak["multipliers"][-15:])
                streak_str = f"{first_15} ... {last_15}"
            report_lines.append(f"HOT STREAK: [{streak_str}]")

            # After context
            if context["after"]:
                after_mults = [r["multiplier"] for r in context["after"]]
                report_lines.append(
                    f"10 Rounds AFTER: {', '.join(f'{m:.2f}' for m in after_mults)}"
                )

        # Definition 2: Lenient
        report_lines.append("\n\n" + "=" * 120)
        report_lines.append("DEFINITION 2: LENIENT (≥ 2.0x with 1-3 dips allowed)")
        report_lines.append("=" * 120)

        lenient_streaks = results.get("lenient", [])
        for rank, streak in enumerate(lenient_streaks[:top_n], 1):
            context = self.get_context_rounds(
                streak["start_round_id"], before=10, after=10
            )

            report_lines.append(f"\n{'─' * 120}")
            report_lines.append(
                f"RANK #{rank} - {streak['length']} total rounds ({streak['over_threshold_count']} over, {streak['dip_count']} dips)"
            )
            report_lines.append(f"{'─' * 120}")
            report_lines.append(f"Session: {streak['session_id']}")
            report_lines.append(
                f"Period: {streak['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {streak['end_time'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
            report_lines.append(f"Average Multiplier: {streak['avg_multiplier']:.2f}x")
            report_lines.append(
                f"Range: {streak['min_multiplier']:.2f}x - {streak['max_multiplier']:.2f}x"
            )

            # Before context
            if context["before"]:
                before_mults = [r["multiplier"] for r in context["before"]]
                report_lines.append(
                    f"\n10 Rounds BEFORE: {', '.join(f'{m:.2f}' for m in before_mults)}"
                )

            # The streak with dip markers
            if len(streak["multipliers"]) <= 30:
                streak_parts = []
                for m, is_dip in zip(streak["multipliers"], streak["is_dip"]):
                    if is_dip:
                        streak_parts.append(f"({m:.2f})")  # Dips in parentheses
                    else:
                        streak_parts.append(f"{m:.2f}")
                streak_str = ", ".join(streak_parts)
            else:
                first_15_parts = []
                for m, is_dip in zip(streak["multipliers"][:15], streak["is_dip"][:15]):
                    if is_dip:
                        first_15_parts.append(f"({m:.2f})")
                    else:
                        first_15_parts.append(f"{m:.2f}")

                last_15_parts = []
                for m, is_dip in zip(
                    streak["multipliers"][-15:], streak["is_dip"][-15:]
                ):
                    if is_dip:
                        last_15_parts.append(f"({m:.2f})")
                    else:
                        last_15_parts.append(f"{m:.2f}")

                streak_str = (
                    f"{', '.join(first_15_parts)} ... {', '.join(last_15_parts)}"
                )

            report_lines.append(f"HOT STREAK: [{streak_str}]  (dips in parentheses)")

            # After context
            if context["after"]:
                after_mults = [r["multiplier"] for r in context["after"]]
                report_lines.append(
                    f"10 Rounds AFTER: {', '.join(f'{m:.2f}' for m in after_mults)}"
                )

        # Definition 3: Window
        report_lines.append("\n\n" + "=" * 120)
        report_lines.append(
            "DEFINITION 3: WINDOW-BASED (10-round average ≥ 3.0x, capped at 100x)"
        )
        report_lines.append("=" * 120)

        window_streaks = results.get("window", [])
        for rank, window in enumerate(window_streaks[:top_n], 1):
            context = self.get_context_rounds(
                window["start_round_id"], before=10, after=10
            )

            report_lines.append(f"\n{'─' * 120}")
            report_lines.append(
                f"RANK #{rank} - Average: {window['avg_multiplier']:.2f}x (normalized)"
            )
            report_lines.append(f"{'─' * 120}")
            report_lines.append(f"Session: {window['session_id']}")
            report_lines.append(
                f"Period: {window['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {window['end_time'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
            report_lines.append(
                f"Range: {window['min_multiplier']:.2f}x - {window['max_multiplier']:.2f}x"
            )
            report_lines.append(f"Rounds over 100x: {window['over_100_count']}")

            # Before context
            if context["before"]:
                before_mults = [r["multiplier"] for r in context["before"]]
                report_lines.append(
                    f"\n10 Rounds BEFORE: {', '.join(f'{m:.2f}' for m in before_mults)}"
                )

            # The window with normalized values
            raw_str = ", ".join(f"{m:.2f}" for m in window["raw_multipliers"])
            norm_str = ", ".join(f"{m:.2f}" for m in window["normalized_multipliers"])

            report_lines.append(f"WINDOW (raw): [{raw_str}]")
            report_lines.append(f"WINDOW (norm): [{norm_str}]")

            # After context
            if context["after"]:
                after_mults = [r["multiplier"] for r in context["after"]]
                report_lines.append(
                    f"10 Rounds AFTER: {', '.join(f'{m:.2f}' for m in after_mults)}"
                )

        report_lines.append("\n" + "=" * 120)

        # Write to file
        with open(output_path, "w") as f:
            f.write("\n".join(report_lines))

        print(f"\n✓ Detailed report saved to: {output_path}")

    def create_visualizations(self, results: Dict[str, List[Dict]], output_dir: str):
        """Create all visualizations"""

        print("\nGenerating visualizations...")

        # 1. Distribution comparisons
        self.plot_length_distributions(
            results, f"{output_dir}/hot_streak_distributions.png"
        )

        # 2. Time of day analysis
        self.plot_time_of_day(results, f"{output_dir}/hot_streak_time_of_day.png")

        # 3. Day of week analysis
        self.plot_day_of_week(results, f"{output_dir}/hot_streak_day_of_week.png")

        # 4. Top streaks comparison
        self.plot_top_comparison(results, f"{output_dir}/hot_streak_top_comparison.png")

        # 5. Average multiplier analysis
        self.plot_avg_multiplier_analysis(
            results, f"{output_dir}/hot_streak_avg_multiplier.png"
        )

        # 6. Streak characteristics
        self.plot_streak_characteristics(
            results, f"{output_dir}/hot_streak_characteristics.png"
        )

        print("\n✓ All visualizations generated!")

    def plot_length_distributions(
        self, results: Dict[str, List[Dict]], output_path: str
    ):
        """Plot distribution of streak lengths for each definition"""

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle(
            "Hot Streak Length Distributions by Definition",
            fontsize=16,
            fontweight="bold",
        )

        colors = ["#4ECDC4", "#45B7D1", "#FFA500"]
        definitions = [
            ("strict", "Strict Consecutive\n(All ≥ 2.0x)"),
            ("lenient", "Lenient\n(≥ 2.0x, 1-3 dips OK)"),
            ("window", "Window-Based\n(10-round avg ≥ 3.0x)"),
        ]

        for idx, ((def_key, def_label), ax) in enumerate(zip(definitions, axes)):
            streaks = results.get(def_key, [])

            if not streaks:
                ax.text(
                    0.5,
                    0.5,
                    "No data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_title(def_label)
                continue

            if def_key == "window":
                # For windows, show average multiplier distribution
                values = [s["avg_multiplier"] for s in streaks]
                xlabel = "Average Multiplier (normalized)"
            else:
                # For streaks, show length distribution
                values = [s["length"] for s in streaks]
                xlabel = "Streak Length (rounds)"

            ax.hist(
                values,
                bins=30,
                color=colors[idx],
                alpha=0.7,
                edgecolor="black",
                linewidth=0.5,
            )

            mean_val = np.mean(values)
            median_val = np.median(values)

            ax.axvline(
                mean_val,
                color="red",
                linestyle="--",
                linewidth=2,
                label=f"Mean: {mean_val:.1f}",
            )
            ax.axvline(
                median_val,
                color="blue",
                linestyle="--",
                linewidth=2,
                label=f"Median: {median_val:.1f}",
            )

            ax.set_xlabel(xlabel, fontsize=10)
            ax.set_ylabel("Frequency", fontsize=10)
            ax.set_title(def_label, fontsize=11, fontweight="bold")
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)

            # Add stats text
            stats_text = f"Total: {len(streaks)}\nMax: {max(values):.1f}\nStd: {np.std(values):.1f}"
            ax.text(
                0.97,
                0.97,
                stats_text,
                transform=ax.transAxes,
                fontsize=9,
                verticalalignment="top",
                horizontalalignment="right",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            )

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def plot_time_of_day(self, results: Dict[str, List[Dict]], output_path: str):
        """Plot hot streak frequency by hour of day"""

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle(
            "Hot Streak Frequency by Time of Day", fontsize=16, fontweight="bold"
        )

        colors = ["#4ECDC4", "#45B7D1", "#FFA500"]
        definitions = [
            ("strict", "Strict Consecutive"),
            ("lenient", "Lenient"),
            ("window", "Window-Based"),
        ]

        for idx, ((def_key, def_label), ax) in enumerate(zip(definitions, axes)):
            streaks = results.get(def_key, [])

            if not streaks:
                ax.text(
                    0.5,
                    0.5,
                    "No data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_title(def_label)
                continue

            # Group by hour
            hour_counts = defaultdict(int)
            hour_avg_lengths = defaultdict(list)

            for streak in streaks:
                hour = streak["start_time"].hour
                hour_counts[hour] += 1

                if def_key == "window":
                    hour_avg_lengths[hour].append(streak["avg_multiplier"])
                else:
                    hour_avg_lengths[hour].append(streak["length"])

            hours = list(range(24))
            counts = [hour_counts.get(h, 0) for h in hours]
            avg_values = [
                np.mean(hour_avg_lengths[h]) if h in hour_avg_lengths else 0
                for h in hours
            ]

            # Dual axis
            ax2 = ax.twinx()

            bars = ax.bar(
                hours,
                counts,
                alpha=0.6,
                color=colors[idx],
                label="Count",
                edgecolor="black",
                linewidth=0.5,
            )
            line = ax2.plot(
                hours,
                avg_values,
                color="darkred",
                linewidth=2,
                marker="o",
                markersize=4,
                label="Avg Value",
            )

            ax.set_xlabel("Hour of Day (0-23)", fontsize=10)
            ax.set_ylabel("Number of Hot Streaks", fontsize=10, color=colors[idx])

            if def_key == "window":
                ax2.set_ylabel("Avg Multiplier", fontsize=10, color="darkred")
            else:
                ax2.set_ylabel("Avg Streak Length", fontsize=10, color="darkred")

            ax.set_title(def_label, fontsize=11, fontweight="bold")
            ax.set_xticks(hours)
            ax.tick_params(axis="y", labelcolor=colors[idx])
            ax2.tick_params(axis="y", labelcolor="darkred")
            ax.grid(True, alpha=0.3, axis="y")

            # Peak hour
            if counts and max(counts) > 0:
                peak_hour = hours[counts.index(max(counts))]
                ax.axvline(
                    peak_hour, color="red", linestyle=":", linewidth=2, alpha=0.5
                )

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def plot_day_of_week(self, results: Dict[str, List[Dict]], output_path: str):
        """Plot hot streak frequency by day of week"""

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle(
            "Hot Streak Frequency by Day of Week", fontsize=16, fontweight="bold"
        )

        colors = ["#4ECDC4", "#45B7D1", "#FFA500"]
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        definitions = [
            ("strict", "Strict Consecutive"),
            ("lenient", "Lenient"),
            ("window", "Window-Based"),
        ]

        for idx, ((def_key, def_label), ax) in enumerate(zip(definitions, axes)):
            streaks = results.get(def_key, [])

            if not streaks:
                ax.text(
                    0.5,
                    0.5,
                    "No data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_title(def_label)
                continue

            # Group by day
            day_counts = defaultdict(int)
            day_max_values = defaultdict(float)

            for streak in streaks:
                day = streak["start_time"].weekday()
                day_counts[day] += 1

                if def_key == "window":
                    day_max_values[day] = max(
                        day_max_values[day], streak["avg_multiplier"]
                    )
                else:
                    day_max_values[day] = max(day_max_values[day], streak["length"])

            days = list(range(7))
            counts = [day_counts.get(d, 0) for d in days]
            max_values = [day_max_values.get(d, 0) for d in days]

            x_pos = np.arange(len(day_names))

            bars = ax.bar(
                x_pos,
                counts,
                alpha=0.7,
                color=colors[idx],
                edgecolor="black",
                linewidth=0.5,
            )

            # Add max value markers
            ax2 = ax.twinx()
            ax2.scatter(
                x_pos,
                max_values,
                color="darkred",
                s=100,
                zorder=5,
                marker="^",
                edgecolors="black",
                linewidth=1,
            )

            ax.set_xlabel("Day of Week", fontsize=10)
            ax.set_ylabel("Number of Hot Streaks", fontsize=10, color=colors[idx])

            if def_key == "window":
                ax2.set_ylabel("Max Avg Multiplier", fontsize=10, color="darkred")
            else:
                ax2.set_ylabel("Max Streak Length", fontsize=10, color="darkred")

            ax.set_title(def_label, fontsize=11, fontweight="bold")
            ax.set_xticks(x_pos)
            ax.set_xticklabels(day_names)
            ax.tick_params(axis="y", labelcolor=colors[idx])
            ax2.tick_params(axis="y", labelcolor="darkred")
            ax.grid(True, alpha=0.3, axis="y")

            # Add count labels
            for i, count in enumerate(counts):
                if count > 0:
                    ax.text(
                        i,
                        count,
                        str(count),
                        ha="center",
                        va="bottom",
                        fontsize=8,
                        fontweight="bold",
                    )

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def plot_top_comparison(self, results: Dict[str, List[Dict]], output_path: str):
        """Compare top hot streaks across definitions"""

        fig, ax = plt.subplots(figsize=(16, 10))

        all_top = []
        colors_map = {"strict": "#4ECDC4", "lenient": "#45B7D1", "window": "#FFA500"}

        # Collect top 15 from each
        for def_key in ["strict", "lenient", "window"]:
            streaks = results.get(def_key, [])

            for streak in streaks[:15]:
                if def_key == "window":
                    value = streak["avg_multiplier"]
                    label_val = f"{value:.2f}x avg"
                else:
                    value = streak["length"]
                    label_val = f"{value} rounds"

                all_top.append(
                    {
                        "type": def_key,
                        "value": value,
                        "label": label_val,
                        "start_time": streak["start_time"],
                        "color": colors_map[def_key],
                    }
                )

        # Sort by value
        all_top.sort(key=lambda x: x["value"], reverse=True)
        top_45 = all_top[:45]

        y_pos = np.arange(len(top_45))
        values = [s["value"] for s in top_45]
        colors = [s["color"] for s in top_45]

        bars = ax.barh(
            y_pos, values, color=colors, alpha=0.7, edgecolor="black", linewidth=0.5
        )

        # Labels
        for i, (bar, streak) in enumerate(zip(bars, top_45)):
            width = bar.get_width()
            label = (
                f"{streak['label']} | {streak['start_time'].strftime('%m/%d %H:%M')}"
            )
            ax.text(
                width,
                bar.get_y() + bar.get_height() / 2,
                f"  {label}",
                va="center",
                fontsize=7,
            )

        ax.set_xlabel(
            "Value (length or avg multiplier)", fontsize=12, fontweight="bold"
        )
        ax.set_ylabel("Rank", fontsize=12, fontweight="bold")
        ax.set_title(
            "Top 45 Hot Streaks Across All Definitions", fontsize=14, fontweight="bold"
        )
        ax.set_yticks(y_pos)
        ax.set_yticklabels([f"#{i + 1}" for i in range(len(top_45))])
        ax.invert_yaxis()
        ax.grid(True, alpha=0.3, axis="x")

        # Legend
        legend_elements = [
            mpatches.Patch(color=colors_map["strict"], label="Strict Consecutive"),
            mpatches.Patch(color=colors_map["lenient"], label="Lenient (1-3 dips)"),
            mpatches.Patch(color=colors_map["window"], label="Window-Based"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=10)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def plot_avg_multiplier_analysis(
        self, results: Dict[str, List[Dict]], output_path: str
    ):
        """Analyze average multipliers in hot streaks"""

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(
            "Hot Streak Average Multiplier Analysis", fontsize=16, fontweight="bold"
        )

        # Plot 1: Average multiplier distribution (all definitions)
        ax1 = axes[0, 0]

        for def_key, color, label in [
            ("strict", "#4ECDC4", "Strict"),
            ("lenient", "#45B7D1", "Lenient"),
            ("window", "#FFA500", "Window"),
        ]:
            streaks = results.get(def_key, [])
            if streaks:
                avgs = [s["avg_multiplier"] for s in streaks]
                ax1.hist(
                    avgs,
                    bins=30,
                    alpha=0.5,
                    color=color,
                    label=label,
                    edgecolor="black",
                    linewidth=0.3,
                )

        ax1.set_xlabel("Average Multiplier", fontsize=10)
        ax1.set_ylabel("Frequency", fontsize=10)
        ax1.set_title(
            "Average Multiplier Distribution (All Definitions)",
            fontsize=11,
            fontweight="bold",
        )
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)

        # Plot 2: Max multiplier in streaks
        ax2 = axes[0, 1]

        strict_max = [
            s["max_multiplier"]
            for s in results.get("strict", [])
            if s["max_multiplier"] <= 100
        ]
        lenient_max = [
            s["max_multiplier"]
            for s in results.get("lenient", [])
            if s["max_multiplier"] <= 100
        ]
        window_max = [
            s["max_multiplier"]
            for s in results.get("window", [])
            if s["max_multiplier"] <= 100
        ]

        bp = ax2.boxplot(
            [strict_max, lenient_max, window_max],
            labels=["Strict", "Lenient", "Window"],
            patch_artist=True,
        )

        for patch, color in zip(bp["boxes"], ["#4ECDC4", "#45B7D1", "#FFA500"]):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax2.set_ylabel("Max Multiplier (≤ 100x)", fontsize=10)
        ax2.set_title("Maximum Multiplier in Streaks", fontsize=11, fontweight="bold")
        ax2.grid(True, alpha=0.3, axis="y")

        # Plot 3: Avg vs Length (strict streaks only)
        ax3 = axes[1, 0]

        strict_streaks = results.get("strict", [])
        if strict_streaks:
            x = [s["length"] for s in strict_streaks]
            y = [s["avg_multiplier"] for s in strict_streaks]

            scatter = ax3.scatter(
                x,
                y,
                c=y,
                cmap="YlOrRd",
                alpha=0.6,
                edgecolors="black",
                linewidth=0.5,
                s=50,
            )

            ax3.set_xlabel("Streak Length (rounds)", fontsize=10)
            ax3.set_ylabel("Average Multiplier", fontsize=10)
            ax3.set_title(
                "Strict: Length vs Avg Multiplier", fontsize=11, fontweight="bold"
            )
            ax3.grid(True, alpha=0.3)

            cbar = plt.colorbar(scatter, ax=ax3)
            cbar.set_label("Avg Mult", rotation=270, labelpad=15)

        # Plot 4: Summary statistics table
        ax4 = axes[1, 1]
        ax4.axis("off")

        table_data = []
        table_data.append(["Definition", "Count", "Avg Mult", "Max Mult", "Avg Length"])
        table_data.append(["─" * 15, "─" * 8, "─" * 10, "─" * 10, "─" * 12])

        for def_key, label in [
            ("strict", "Strict"),
            ("lenient", "Lenient"),
            ("window", "Window"),
        ]:
            streaks = results.get(def_key, [])
            if streaks:
                count = len(streaks)
                avg_mult = np.mean([s["avg_multiplier"] for s in streaks])
                max_mult = max([s["max_multiplier"] for s in streaks])

                if def_key == "window":
                    avg_len = 10  # Window size
                else:
                    avg_len = np.mean([s["length"] for s in streaks])

                table_data.append(
                    [
                        label,
                        f"{count:,}",
                        f"{avg_mult:.2f}x",
                        f"{max_mult:.2f}x",
                        f"{avg_len:.1f}",
                    ]
                )

        table_text = "\n".join(
            [
                f"{row[0]:<15} {row[1]:>8} {row[2]:>10} {row[3]:>10} {row[4]:>12}"
                for row in table_data
            ]
        )

        ax4.text(
            0.1,
            0.9,
            table_text,
            transform=ax4.transAxes,
            fontsize=11,
            verticalalignment="top",
            family="monospace",
            bbox=dict(boxstyle="round", facecolor="lightgreen", alpha=0.3),
        )

        ax4.set_title("Summary Statistics", fontsize=11, fontweight="bold")

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def plot_streak_characteristics(
        self, results: Dict[str, List[Dict]], output_path: str
    ):
        """Plot various characteristics of hot streaks"""

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle("Hot Streak Characteristics", fontsize=16, fontweight="bold")

        # Plot 1: Dip analysis for lenient streaks
        ax1 = axes[0, 0]

        lenient_streaks = results.get("lenient", [])
        if lenient_streaks:
            dip_counts = [s["dip_count"] for s in lenient_streaks]
            dip_distribution = defaultdict(int)
            for count in dip_counts:
                dip_distribution[count] += 1

            x = sorted(dip_distribution.keys())
            y = [dip_distribution[i] for i in x]

            bars = ax1.bar(
                x, y, color="#45B7D1", alpha=0.7, edgecolor="black", linewidth=0.5
            )

            for bar, count in zip(bars, y):
                height = bar.get_height()
                ax1.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{count}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    fontweight="bold",
                )

            ax1.set_xlabel("Number of Dips in Streak", fontsize=10)
            ax1.set_ylabel("Frequency", fontsize=10)
            ax1.set_title(
                "Lenient Streaks: Dip Distribution", fontsize=11, fontweight="bold"
            )
            ax1.set_xticks(x)
            ax1.grid(True, alpha=0.3, axis="y")

        # Plot 2: Over 100x occurrences in windows
        ax2 = axes[0, 1]

        window_streaks = results.get("window", [])
        if window_streaks:
            over_100_counts = [s["over_100_count"] for s in window_streaks]
            over_100_dist = defaultdict(int)
            for count in over_100_counts:
                over_100_dist[count] += 1

            x = sorted(over_100_dist.keys())
            y = [over_100_dist[i] for i in x]

            bars = ax2.bar(
                x, y, color="#FFA500", alpha=0.7, edgecolor="black", linewidth=0.5
            )

            for bar, count in zip(bars, y):
                height = bar.get_height()
                ax2.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{count}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    fontweight="bold",
                )

            ax2.set_xlabel("Number of 100x+ Rounds in Window", fontsize=10)
            ax2.set_ylabel("Frequency", fontsize=10)
            ax2.set_title(
                "Window Streaks: 100x+ Occurrences", fontsize=11, fontweight="bold"
            )
            ax2.set_xticks(x if x else [0])
            ax2.grid(True, alpha=0.3, axis="y")

        # Plot 3: Duration analysis
        ax3 = axes[1, 0]

        for def_key, color, label in [
            ("strict", "#4ECDC4", "Strict"),
            ("lenient", "#45B7D1", "Lenient"),
            ("window", "#FFA500", "Window"),
        ]:
            streaks = results.get(def_key, [])
            if streaks:
                durations = [
                    (s["end_time"] - s["start_time"]).total_seconds() / 60
                    for s in streaks
                ]
                ax3.hist(
                    durations,
                    bins=30,
                    alpha=0.5,
                    color=color,
                    label=label,
                    edgecolor="black",
                    linewidth=0.3,
                )

        ax3.set_xlabel("Duration (minutes)", fontsize=10)
        ax3.set_ylabel("Frequency", fontsize=10)
        ax3.set_title("Streak Duration Distribution", fontsize=11, fontweight="bold")
        ax3.legend(fontsize=9)
        ax3.grid(True, alpha=0.3)

        # Plot 4: Min multiplier in streaks
        ax4 = axes[1, 1]

        for def_key, color, label in [
            ("strict", "#4ECDC4", "Strict"),
            ("lenient", "#45B7D1", "Lenient"),
            ("window", "#FFA500", "Window"),
        ]:
            streaks = results.get(def_key, [])
            if streaks:
                mins = [s["min_multiplier"] for s in streaks]
                ax4.hist(
                    mins,
                    bins=30,
                    alpha=0.5,
                    color=color,
                    label=label,
                    edgecolor="black",
                    linewidth=0.3,
                )

        ax4.set_xlabel("Minimum Multiplier in Streak", fontsize=10)
        ax4.set_ylabel("Frequency", fontsize=10)
        ax4.set_title("Minimum Multiplier Distribution", fontsize=11, fontweight="bold")
        ax4.legend(fontsize=9)
        ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"✓ Saved: {output_path}")

    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze hot streaks with multiple definitions and visualizations"
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--output-dir",
        default="data-analyze/outputs",
        help="Output directory (default: data-analyze/outputs)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Number of top streaks to show in report (default: 50)",
    )

    args = parser.parse_args()

    # Check for required packages
    try:
        import matplotlib
        import numpy
    except ImportError:
        print("❌ Missing required packages!")
        print("\nInstall with:")
        print("  pip install matplotlib numpy --break-system-packages")
        sys.exit(1)

    print("=" * 100)
    print("HOT STREAK ANALYZER - THREE DEFINITIONS")
    print("=" * 100)
    print(f"\nDatabase: {args.db}")
    print(f"Output Directory: {args.output_dir}")
    print("\nDefinitions:")
    print("  1. Strict: All consecutive rounds ≥ 2.0x")
    print("  2. Lenient: Consecutive rounds ≥ 2.0x with 1-3 dips allowed")
    print("  3. Window: 10-round windows with avg ≥ 3.0x (100x+ normalized to 100x)")
    print("\n" + "=" * 100)

    analyzer = HotStreakAnalyzer(args.db)

    try:
        import os

        os.makedirs(args.output_dir, exist_ok=True)

        # Analyze all definitions
        results = analyzer.analyze_all_definitions()

        if not results:
            print(
                "\n❌ No results generated. Check if your database has session assignments."
            )
            sys.exit(1)

        # Generate detailed report
        report_path = f"{args.output_dir}/hot_streaks_top_{args.top}_with_context.txt"
        analyzer.generate_top_streaks_report(results, report_path, top_n=args.top)

        # Create visualizations
        analyzer.create_visualizations(results, args.output_dir)

        print("\n" + "=" * 100)
        print("GENERATED FILES:")
        print("=" * 100)
        print(f"  Report: {report_path}")
        print(f"  Visualizations:")
        print(f"    - {args.output_dir}/hot_streak_distributions.png")
        print(f"    - {args.output_dir}/hot_streak_time_of_day.png")
        print(f"    - {args.output_dir}/hot_streak_day_of_week.png")
        print(f"    - {args.output_dir}/hot_streak_top_comparison.png")
        print(f"    - {args.output_dir}/hot_streak_avg_multiplier.png")
        print(f"    - {args.output_dir}/hot_streak_characteristics.png")
        print("=" * 100)

        print("\n✓ Analysis complete!")

    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
