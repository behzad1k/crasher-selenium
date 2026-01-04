#!/usr/bin/env python3
"""
Add Prediction Timing to Combinations Table
Calculates and saves how many rounds ahead each combination predicts
"""

import sqlite3
import json
import sys
from collections import Counter


def add_timing_columns(db_path: str = "./crasher_data.db"):
    """Add timing-related columns to combinations table"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*80)
    print("ADDING TIMING COLUMNS TO COMBINATIONS TABLE")
    print("="*80)
    
    # Check if columns already exist
    cursor.execute("PRAGMA table_info(combinations)")
    columns = [col[1] for col in cursor.fetchall()]
    
    new_columns = [
        ('avg_predicted_rounds', 'REAL', 'Average rounds until hot streak (predicted)'),
        ('avg_actual_rounds', 'REAL', 'Average rounds until hot streak (actual)'),
        ('prediction_mode', 'TEXT', 'Most common prediction range (e.g., "6-10 rounds")'),
        ('prediction_accuracy_in_range', 'REAL', 'Accuracy within the predicted range'),
        ('earliest_prediction', 'INTEGER', 'Earliest prediction seen'),
        ('latest_prediction', 'INTEGER', 'Latest prediction seen'),
        ('median_prediction', 'REAL', 'Median prediction'),
    ]
    
    added_count = 0
    
    for col_name, col_type, description in new_columns:
        if col_name not in columns:
            cursor.execute(f"""
                ALTER TABLE combinations
                ADD COLUMN {col_name} {col_type}
            """)
            print(f"  ✓ Added column: {col_name} ({description})")
            added_count += 1
        else:
            print(f"  ⊘ Column exists: {col_name}")
    
    conn.commit()
    
    if added_count > 0:
        print(f"\n✅ Added {added_count} new columns")
    else:
        print(f"\n✅ All columns already exist")
    
    conn.close()


def calculate_timing_stats(db_path: str = "./crasher_data.db", 
                          json_file: str = "combination_results.json"):
    """Calculate timing statistics for all combinations"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("CALCULATING TIMING STATISTICS")
    print("="*80)
    
    # Get all combinations from database
    cursor.execute("""
        SELECT combo_id, method_ids, short_name
        FROM combinations
        ORDER BY combo_id
    """)
    
    combinations = cursor.fetchall()
    print(f"\nFound {len(combinations)} combinations in database")
    
    updated_count = 0
    
    for combo_id, method_ids_str, short_name in combinations:
        method_ids = [int(m) for m in method_ids_str.split(',')]
        placeholders = ','.join('?' * len(method_ids))
        
        # Get all multipliers where this exact combination triggered
        # First, find multipliers with all required methods
        cursor.execute(f"""
            SELECT DISTINCT s.multiplier_id
            FROM signals s
            WHERE s.method_id IN ({placeholders})
            GROUP BY s.multiplier_id
            HAVING COUNT(DISTINCT s.method_id) = ?
        """, method_ids + [len(method_ids)])
        
        combo_multipliers = [row[0] for row in cursor.fetchall()]
        
        if not combo_multipliers:
            print(f"  [{combo_id}] {short_name}: No occurrences")
            continue
        
        # Now get predictions for these specific multipliers
        mult_placeholders = ','.join('?' * len(combo_multipliers))
        
        cursor.execute(f"""
            SELECT 
                sig.multiplier_id,
                AVG(sfc.predicted_rounds) as avg_pred,
                AVG(sfc.actual_rounds) as avg_actual,
                AVG(sfc.confidence) as avg_conf
            FROM signal_fact_check sfc
            JOIN signals sig ON sfc.signal_id = sig.id
            WHERE sfc.method_id IN ({placeholders})
              AND sig.multiplier_id IN ({mult_placeholders})
            GROUP BY sig.multiplier_id
            HAVING COUNT(DISTINCT sfc.method_id) = ?
        """, method_ids + combo_multipliers + [len(method_ids)])
        
        predictions = cursor.fetchall()
        
        if not predictions:
            print(f"  [{combo_id}] {short_name}: No data")
            continue
        
        # Calculate statistics
        pred_values = [int(round(p[1])) for p in predictions if p[1] is not None]
        actual_values = [p[2] for p in predictions if p[2] is not None]
        
        if not pred_values:
            print(f"  [{combo_id}] {short_name}: No valid predictions")
            continue
        
        # Basic stats
        avg_predicted = sum(p[1] for p in predictions if p[1]) / len(predictions)
        avg_actual = sum(actual_values) / len(actual_values) if actual_values else None
        
        earliest = min(pred_values)
        latest = max(pred_values)
        
        # Median
        sorted_preds = sorted(pred_values)
        n = len(sorted_preds)
        median = (sorted_preds[n//2] if n % 2 == 1 
                 else (sorted_preds[n//2-1] + sorted_preds[n//2]) / 2)
        
        # Most common range
        ranges = {
            '0-5 rounds': (0, 5),
            '6-10 rounds': (6, 10),
            '11-15 rounds': (11, 15),
            '16-20 rounds': (16, 20),
            '21-30 rounds': (21, 30),
            '31+ rounds': (31, 999)
        }
        
        range_counts = Counter()
        range_accuracy = {}
        
        for pred_val, actual_val in zip([p[1] for p in predictions], actual_values):
            if pred_val is None:
                continue
            
            pred_int = int(round(pred_val))
            
            for range_name, (min_val, max_val) in ranges.items():
                if min_val <= pred_int <= max_val:
                    range_counts[range_name] += 1
                    
                    # Track accuracy in this range
                    if range_name not in range_accuracy:
                        range_accuracy[range_name] = []
                    
                    if actual_val is not None:
                        margin = abs(actual_val - pred_val)
                        range_accuracy[range_name].append(margin <= 10)
                    break
        
        # Get most common range
        if range_counts:
            prediction_mode = range_counts.most_common(1)[0][0]
            mode_accuracy = (sum(range_accuracy[prediction_mode]) / 
                           len(range_accuracy[prediction_mode]) * 100
                           if prediction_mode in range_accuracy else None)
        else:
            prediction_mode = None
            mode_accuracy = None
        
        # Update database
        cursor.execute("""
            UPDATE combinations
            SET avg_predicted_rounds = ?,
                avg_actual_rounds = ?,
                prediction_mode = ?,
                prediction_accuracy_in_range = ?,
                earliest_prediction = ?,
                latest_prediction = ?,
                median_prediction = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE combo_id = ?
        """, (avg_predicted, avg_actual, prediction_mode, mode_accuracy,
              earliest, latest, median, combo_id))
        
        print(f"  [{combo_id:3}] {short_name:<25} "
              f"Avg: {avg_predicted:>5.1f}r | Mode: {prediction_mode or 'N/A':<15} | "
              f"Accuracy: {mode_accuracy:.1f}%" if mode_accuracy else "N/A")
        
        updated_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n{'='*80}")
    print(f"✅ Updated {updated_count} combinations with timing data")
    print("="*80)


def display_timing_report(db_path: str = "./crasher_data.db"):
    """Display timing report from database"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("COMBINATION TIMING REPORT")
    print("="*80)
    
    cursor.execute("""
        SELECT 
            combo_id,
            short_name,
            actual_accuracy,
            avg_predicted_rounds,
            avg_actual_rounds,
            prediction_mode,
            prediction_accuracy_in_range,
            earliest_prediction,
            latest_prediction,
            median_prediction,
            checked_occurrences
        FROM combinations
        WHERE avg_predicted_rounds IS NOT NULL
        ORDER BY actual_accuracy DESC
        LIMIT 30
    """)
    
    print(f"\n{'#':<5} {'Combo':<25} {'Acc':<8} {'Avg Pred':<10} {'Mode':<18} "
          f"{'Mode Acc':<10} {'Range'}")
    print("-"*100)
    
    for row in cursor.fetchall():
        (combo_id, short_name, accuracy, avg_pred, avg_actual, pred_mode, 
         mode_acc, earliest, latest, median, checked) = row
        
        range_str = f"{earliest}-{latest}r" if earliest and latest else "N/A"
        mode_acc_str = f"{mode_acc:.1f}%" if mode_acc else "N/A"
        
        print(f"{combo_id:<5} {short_name:<25} {accuracy:>6.1f}% {avg_pred:>9.1f}r "
              f"{pred_mode or 'N/A':<18} {mode_acc_str:<10} {range_str}")
    
    # Summary by prediction mode
    print("\n" + "="*80)
    print("SUMMARY BY PREDICTION MODE")
    print("="*80)
    
    cursor.execute("""
        SELECT 
            prediction_mode,
            COUNT(*) as count,
            AVG(actual_accuracy) as avg_accuracy,
            AVG(avg_predicted_rounds) as avg_pred,
            AVG(checked_occurrences) as avg_checks
        FROM combinations
        WHERE prediction_mode IS NOT NULL
        GROUP BY prediction_mode
        ORDER BY avg_accuracy DESC
    """)
    
    print(f"\n{'Prediction Mode':<20} {'Count':<8} {'Avg Acc':<10} "
          f"{'Avg Pred':<12} {'Avg Checks'}")
    print("-"*70)
    
    for mode, count, avg_acc, avg_pred, avg_checks in cursor.fetchall():
        print(f"{mode:<20} {count:<8} {avg_acc:>8.1f}% {avg_pred:>10.1f}r {avg_checks:>12,.0f}")
    
    # Practical guide
    print("\n" + "="*80)
    print("PRACTICAL BETTING GUIDE (Based on Timing Data)")
    print("="*80)
    
    cursor.execute("""
        SELECT 
            short_name,
            actual_accuracy,
            avg_predicted_rounds,
            avg_actual_rounds,
            prediction_mode
        FROM combinations
        WHERE actual_accuracy >= 65
        ORDER BY actual_accuracy DESC
        LIMIT 10
    """)
    
    print(f"\nTop 10 Combinations:")
    print(f"\n{'Combo':<25} {'Accuracy':<10} {'Predicts':<12} {'Actually':<12} {'When to Bet'}")
    print("-"*90)
    
    for short_name, accuracy, avg_pred, avg_actual, pred_mode in cursor.fetchall():
        if avg_pred:
            if avg_pred <= 5:
                when = "Bet NOW (0-5r)"
            elif avg_pred <= 10:
                when = "Start immediately"
            elif avg_pred <= 15:
                when = f"Start round {int(avg_pred-5)}"
            else:
                when = f"Wait to round {int(avg_pred-8)}"
        else:
            when = "N/A"
        
        actual_str = f"{avg_actual:.1f}r" if avg_actual else "N/A"
        
        print(f"{short_name:<25} {accuracy:>8.1f}% {avg_pred:>10.1f}r {actual_str:>10} {when}")
    
    conn.close()
    
    print("\n" + "="*80)
    print("✅ Report complete!")
    print("="*80)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Add prediction timing to combinations table'
    )
    parser.add_argument(
        '--db',
        default='./crasher_data.db',
        help='Database path (default: ./crasher_data.db)'
    )
    parser.add_argument(
        '--json',
        default='combination_results.json',
        help='JSON results file (default: combination_results.json)'
    )
    parser.add_argument(
        '--skip-columns',
        action='store_true',
        help='Skip adding columns (if already added)'
    )
    
    args = parser.parse_args()
    
    try:
        # Add columns
        if not args.skip_columns:
            add_timing_columns(args.db)
        
        # Calculate and save timing stats
        calculate_timing_stats(args.db, args.json)
        
        # Display report
        display_timing_report(args.db)
        
        print("\n✅ All timing data saved to combinations table!")
        print("\nNew columns added:")
        print("  - avg_predicted_rounds: Average predicted rounds until hot streak")
        print("  - avg_actual_rounds: Average actual rounds until hot streak")
        print("  - prediction_mode: Most common range (e.g., '6-10 rounds')")
        print("  - prediction_accuracy_in_range: Accuracy within that range")
        print("  - earliest_prediction: Minimum prediction seen")
        print("  - latest_prediction: Maximum prediction seen")
        print("  - median_prediction: Median prediction value")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
