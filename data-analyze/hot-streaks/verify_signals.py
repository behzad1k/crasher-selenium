#!/usr/bin/env python3
"""
Verify Signals - Check backfilled signal data
Analyzes the signals table and shows interesting patterns
"""

import sqlite3
import sys
from collections import defaultdict


def verify_signals(db_path: str = "./crasher_data.db"):
    """Verify and analyze signals in database"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 80)
    print("SIGNAL VERIFICATION REPORT")
    print("=" * 80)
    
    # Check if signals table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='signals'
    """)
    
    if not cursor.fetchone():
        print("\n❌ ERROR: Signals table does not exist!")
        print("Run the bot once or manually create the table.")
        return
    
    # Total signals
    cursor.execute("SELECT COUNT(*) FROM signals")
    total_signals = cursor.fetchone()[0]
    
    print(f"\n📊 Total Signals: {total_signals:,}")
    
    if total_signals == 0:
        print("\n⚠️  No signals found! Run backfill_signals.py to generate signals.")
        return
    
    # Signals by method
    print("\n" + "=" * 80)
    print("SIGNALS BY METHOD")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            method_id,
            method_name,
            COUNT(*) as signal_count,
            AVG(confidence) * 100 as avg_confidence,
            AVG(prediction_rounds) as avg_prediction,
            MIN(prediction_rounds) as min_prediction,
            MAX(prediction_rounds) as max_prediction
        FROM signals
        GROUP BY method_id, method_name
        ORDER BY method_id
    """)
    
    print(f"\n{'ID':<4} {'Method':<25} {'Signals':<10} {'Avg Conf':<10} {'Avg Pred':<10} {'Range'}")
    print("-" * 80)
    
    for row in cursor.fetchall():
        method_id, name, count, conf, avg_pred, min_pred, max_pred = row
        print(f"M{method_id:<3} {name:<25} {count:<10,} {conf:>6.1f}% {avg_pred:>9.1f}r {min_pred:.0f}-{max_pred:.0f}r")
    
    # Signals by session
    print("\n" + "=" * 80)
    print("SIGNALS BY SESSION")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            m.session_id,
            COUNT(DISTINCT s.id) as signal_count,
            COUNT(DISTINCT s.multiplier_id) as rounds_with_signals,
            COUNT(DISTINCT m.id) as total_rounds
        FROM signals s
        JOIN multipliers m ON s.multiplier_id = m.id
        GROUP BY m.session_id
        ORDER BY m.session_id
    """)
    
    print(f"\n{'Session':<10} {'Signals':<10} {'Rounds w/Signals':<18} {'Total Rounds':<15} {'Coverage'}")
    print("-" * 80)
    
    for row in cursor.fetchall():
        session_id, signals, rounds_with_signals, total_rounds = row
        coverage = (rounds_with_signals / total_rounds * 100) if total_rounds > 0 else 0
        print(f"#{session_id:<9} {signals:<10,} {rounds_with_signals:<18,} {total_rounds:<15,} {coverage:>6.1f}%")
    
    # High confidence signals
    print("\n" + "=" * 80)
    print("HIGH CONFIDENCE SIGNALS (>70%)")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            method_name,
            COUNT(*) as count,
            AVG(prediction_rounds) as avg_prediction
        FROM signals
        WHERE confidence > 0.70
        GROUP BY method_name
        ORDER BY count DESC
    """)
    
    rows = cursor.fetchall()
    if rows:
        print(f"\n{'Method':<30} {'Count':<10} {'Avg Prediction'}")
        print("-" * 80)
        for row in rows:
            method_name, count, avg_pred = row
            print(f"{method_name:<30} {count:<10,} {avg_pred:>10.1f}r")
    else:
        print("\nNo high-confidence signals found.")
    
    # Top 10 Combination appearances
    print("\n" + "=" * 80)
    print("TOP 10 COMBINATION OCCURRENCES")
    print("=" * 80)
    
    # Check which combinations appeared
    cursor.execute("""
        SELECT 
            multiplier_id,
            GROUP_CONCAT(method_id ORDER BY method_id) as method_combo
        FROM signals
        GROUP BY multiplier_id
        HAVING COUNT(*) >= 3
    """)
    
    combo_map = {
        '1,3,4,5,6': 'COMBO #1: The Champion',
        '1,4,5,6': 'COMBO #2: The Efficient (BEST)',
        '1,2,4,5': 'COMBO #3: Precision Striker',
        '3,4,5,6': 'COMBO #4: Pure Predictor',
        '2,3,4,6': 'COMBO #5: Composite Specialist',
        '1,3,4,5': 'COMBO #6: Core Four',
        '2,4,6': 'COMBO #7: Minimalist',
        '1,3,5,6': 'COMBO #8: Balanced Five',
        '1,2,4,6': 'COMBO #9: Strategic Four',
        '3,4,5': 'COMBO #10: Essential Three'
    }
    
    combo_counts = defaultdict(int)
    for row in cursor.fetchall():
        combo = row[1]
        if combo in combo_map:
            combo_counts[combo] += 1
    
    if combo_counts:
        print(f"\n{'Combination':<45} {'Occurrences'}")
        print("-" * 80)
        
        # Sort by combo number (from map)
        sorted_combos = sorted(combo_counts.items(), key=lambda x: list(combo_map.keys()).index(x[0]))
        
        total_combo_occurrences = 0
        for combo, count in sorted_combos:
            print(f"🏆 {combo_map[combo]:<43} {count:>10,}")
            total_combo_occurrences += count
        
        print("-" * 80)
        print(f"{'TOTAL TOP 10 COMBO APPEARANCES':<45} {total_combo_occurrences:>10,}")
    else:
        print("\nNo Top 10 combinations detected in the data.")
    
    # Rule of 17 occurrences
    print("\n" + "=" * 80)
    print("SPECIAL SIGNALS")
    print("=" * 80)
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM signals 
        WHERE method_name = 'Cold Streak Classifier' 
          AND details LIKE '%Rule of 17%'
    """)
    
    rule17_count = cursor.fetchone()[0]
    print(f"\n🚨 Rule of 17 Triggers: {rule17_count:,}")
    
    if rule17_count > 0:
        cursor.execute("""
            SELECT 
                s.timestamp,
                s.confidence * 100 as confidence,
                s.prediction_rounds,
                m.multiplier
            FROM signals s
            JOIN multipliers m ON s.multiplier_id = m.id
            WHERE s.method_name = 'Cold Streak Classifier'
              AND s.details LIKE '%Rule of 17%'
            ORDER BY s.timestamp DESC
            LIMIT 5
        """)
        
        print("\nMost Recent Rule of 17 Triggers:")
        print(f"{'Timestamp':<20} {'Confidence':<12} {'Prediction':<12} {'Multiplier'}")
        print("-" * 60)
        
        for row in cursor.fetchall():
            timestamp, conf, pred, mult = row
            print(f"{timestamp:<20} {conf:>6.1f}% {pred:>10.0f}r {mult:>10.2f}x")
    
    # Time range
    print("\n" + "=" * 80)
    print("TIME RANGE")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            MIN(timestamp) as first_signal,
            MAX(timestamp) as last_signal,
            COUNT(DISTINCT DATE(timestamp)) as days
        FROM signals
    """)
    
    first, last, days = cursor.fetchone()
    print(f"\nFirst Signal: {first}")
    print(f"Last Signal:  {last}")
    print(f"Days Covered: {days}")
    
    # Sample signals
    print("\n" + "=" * 80)
    print("SAMPLE SIGNALS (Most Recent)")
    print("=" * 80)
    
    cursor.execute("""
        SELECT 
            s.timestamp,
            s.method_name,
            s.prediction_rounds,
            s.confidence * 100 as confidence,
            s.details,
            m.multiplier
        FROM signals s
        JOIN multipliers m ON s.multiplier_id = m.id
        ORDER BY s.timestamp DESC
        LIMIT 10
    """)
    
    print(f"\n{'Time':<20} {'Method':<20} {'→':<2} {'Pred':<6} {'Conf':<8} {'Multiplier':<12} {'Details'}")
    print("-" * 120)
    
    for row in cursor.fetchall():
        timestamp, method, pred, conf, details, mult = row
        timestamp_short = timestamp[11:19] if len(timestamp) > 11 else timestamp
        method_short = method[:18]
        details_short = details[:40] if details else ''
        print(f"{timestamp_short:<20} {method_short:<20} → {pred:>4}r {conf:>6.1f}% {mult:>10.2f}x {details_short}")
    
    print("\n" + "=" * 80)
    print("✅ VERIFICATION COMPLETE")
    print("=" * 80)
    
    conn.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Verify signals in database'
    )
    parser.add_argument(
        '--db',
        default='./crasher_data.db',
        help='Path to database (default: ./crasher_data.db)'
    )
    
    args = parser.parse_args()
    
    try:
        verify_signals(args.db)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
