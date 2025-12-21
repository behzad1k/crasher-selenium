#!/usr/bin/env python3
"""
Crasher Game Data Analysis
Analyzes multiplier streaks and session statistics
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Tuple

import pandas as pd


class CrasherAnalyzer:
    """Analyze crasher game data with session detection"""

    def __init__(self, db_path: str = "./crasher_data.db", threshold: float = 2.0):
        self.conn = sqlite3.connect(db_path)
        self.threshold = threshold
        self.max_gap_minutes = 3  # Maximum gap between rounds in same session

    def load_data(self) -> pd.DataFrame:
        """Load multiplier data from database"""
        query = """
            SELECT
                id,
                multiplier,
                bettor_count,
                timestamp
            FROM multipliers
            ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(query, self.conn)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def detect_sessions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect sessions based on time gaps
        A new session starts if gap > max_gap_minutes
        """
        df = df.copy()
        df["time_diff"] = df["timestamp"].diff()
        df["new_session"] = df["time_diff"] > timedelta(minutes=self.max_gap_minutes)
        df["session_id"] = df["new_session"].cumsum()

        # First round is always session 0
        if len(df) > 0:
            df.loc[0, "session_id"] = 0

        return df

    def find_streaks(self, df: pd.DataFrame) -> List[dict]:
        """Find all streaks of rounds under threshold"""
        df = df.copy()
        df["under_threshold"] = df["multiplier"] < self.threshold

        streaks = []
        current_streak = []

        for idx, row in df.iterrows():
            if row["under_threshold"]:
                current_streak.append(
                    {
                        "id": row["id"],
                        "multiplier": row["multiplier"],
                        "timestamp": row["timestamp"],
                        "session_id": row["session_id"],
                    }
                )
            else:
                if current_streak:
                    streaks.append(
                        {
                            "length": len(current_streak),
                            "rounds": current_streak,
                            "session_id": current_streak[0]["session_id"],
                            "start_time": current_streak[0]["timestamp"],
                            "end_time": current_streak[-1]["timestamp"],
                        }
                    )
                    current_streak = []

        # Don't forget last streak if it exists
        if current_streak:
            streaks.append(
                {
                    "length": len(current_streak),
                    "rounds": current_streak,
                    "session_id": current_streak[0]["session_id"],
                    "start_time": current_streak[0]["timestamp"],
                    "end_time": current_streak[-1]["timestamp"],
                }
            )

        return streaks

    def analyze_streaks(self, streaks: List[dict]) -> dict:
        """Analyze streak statistics"""
        if not streaks:
            return {"total_streaks": 0, "longest_streak": 0, "streak_distribution": {}}

        streak_lengths = [s["length"] for s in streaks]

        # Count streaks by length
        distribution = {}
        for length in range(1, max(streak_lengths) + 1):
            count = sum(1 for l in streak_lengths if l == length)
            if count > 0:
                distribution[length] = count

        # Specific counts requested
        specific_counts = {
            6: distribution.get(6, 0),
            7: distribution.get(7, 0),
            8: distribution.get(8, 0),
            9: distribution.get(9, 0),
            10: distribution.get(10, 0),
        }

        return {
            "total_streaks": len(streaks),
            "longest_streak": max(streak_lengths),
            "average_streak": sum(streak_lengths) / len(streak_lengths),
            "streak_distribution": distribution,
            "specific_counts": specific_counts,
        }

    def session_statistics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate statistics per session"""
        session_stats = []

        for session_id in df["session_id"].unique():
            session_df = df[df["session_id"] == session_id]

            session_stats.append(
                {
                    "session_id": int(session_id),
                    "total_rounds": len(session_df),
                    "start_time": session_df["timestamp"].min(),
                    "end_time": session_df["timestamp"].max(),
                    "duration_minutes": (
                        session_df["timestamp"].max() - session_df["timestamp"].min()
                    ).total_seconds()
                    / 60,
                    "avg_multiplier": session_df["multiplier"].mean(),
                    "max_multiplier": session_df["multiplier"].max(),
                    "min_multiplier": session_df["multiplier"].min(),
                    "rounds_under_2x": (
                        session_df["multiplier"] < self.threshold
                    ).sum(),
                    "percentage_under_2x": (
                        session_df["multiplier"] < self.threshold
                    ).sum()
                    / len(session_df)
                    * 100,
                }
            )

        return pd.DataFrame(session_stats)

    def risk_assessment(self, streaks: List[dict]) -> dict:
        """
        Assess risk based on actual data
        Strategy: Wait for 10 under 2x, then bet with martingale for up to 5 rounds
        Risk: Total of 15 consecutive under 2x would wipe out bank
        """
        # Find streaks of 15+ (would wipe out bank)
        catastrophic_streaks = [s for s in streaks if s["length"] >= 15]

        # Find streaks of 10+ (trigger condition met)
        trigger_streaks = [s for s in streaks if s["length"] >= 10]

        # Find streaks that would cause losses (11-14 under 2x)
        # These would trigger betting but lose some rounds
        partial_loss_streaks = [s for s in streaks if 11 <= s["length"] <= 14]

        # Calculate how many times strategy would have been triggered
        # and what would have happened
        outcomes = []
        for streak in trigger_streaks:
            length = streak["length"]
            if length >= 15:
                outcome = "TOTAL_LOSS"
                rounds_lost = 5  # Lost all 5 martingale rounds
            elif length >= 11:
                outcome = "PARTIAL_LOSS"
                rounds_lost = length - 10  # Number of losing bets
            else:
                outcome = "WIN"
                rounds_lost = 0

            outcomes.append(
                {
                    "streak_length": int(length),
                    "outcome": outcome,
                    "rounds_lost": int(rounds_lost),
                    "session_id": int(streak["session_id"]),
                    "start_time": streak["start_time"].isoformat(),
                }
            )

        return {
            "total_triggers": len(trigger_streaks),
            "catastrophic_events": len(catastrophic_streaks),
            "partial_loss_events": len(partial_loss_streaks),
            "win_events": len(trigger_streaks)
            - len(partial_loss_streaks)
            - len(catastrophic_streaks),
            "outcomes": outcomes,
            "catastrophic_details": [
                {
                    "length": int(s["length"]),
                    "session_id": int(s["session_id"]),
                    "start_time": s["start_time"].isoformat(),
                    "end_time": s["end_time"].isoformat(),
                }
                for s in catastrophic_streaks
            ],
        }

    def generate_report(self) -> dict:
        """Generate comprehensive analysis report"""
        print("Loading data...")
        df = self.load_data()

        if len(df) == 0:
            return {"error": "No data found in database"}

        print(f"Loaded {len(df)} rounds")

        print("Detecting sessions...")
        df = self.detect_sessions(df)

        print("Finding streaks...")
        streaks = self.find_streaks(df)

        print("Analyzing streaks...")
        streak_analysis = self.analyze_streaks(streaks)

        print("Calculating session statistics...")
        session_stats = self.session_statistics(df)

        print("Performing risk assessment...")
        risk = self.risk_assessment(streaks)

        # Convert session stats to JSON-serializable format
        session_stats_dict = session_stats.to_dict("records")
        for session in session_stats_dict:
            if "start_time" in session and hasattr(session["start_time"], "isoformat"):
                session["start_time"] = session["start_time"].isoformat()
            if "end_time" in session and hasattr(session["end_time"], "isoformat"):
                session["end_time"] = session["end_time"].isoformat()

        return {
            "overview": {
                "total_rounds": int(len(df)),
                "total_sessions": int(df["session_id"].nunique()),
                "date_range": {
                    "start": df["timestamp"].min().isoformat(),
                    "end": df["timestamp"].max().isoformat(),
                },
                "threshold": float(self.threshold),
            },
            "streak_analysis": streak_analysis,
            "session_statistics": session_stats_dict,
            "risk_assessment": risk,
            "longest_streaks": sorted(
                [
                    {
                        "length": int(s["length"]),
                        "session_id": int(s["session_id"]),
                        "start": s["start_time"].isoformat(),
                        "end": s["end_time"].isoformat(),
                    }
                    for s in streaks
                ],
                key=lambda x: x["length"],
                reverse=True,
            )[:10],  # Top 10 longest streaks
        }

    def print_report(self, report: dict):
        """Print formatted report"""
        print("\n" + "=" * 80)
        print("CRASHER GAME DATA ANALYSIS REPORT")
        print("=" * 80)

        # Overview
        print("\nOVERVIEW:")
        print(f"  Total Rounds: {report['overview']['total_rounds']:,}")
        print(f"  Total Sessions: {report['overview']['total_sessions']}")
        print(
            f"  Date Range: {report['overview']['date_range']['start']} to {report['overview']['date_range']['end']}"
        )
        print(f"  Threshold: Under {report['overview']['threshold']}x")

        # Streak Analysis
        sa = report["streak_analysis"]
        print("\n" + "-" * 80)
        print("STREAK ANALYSIS (Consecutive rounds under 2.0x):")
        print(f"  Longest Streak: {sa['longest_streak']} consecutive rounds")
        print(f"  Total Streaks: {sa['total_streaks']}")
        print(f"  Average Streak Length: {sa['average_streak']:.2f} rounds")

        print("\n  Specific Streak Counts:")
        for length in [6, 7, 8, 9, 10]:
            count = sa["specific_counts"][length]
            print(f"    {length} consecutive rounds: {count} times")

        print("\n  Full Distribution:")
        for length in sorted(sa["streak_distribution"].keys()):
            count = sa["streak_distribution"][length]
            bar = "█" * min(count, 50)
            print(f"    {length:2d} rounds: {count:3d} times {bar}")

        # Risk Assessment
        risk = report["risk_assessment"]
        print("\n" + "-" * 80)
        print("RISK ASSESSMENT:")
        print(f"  Strategy: Wait for 10 under 2x, then martingale for 5 rounds")
        print(f"  Total Risk: 15 consecutive under 2x rounds = TOTAL LOSS")
        print(
            f"\n  Times trigger condition was met (10+ under 2x): {risk['total_triggers']}"
        )
        print(
            f"  Times you would have WON: {risk['win_events']} ({risk['win_events'] / max(risk['total_triggers'], 1) * 100:.1f}%)"
        )
        print(
            f"  Times you would have had PARTIAL LOSS: {risk['partial_loss_events']} ({risk['partial_loss_events'] / max(risk['total_triggers'], 1) * 100:.1f}%)"
        )
        print(
            f"  Times you would have had TOTAL LOSS: {risk['catastrophic_events']} ({risk['catastrophic_events'] / max(risk['total_triggers'], 1) * 100:.1f}%)"
        )

        if risk["catastrophic_events"] > 0:
            print("\n  ⚠️  CATASTROPHIC EVENTS (15+ consecutive under 2x):")
            for event in risk["catastrophic_details"]:
                print(
                    f"    - {event['length']} rounds in session {event['session_id']} ({event['start_time']})"
                )

        # Top 10 Longest Streaks
        print("\n" + "-" * 80)
        print("TOP 10 LONGEST STREAKS:")
        for i, streak in enumerate(report["longest_streaks"][:10], 1):
            print(
                f"  {i:2d}. {streak['length']} rounds (Session {streak['session_id']}) - {streak['start']}"
            )

        # Session Summary
        print("\n" + "-" * 80)
        print("SESSION SUMMARY:")
        session_df = pd.DataFrame(report["session_statistics"])
        print(f"  Total Sessions: {len(session_df)}")
        print(f"  Average Rounds per Session: {session_df['total_rounds'].mean():.1f}")
        print(
            f"  Average Session Duration: {session_df['duration_minutes'].mean():.1f} minutes"
        )
        print(
            f"  Average % Rounds Under 2x: {session_df['percentage_under_2x'].mean():.1f}%"
        )

        print("\n" + "=" * 80)

    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import sys

    db_path = "./crasher_data.db"
    threshold = 2.0

    # Parse command line arguments
    if len(sys.argv) >= 2:
        db_path = sys.argv[1]
    if len(sys.argv) >= 3:
        try:
            threshold = float(sys.argv[2])
        except ValueError:
            print(f"Invalid threshold value: {sys.argv[2]}, using default 2.0")
            threshold = 2.0

    print(f"Database: {db_path}")
    print(f"Threshold: {threshold}x")

    analyzer = CrasherAnalyzer(db_path, threshold)

    try:
        report = analyzer.generate_report()

        # Print to console
        analyzer.print_report(report)

        # Save JSON report
        json_path = "data-analyze/outputs/analysis_report.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nDetailed JSON report saved to: {json_path}")

    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
