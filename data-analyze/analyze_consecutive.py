#!/usr/bin/env python3
"""
Consecutive Rounds Analysis Script

Analyzes how many consecutive rounds above a threshold occur in the database
and how frequently they happen.

Usage:
    python3 analyze_consecutive.py 2.0
    python3 analyze_consecutive.py 3.0 --session 5
    python3 analyze_consecutive.py 5.0 --all-sessions
    python3 analyze_consecutive.py 2.0 --detailed
"""

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from typing import List, Tuple


def get_multipliers(db_path: str, session_id: int = None) -> List[Tuple[float, str]]:
    """
    Get multipliers from database
    Returns list of (multiplier, timestamp) tuples in chronological order
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if session_id:
        # Specific session
        query = """
            SELECT multiplier, timestamp
            FROM multipliers
            WHERE session_id = ?
            ORDER BY id ASC
        """
        cursor.execute(query, (session_id,))
    else:
        # All sessions (or latest if only one exists)
        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]

        if session_count == 0:
            # No sessions, get all multipliers
            query = "SELECT multiplier, timestamp FROM multipliers ORDER BY id ASC"
            cursor.execute(query)
        else:
            # Get latest session
            cursor.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1")
            session_id = cursor.fetchone()[0]
            query = """
                SELECT multiplier, timestamp
                FROM multipliers
                WHERE session_id = ?
                ORDER BY id ASC
            """
            cursor.execute(query, (session_id,))

    results = cursor.fetchall()
    conn.close()

    return results


def analyze_consecutive_above(multipliers: List[float], threshold: float) -> dict:
    """
    Analyze consecutive rounds above threshold

    Returns dict with:
        - streaks: List of streak lengths
        - max_streak: Longest streak
        - avg_streak: Average streak length
        - total_streaks: Number of streaks found
        - frequency: Streaks per 100 rounds
        - distribution: Counter of streak lengths
    """
    if not multipliers:
        return {
            "streaks": [],
            "max_streak": 0,
            "avg_streak": 0,
            "total_streaks": 0,
            "frequency": 0,
            "distribution": Counter(),
        }

    streaks = []
    current_streak = 0

    for mult in multipliers:
        if mult >= threshold:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
                current_streak = 0

    # Don't forget the last streak if it's still ongoing
    if current_streak > 0:
        streaks.append(current_streak)

    total_rounds = len(multipliers)
    total_streaks = len(streaks)

    return {
        "streaks": streaks,
        "max_streak": max(streaks) if streaks else 0,
        "avg_streak": sum(streaks) / len(streaks) if streaks else 0,
        "total_streaks": total_streaks,
        "frequency": (total_streaks / total_rounds * 100) if total_rounds > 0 else 0,
        "distribution": Counter(streaks),
    }


def format_distribution(distribution: Counter, max_display: int = 20) -> str:
    """Format distribution as a bar chart"""
    if not distribution:
        return "No data"

    lines = []
    max_count = max(distribution.values())
    max_streak = max(distribution.keys())

    # Determine bar width (50 chars max)
    bar_scale = 50 / max_count if max_count > 0 else 1

    for streak_len in sorted(distribution.keys()):
        if streak_len > max_display:
            continue

        count = distribution[streak_len]
        bar_length = int(count * bar_scale)
        bar = "█" * bar_length

        lines.append(f"  {streak_len:3d} rounds: {bar} {count}")

    if max_streak > max_display:
        remaining = sum(
            count for length, count in distribution.items() if length > max_display
        )
        lines.append(f"  {max_display + 1}+ rounds: (combined) {remaining}")

    return "\n".join(lines)


def print_detailed_streaks(
    multipliers: List[float],
    timestamps: List[str],
    threshold: float,
    max_show: int = 10,
):
    """Print detailed information about each streak"""
    print(f"\n{'=' * 80}")
    print(f"DETAILED STREAK ANALYSIS (showing up to {max_show} longest streaks)")
    print(f"{'=' * 80}\n")

    streaks_with_info = []
    current_streak = []
    current_indices = []

    for i, mult in enumerate(multipliers):
        if mult >= threshold:
            current_streak.append(mult)
            current_indices.append(i)
        else:
            if current_streak:
                start_idx = current_indices[0]
                end_idx = current_indices[-1]
                streaks_with_info.append(
                    {
                        "length": len(current_streak),
                        "multipliers": current_streak[:],
                        "start_time": timestamps[start_idx]
                        if start_idx < len(timestamps)
                        else "N/A",
                        "end_time": timestamps[end_idx]
                        if end_idx < len(timestamps)
                        else "N/A",
                        "start_idx": start_idx,
                        "end_idx": end_idx,
                        "max": max(current_streak),
                        "min": min(current_streak),
                        "avg": sum(current_streak) / len(current_streak),
                    }
                )
                current_streak = []
                current_indices = []

    # Don't forget the last streak
    if current_streak:
        start_idx = current_indices[0]
        end_idx = current_indices[-1]
        streaks_with_info.append(
            {
                "length": len(current_streak),
                "multipliers": current_streak[:],
                "start_time": timestamps[start_idx]
                if start_idx < len(timestamps)
                else "N/A",
                "end_time": timestamps[end_idx] if end_idx < len(timestamps) else "N/A",
                "start_idx": start_idx,
                "end_idx": end_idx,
                "max": max(current_streak),
                "min": min(current_streak),
                "avg": sum(current_streak) / len(current_streak),
            }
        )

    # Sort by length (longest first)
    streaks_with_info.sort(key=lambda x: x["length"], reverse=True)

    for i, streak in enumerate(streaks_with_info[:max_show], 1):
        print(f"Streak #{i}: {streak['length']} consecutive rounds")
        print(f"  Time: {streak['start_time']} to {streak['end_time']}")
        print(f"  Rounds: #{streak['start_idx'] + 1} to #{streak['end_idx'] + 1}")
        print(
            f"  Stats: Min={streak['min']:.2f}x, Max={streak['max']:.2f}x, Avg={streak['avg']:.2f}x"
        )

        # Show multipliers (up to 20)
        if len(streak["multipliers"]) <= 20:
            mult_str = ", ".join(f"{m:.2f}x" for m in streak["multipliers"])
            print(f"  Values: {mult_str}")
        else:
            first_10 = ", ".join(f"{m:.2f}x" for m in streak["multipliers"][:10])
            last_10 = ", ".join(f"{m:.2f}x" for m in streak["multipliers"][-10:])
            print(f"  Values: {first_10} ... {last_10}")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze consecutive rounds above a threshold multiplier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 2.0                    # Analyze rounds above 2.0x (latest session)
  %(prog)s 3.0 --session 5        # Analyze session #5 for rounds above 3.0x
  %(prog)s 5.0 --all-sessions     # Analyze all sessions combined
  %(prog)s 2.0 --detailed         # Show detailed streak information
  %(prog)s 2.0 --db custom.db     # Use custom database file
        """,
    )

    parser.add_argument(
        "threshold",
        type=float,
        help="Multiplier threshold (e.g., 2.0 for rounds >= 2.0x)",
    )

    parser.add_argument("--session", type=int, help="Analyze specific session ID")

    parser.add_argument(
        "--all-sessions", action="store_true", help="Analyze all sessions combined"
    )

    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)",
    )

    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed information about each streak",
    )

    parser.add_argument(
        "--max-show",
        type=int,
        default=10,
        help="Maximum number of streaks to show in detailed mode (default: 10)",
    )

    args = parser.parse_args()

    # Validate threshold
    if args.threshold < 1.0:
        print(f"ERROR: Threshold must be >= 1.0 (got {args.threshold})")
        sys.exit(1)

    # Get multipliers from database
    try:
        if args.all_sessions:
            conn = sqlite3.connect(args.db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT multiplier, timestamp FROM multipliers ORDER BY id ASC"
            )
            results = cursor.fetchall()
            conn.close()
            session_id = "ALL"
        else:
            results = get_multipliers(args.db, args.session)
            session_id = args.session or "LATEST"
    except Exception as e:
        print(f"ERROR: Failed to read database: {e}")
        sys.exit(1)

    if not results:
        print(f"ERROR: No multipliers found in database")
        sys.exit(1)

    multipliers = [r[0] for r in results]
    timestamps = [r[1] for r in results]

    # Analyze
    analysis = analyze_consecutive_above(multipliers, args.threshold)

    # Print results
    print(f"\n{'=' * 80}")
    print(f"CONSECUTIVE ROUNDS ANALYSIS")
    print(f"{'=' * 80}")
    print(f"Database: {args.db}")
    print(f"Session: {session_id}")
    print(f"Threshold: >= {args.threshold}x")
    print(f"Total Rounds: {len(multipliers)}")
    print(f"{'=' * 80}\n")

    print(f"SUMMARY:")
    print(f"  Total Streaks Found: {analysis['total_streaks']}")
    print(f"  Longest Streak: {analysis['max_streak']} consecutive rounds")
    print(f"  Average Streak: {analysis['avg_streak']:.2f} rounds")
    print(f"  Frequency: {analysis['frequency']:.2f}% of rounds start a streak")
    print()

    # Calculate additional stats
    total_above = sum(analysis["streaks"])
    pct_above = (total_above / len(multipliers) * 100) if multipliers else 0

    print(f"COVERAGE:")
    print(f"  Total Rounds >= {args.threshold}x: {total_above} ({pct_above:.1f}%)")
    print(
        f"  Total Rounds < {args.threshold}x: {len(multipliers) - total_above} ({100 - pct_above:.1f}%)"
    )
    print()

    print(f"DISTRIBUTION:")
    print(format_distribution(analysis["distribution"]))
    print()

    # Streak occurrence intervals
    if len(analysis["streaks"]) > 1:
        # Calculate how many rounds between streaks
        streak_positions = []
        current_pos = 0
        current_streak = 0

        for mult in multipliers:
            if mult >= args.threshold:
                current_streak += 1
            else:
                if current_streak > 0:
                    streak_positions.append(current_pos - current_streak + 1)
                    current_streak = 0
            current_pos += 1

        if len(streak_positions) > 1:
            intervals = [
                streak_positions[i + 1] - streak_positions[i]
                for i in range(len(streak_positions) - 1)
            ]

            avg_interval = sum(intervals) / len(intervals) if intervals else 0
            min_interval = min(intervals) if intervals else 0
            max_interval = max(intervals) if intervals else 0

            print(f"STREAK INTERVALS:")
            print(f"  Average rounds between streaks: {avg_interval:.1f}")
            print(f"  Minimum interval: {min_interval} rounds")
            print(f"  Maximum interval: {max_interval} rounds")
            print()

    # Probability estimation
    if len(multipliers) >= 100:
        print(f"PROBABILITY ESTIMATION:")
        print(f"  P(next round >= {args.threshold}x) ≈ {pct_above:.1f}%")

        if analysis["total_streaks"] > 0:
            expected_streak = analysis["avg_streak"]
            print(f"  Expected streak length: {expected_streak:.2f} rounds")
            print(f"  Longest observed: {analysis['max_streak']} rounds")

            # Probability of specific streak lengths
            print(f"\n  Probability of streak lengths:")
            for length in sorted(set([2, 5, 10, 15, 20, analysis["max_streak"]])):
                if length <= analysis["max_streak"]:
                    count = analysis["distribution"].get(length, 0)
                    prob = (
                        (count / analysis["total_streaks"] * 100)
                        if analysis["total_streaks"] > 0
                        else 0
                    )
                    print(f"    {length} rounds: {prob:.2f}% ({count} occurrences)")
        print()

    # Detailed analysis
    if args.detailed and analysis["streaks"]:
        print_detailed_streaks(multipliers, timestamps, args.threshold, args.max_show)

    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
