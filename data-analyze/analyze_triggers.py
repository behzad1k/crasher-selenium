#!/usr/bin/env python3
"""
Consecutive Rounds BELOW Threshold Analysis Script

Analyzes consecutive rounds BELOW a threshold - useful for understanding
when trigger strategies would activate.

Usage:
    python3 analyze_triggers.py 2.0
    python3 analyze_triggers.py 3.0 --min-count 8
    python3 analyze_triggers.py 5.0 --session 5 --detailed
"""

import argparse
import sqlite3
import sys
from collections import Counter
from typing import List, Tuple


def get_multipliers(db_path: str, session_id: int = None) -> List[float]:
    """Get multipliers from database in chronological order"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if session_id:
        query = """
            SELECT multiplier 
            FROM multipliers 
            WHERE session_id = ? 
            ORDER BY id ASC
        """
        cursor.execute(query, (session_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]
        
        if session_count == 0:
            query = "SELECT multiplier FROM multipliers ORDER BY id ASC"
            cursor.execute(query)
        else:
            cursor.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1")
            session_id = cursor.fetchone()[0]
            query = """
                SELECT multiplier 
                FROM multipliers 
                WHERE session_id = ? 
                ORDER BY id ASC
            """
            cursor.execute(query, (session_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [r[0] for r in results]


def analyze_consecutive_below(multipliers: List[float], threshold: float) -> dict:
    """Analyze consecutive rounds below threshold (for trigger analysis)"""
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
        if mult < threshold:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
                current_streak = 0
    
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


def main():
    parser = argparse.ArgumentParser(
        description="Analyze consecutive rounds BELOW threshold (trigger analysis)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 2.0                    # Find streaks of rounds < 2.0x
  %(prog)s 2.0 --min-count 8      # Show how often you get 8+ rounds < 2.0x
  %(prog)s 3.0 --session 5        # Analyze specific session
  %(prog)s 5.0 --detailed         # Show detailed analysis
        """
    )
    
    parser.add_argument(
        "threshold",
        type=float,
        help="Multiplier threshold (e.g., 2.0 for rounds < 2.0x)"
    )
    
    parser.add_argument(
        "--min-count",
        type=int,
        help="Highlight streaks >= this length (e.g., your trigger_count)"
    )
    
    parser.add_argument(
        "--session",
        type=int,
        help="Analyze specific session ID"
    )
    
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)"
    )
    
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed breakdown"
    )
    
    args = parser.parse_args()
    
    # Get multipliers
    try:
        multipliers = get_multipliers(args.db, args.session)
    except Exception as e:
        print(f"ERROR: Failed to read database: {e}")
        sys.exit(1)
    
    if not multipliers:
        print(f"ERROR: No multipliers found")
        sys.exit(1)
    
    # Analyze
    analysis = analyze_consecutive_below(multipliers, args.threshold)
    
    # Print results
    print(f"\n{'='*80}")
    print(f"TRIGGER ANALYSIS: Consecutive Rounds < {args.threshold}x")
    print(f"{'='*80}")
    print(f"Database: {args.db}")
    print(f"Session: {args.session or 'LATEST'}")
    print(f"Total Rounds: {len(multipliers)}")
    print(f"{'='*80}\n")
    
    print(f"SUMMARY:")
    print(f"  Total Streaks: {analysis['total_streaks']}")
    print(f"  Longest Streak: {analysis['max_streak']} rounds")
    print(f"  Average Streak: {analysis['avg_streak']:.2f} rounds")
    print()
    
    # Trigger-specific analysis
    if args.min_count:
        trigger_streaks = [s for s in analysis['streaks'] if s >= args.min_count]
        trigger_pct = (len(trigger_streaks) / len(analysis['streaks']) * 100) if analysis['streaks'] else 0
        
        print(f"TRIGGER OPPORTUNITIES (>= {args.min_count} rounds):")
        print(f"  Count: {len(trigger_streaks)} times")
        print(f"  Percentage: {trigger_pct:.2f}% of all streaks")
        
        if trigger_streaks:
            avg_trigger = sum(trigger_streaks) / len(trigger_streaks)
            print(f"  Average length: {avg_trigger:.2f} rounds")
            print(f"  Max length: {max(trigger_streaks)} rounds")
            
            # Estimate frequency
            total_rounds = len(multipliers)
            rounds_between = total_rounds / len(trigger_streaks) if trigger_streaks else 0
            print(f"  Frequency: Every ~{rounds_between:.1f} rounds")
        print()
    
    # Distribution
    if args.detailed:
        print(f"STREAK DISTRIBUTION:")
        max_streak = analysis['max_streak']
        
        for length in range(1, min(max_streak + 1, 31)):
            count = analysis['distribution'].get(length, 0)
            pct = (count / analysis['total_streaks'] * 100) if analysis['total_streaks'] > 0 else 0
            bar = "█" * int(pct / 2)  # Scale to 50 chars max
            
            marker = ""
            if args.min_count and length == args.min_count:
                marker = " ← YOUR TRIGGER"
            
            print(f"  {length:3d} rounds: {bar:25s} {count:4d} ({pct:5.1f}%){marker}")
        
        if max_streak > 30:
            remaining = sum(count for l, count in analysis['distribution'].items() if l > 30)
            print(f"  31+ rounds: {remaining:4d}")
        print()
    else:
        # Compact distribution
        print(f"TOP STREAK LENGTHS:")
        for length, count in analysis['distribution'].most_common(10):
            pct = (count / analysis['total_streaks'] * 100) if analysis['total_streaks'] > 0 else 0
            marker = " ← YOUR TRIGGER" if args.min_count and length == args.min_count else ""
            print(f"  {length:3d} rounds: {count:4d} times ({pct:5.1f}%){marker}")
        print()
    
    # Strategy recommendation
    if analysis['max_streak'] >= 5:
        print(f"STRATEGY RECOMMENDATIONS:")
        
        # Find optimal trigger counts
        cumulative = 0
        optimal_triggers = []
        
        for length in sorted(analysis['distribution'].keys(), reverse=True):
            cumulative += analysis['distribution'][length]
            coverage = (cumulative / analysis['total_streaks'] * 100)
            
            if length <= 30 and coverage >= 20 and coverage <= 80:
                optimal_triggers.append((length, coverage))
        
        if optimal_triggers:
            print(f"  Suggested trigger_count values:")
            for trigger_len, coverage in sorted(optimal_triggers)[:5]:
                print(f"    {trigger_len:2d} rounds: Would trigger {coverage:.1f}% of the time")
        
        print()
    
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
