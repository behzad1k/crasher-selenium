#!/usr/bin/env python3
"""
Losing Streak Analysis by Threshold
Analyzes longest consecutive losing streaks per multiplier threshold (2x, 3x, 5x, 10x)
Session-aware to handle data gaps correctly
"""

import json
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Tuple


class LosingStreakAnalyzer:
    """Analyze losing streaks with session awareness"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path)
        self.thresholds = [
            2.0,
            3.0,
            4.0,
            5.0,
            6.0,
            7.0,
            8.0,
            9.0,
            10.0,
            11.0,
            12.0,
            13.0,
            14.0,
            15.0,
            16.0,
            17.0,
            18.0,
            19.0,
            20.0,
        ]

    def load_data_by_session(self) -> Dict[int, List[Tuple]]:
        """
        Load all multipliers grouped by session
        Returns: {session_id: [(timestamp, multiplier), ...]}
        """
        cursor = self.conn.cursor()

        # Get all rounds with session_id, ordered by session and timestamp
        cursor.execute("""
            SELECT
                session_id,
                timestamp,
                multiplier
            FROM multipliers
            WHERE session_id IS NOT NULL
            ORDER BY session_id, timestamp
        """)

        rows = cursor.fetchall()

        if not rows:
            print("❌ No data found with session assignments!")
            print("\nRun this first:")
            print("  python import_logs.py --detect-sessions")
            return {}

        # Group by session
        sessions = {}
        for session_id, timestamp_str, multiplier in rows:
            if session_id not in sessions:
                sessions[session_id] = []

            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            sessions[session_id].append((timestamp, multiplier))

        return sessions

    def find_streaks_for_threshold(
        self, sessions: Dict[int, List[Tuple]], threshold: float
    ) -> List[Dict]:
        """
        Find all losing streaks (consecutive rounds under threshold) per session
        Returns: List of streak dictionaries
        """
        all_streaks = []

        for session_id, rounds in sessions.items():
            current_streak = []

            for timestamp, multiplier in rounds:
                if multiplier < threshold:
                    # Under threshold - add to current streak
                    current_streak.append(
                        {"timestamp": timestamp, "multiplier": multiplier}
                    )
                else:
                    # Hit or exceeded threshold - save current streak if exists
                    if current_streak:
                        all_streaks.append(
                            {
                                "session_id": session_id,
                                "length": len(current_streak),
                                "start_time": current_streak[0]["timestamp"],
                                "end_time": current_streak[-1]["timestamp"],
                                "multipliers": [
                                    r["multiplier"] for r in current_streak
                                ],
                                "avg_multiplier": sum(
                                    r["multiplier"] for r in current_streak
                                )
                                / len(current_streak),
                            }
                        )
                        current_streak = []

            # Don't forget last streak in session (if session ended during streak)
            if current_streak:
                all_streaks.append(
                    {
                        "session_id": session_id,
                        "length": len(current_streak),
                        "start_time": current_streak[0]["timestamp"],
                        "end_time": current_streak[-1]["timestamp"],
                        "multipliers": [r["multiplier"] for r in current_streak],
                        "avg_multiplier": sum(r["multiplier"] for r in current_streak)
                        / len(current_streak),
                        "incomplete": True,  # Mark as potentially incomplete
                    }
                )
                current_streak = []

        return all_streaks

    def get_session_info(self, session_id: int) -> Dict:
        """Get session metadata"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT
                start_timestamp,
                end_timestamp,
                start_balance,
                end_balance,
                total_rounds
            FROM sessions
            WHERE id = ?
        """,
            (session_id,),
        )

        row = cursor.fetchone()
        if row:
            return {
                "start": row[0],
                "end": row[1],
                "start_balance": row[2],
                "end_balance": row[3],
                "total_rounds": row[4],
            }
        return {}

    def analyze_all_thresholds(self) -> Dict[float, List[Dict]]:
        """
        Analyze losing streaks for all thresholds
        Returns: {threshold: [streaks]}
        """
        print("Loading data by session...")
        sessions = self.load_data_by_session()

        if not sessions:
            return {}

        total_rounds = sum(len(rounds) for rounds in sessions.values())
        print(f"Loaded {total_rounds:,} rounds across {len(sessions)} sessions")

        results = {}

        for threshold in self.thresholds:
            print(f"\nAnalyzing threshold: {threshold}x...")
            streaks = self.find_streaks_for_threshold(sessions, threshold)

            # Sort by length (descending)
            streaks.sort(key=lambda x: x["length"], reverse=True)

            results[threshold] = streaks
            print(f"  Found {len(streaks)} streaks")
            if streaks:
                print(f"  Longest: {streaks[0]['length']} rounds")

        return results

    def print_report(self, results: Dict[float, List[Dict]], top_n: int = 20):
        """Print comprehensive report"""

        print("\n" + "=" * 100)
        print("LOSING STREAK ANALYSIS - TOP 20 BY THRESHOLD")
        print("=" * 100)

        for threshold in self.thresholds:
            streaks = results.get(threshold, [])

            if not streaks:
                continue

            print(f"\n{'=' * 100}")
            print(f"THRESHOLD: UNDER {threshold}x")
            print(f"{'=' * 100}")

            # Statistics
            total_streaks = len(streaks)
            longest = streaks[0]["length"] if streaks else 0
            avg_length = (
                sum(s["length"] for s in streaks) / len(streaks) if streaks else 0
            )
            avg_multiplier_overall = (
                sum(s["avg_multiplier"] for s in streaks) / len(streaks)
                if streaks
                else 0
            )

            print(f"\nSTATISTICS:")
            print(f"  Total Streaks: {total_streaks:,}")
            print(f"  Longest Streak: {longest} consecutive rounds")
            print(f"  Average Streak Length: {avg_length:.2f} rounds")
            print(f"  Average Multiplier During Streaks: {avg_multiplier_overall:.3f}x")

            # Top 20
            print(f"\nTOP {top_n} LONGEST STREAKS:")
            print(f"{'-' * 100}")
            print(
                f"{'Rank':<6} {'Length':<8} {'Avg Mult':<10} {'Session':<10} {'Started':<20} {'Duration':<12} {'Status':<10}"
            )
            print(f"{'-' * 100}")

            for rank, streak in enumerate(streaks[:top_n], 1):
                length = streak["length"]
                avg_mult = streak["avg_multiplier"]
                session_id = streak["session_id"]
                start_time = streak["start_time"].strftime("%Y-%m-%d %H:%M:%S")

                # Calculate duration
                duration = (
                    streak["end_time"] - streak["start_time"]
                ).total_seconds() / 60
                duration_str = f"{duration:.1f} min"

                # Check if incomplete
                status = "INCOMPLETE" if streak.get("incomplete") else "Complete"

                print(
                    f"{rank:<6} {length:<8} {avg_mult:<10.3f} {session_id:<10} {start_time:<20} {duration_str:<12} {status:<10}"
                )

            # Show some example streaks with details
            print(f"\nDETAILED VIEW - TOP 5 STREAKS:")
            print(f"{'-' * 100}")

            for rank, streak in enumerate(streaks[:5], 1):
                session_info = self.get_session_info(streak["session_id"])

                print(
                    f"\n#{rank} - {streak['length']} consecutive rounds under {threshold}x"
                )
                print(f"  Session: {streak['session_id']}")
                print(
                    f"  Period: {streak['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {streak['end_time'].strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(f"  Average Multiplier: {streak['avg_multiplier']:.3f}x")
                print(f"  Min Multiplier: {min(streak['multipliers']):.2f}x")
                print(f"  Max Multiplier: {max(streak['multipliers']):.2f}x")

                if session_info:
                    if session_info.get("start_balance") and session_info.get(
                        "end_balance"
                    ):
                        profit = (
                            session_info["end_balance"] - session_info["start_balance"]
                        )
                        print(
                            f"  Session Balance: {session_info['start_balance']:,.0f} → {session_info['end_balance']:,.0f} ({profit:+,.0f})"
                        )

                # Show first 10 and last 10 multipliers
                mults = streak["multipliers"]
                if len(mults) <= 20:
                    mults_str = ", ".join(f"{m:.2f}" for m in mults)
                else:
                    first_10 = ", ".join(f"{m:.2f}" for m in mults[:10])
                    last_10 = ", ".join(f"{m:.2f}" for m in mults[-10:])
                    mults_str = f"{first_10} ... {last_10}"

                print(f"  Multipliers: {mults_str}")

                if streak.get("incomplete"):
                    print(
                        f"  ⚠️  WARNING: Streak may be incomplete (session ended during streak)"
                    )

        print("\n" + "=" * 100)

    def generate_json_report(self, results: Dict[float, List[Dict]], output_path: str):
        """Generate JSON report for further analysis"""

        json_data = {}

        for threshold, streaks in results.items():
            json_data[f"{threshold}x"] = {
                "threshold": threshold,
                "total_streaks": len(streaks),
                "longest_streak": streaks[0]["length"] if streaks else 0,
                "average_length": sum(s["length"] for s in streaks) / len(streaks)
                if streaks
                else 0,
                "average_multiplier": sum(s["avg_multiplier"] for s in streaks)
                / len(streaks)
                if streaks
                else 0,
                "top_20_streaks": [
                    {
                        "rank": i + 1,
                        "length": s["length"],
                        "session_id": s["session_id"],
                        "start_time": s["start_time"].isoformat(),
                        "end_time": s["end_time"].isoformat(),
                        "average_multiplier": s["avg_multiplier"],
                        "min_multiplier": min(s["multipliers"]),
                        "max_multiplier": max(s["multipliers"]),
                        "incomplete": s.get("incomplete", False),
                        "multipliers": s["multipliers"],
                    }
                    for i, s in enumerate(streaks[:20])
                ],
            }

        with open(output_path, "w") as f:
            json.dump(json_data, f, indent=2)

        print(f"\n✓ JSON report saved to: {output_path}")

    def generate_risk_analysis(self, results: Dict[float, List[Dict]]):
        """Generate risk analysis based on streak data"""

        print("\n" + "=" * 100)
        print("RISK ANALYSIS - BETTING STRATEGY IMPLICATIONS")
        print("=" * 100)

        # Analyze each threshold for common betting strategies
        strategies = [
            {
                "name": "2x Strategy (Wait 8, Martingale 5)",
                "threshold": 2.0,
                "trigger": 8,
                "max_losses": 5,
                "wipeout_streak": 13,  # 8 + 5
            },
            {
                "name": "3x Strategy (Wait 35, Martingale 5)",
                "threshold": 3.0,
                "trigger": 35,
                "max_losses": 5,
                "wipeout_streak": 40,  # 35 + 5
            },
            {
                "name": "5x Strategy (Wait 45, Martingale 5)",
                "threshold": 5.0,
                "trigger": 45,
                "max_losses": 5,
                "wipeout_streak": 50,  # 45 + 5
            },
            {
                "name": "10x Strategy (Wait 65, Martingale 5)",
                "threshold": 10.0,
                "trigger": 65,
                "max_losses": 5,
                "wipeout_streak": 70,  # 65 + 5
            },
        ]

        for strategy in strategies:
            threshold = strategy["threshold"]
            streaks = results.get(threshold, [])

            if not streaks:
                continue

            print(f"\n{'-' * 100}")
            print(f"STRATEGY: {strategy['name']}")
            print(f"{'-' * 100}")

            # Count outcomes
            trigger_count = sum(
                1 for s in streaks if s["length"] >= strategy["trigger"]
            )
            wipeout_count = sum(
                1 for s in streaks if s["length"] >= strategy["wipeout_streak"]
            )
            partial_loss_count = sum(
                1
                for s in streaks
                if strategy["trigger"] <= s["length"] < strategy["wipeout_streak"]
            )

            print(
                f"  Trigger Condition ({strategy['trigger']}+ streaks): {trigger_count} times"
            )
            print(
                f"  Would Win: {trigger_count - partial_loss_count - wipeout_count} times ({(trigger_count - partial_loss_count - wipeout_count) / max(trigger_count, 1) * 100:.1f}%)"
            )
            print(
                f"  Partial Loss ({strategy['trigger']}-{strategy['wipeout_streak'] - 1} streaks): {partial_loss_count} times ({partial_loss_count / max(trigger_count, 1) * 100:.1f}%)"
            )
            print(
                f"  TOTAL WIPEOUT ({strategy['wipeout_streak']}+ streaks): {wipeout_count} times ({wipeout_count / max(trigger_count, 1) * 100:.1f}%)"
            )

            if wipeout_count > 0:
                print(f"\n  ⚠️  WIPEOUT EVENTS:")
                wipeouts = [
                    s for s in streaks if s["length"] >= strategy["wipeout_streak"]
                ][:10]
                for w in wipeouts:
                    print(
                        f"    - {w['length']} rounds in Session {w['session_id']} ({w['start_time'].strftime('%Y-%m-%d %H:%M')})"
                    )

            # Calculate expected value (simplified)
            if trigger_count > 0:
                win_rate = (
                    trigger_count - partial_loss_count - wipeout_count
                ) / trigger_count
                print(f"\n  Estimated Win Rate: {win_rate * 100:.1f}%")

                if win_rate < 0.5:
                    print(
                        f"  ⚠️  WARNING: Win rate below 50% - Strategy may be unprofitable"
                    )

        print("\n" + "=" * 100)

    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze losing streaks by multiplier threshold with session awareness"
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top streaks to show (default: 20)",
    )
    parser.add_argument("--json", help="Save detailed results to JSON file")
    parser.add_argument(
        "--risk-analysis",
        action="store_true",
        help="Include risk analysis for betting strategies",
    )

    args = parser.parse_args()

    print("=" * 100)
    print("LOSING STREAK ANALYZER - SESSION AWARE")
    print("=" * 100)
    print(f"\nDatabase: {args.db}")
    print(f"Analyzing thresholds: 2x, 3x, 5x, 10x")
    print(f"Top streaks to show: {args.top}")
    print("\n" + "=" * 100)

    analyzer = LosingStreakAnalyzer(args.db)

    try:
        # Analyze all thresholds
        results = analyzer.analyze_all_thresholds()

        if not results:
            print(
                "\n❌ No results generated. Check if your database has session assignments."
            )
            sys.exit(1)

        # Print report
        analyzer.print_report(results, top_n=args.top)

        # Risk analysis
        if args.risk_analysis:
            analyzer.generate_risk_analysis(results)

        # Save JSON if requested
        if args.json:
            analyzer.generate_json_report(results, args.json)

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
