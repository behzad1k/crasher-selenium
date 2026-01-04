#!/usr/bin/env python3
"""
Method Selectivity Analyzer
Analyzes why methods trigger too often and suggests fixes
"""

import sqlite3
import numpy as np


def analyze_method_triggers(db_path: str = "./crasher_data.db"):
    """Analyze what makes each method trigger"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*100)
    print("METHOD SELECTIVITY ANALYSIS")
    print("="*100)
    
    # Get total rounds
    cursor.execute("SELECT COUNT(*) FROM multipliers")
    total_rounds = cursor.fetchone()[0]
    
    # Get signals per round distribution
    cursor.execute("""
        SELECT 
            COUNT(*) as method_count,
            COUNT(multiplier_id) as round_count
        FROM (
            SELECT multiplier_id, COUNT(*) as method_count
            FROM signals
            GROUP BY multiplier_id
        )
        GROUP BY method_count
        ORDER BY method_count
    """)
    
    print(f"\nSIGNALS PER ROUND DISTRIBUTION:")
    print(f"{'Methods/Round':<20} {'Rounds':<15} {'%'}")
    print("-"*60)
    
    for method_count, round_count in cursor.fetchall():
        pct = (round_count / total_rounds * 100) if total_rounds > 0 else 0
        print(f"{method_count:<20} {round_count:>13,} {pct:>6.1f}%")
    
    # Analyze each method
    print(f"\n{'='*100}")
    print("METHOD-BY-METHOD ANALYSIS")
    print("="*100)
    
    cursor.execute("SELECT method_id, short_title FROM methods ORDER BY method_id")
    methods = cursor.fetchall()
    
    for method_id, method_name in methods:
        print(f"\n{'='*100}")
        print(f"METHOD {method_id}: {method_name}")
        print("="*100)
        
        # Get trigger count
        cursor.execute("""
            SELECT COUNT(DISTINCT multiplier_id)
            FROM signals
            WHERE method_id = ?
        """, (method_id,))
        
        trigger_count = cursor.fetchone()[0]
        trigger_pct = (trigger_count / total_rounds * 100) if total_rounds > 0 else 0
        
        print(f"\nTrigger Rate: {trigger_count:,}/{total_rounds:,} rounds ({trigger_pct:.1f}%)")
        
        # Get confidence distribution for this method
        cursor.execute("""
            SELECT confidence
            FROM signals
            WHERE method_id = ?
            ORDER BY confidence
        """, (method_id,))
        
        confidences = [row[0] for row in cursor.fetchall()]
        
        if confidences:
            print(f"\nConfidence Distribution:")
            print(f"  Min: {min(confidences)*100:.1f}%")
            print(f"  25th percentile: {np.percentile(confidences, 25)*100:.1f}%")
            print(f"  Median: {np.median(confidences)*100:.1f}%")
            print(f"  75th percentile: {np.percentile(confidences, 75)*100:.1f}%")
            print(f"  Max: {max(confidences)*100:.1f}%")
            
            # Suggest threshold
            if trigger_pct > 60:
                # Find confidence threshold that would give 30% trigger rate
                target_count = int(total_rounds * 0.30)
                sorted_confs = sorted(confidences, reverse=True)
                
                if len(sorted_confs) > target_count:
                    suggested_threshold = sorted_confs[target_count]
                    
                    print(f"\n💡 SUGGESTION:")
                    print(f"   Current trigger rate: {trigger_pct:.1f}%")
                    print(f"   Target trigger rate: 30%")
                    print(f"   Suggested minimum confidence: {suggested_threshold*100:.1f}%")
                    print(f"   This would reduce triggers from {trigger_count:,} to ~{target_count:,}")
                    
                    print(f"\n📝 CODE FIX:")
                    print(f"   Add this condition to Method {method_id}:")
                    print(f"   ```python")
                    print(f"   if confidence >= {suggested_threshold:.3f}:")
                    print(f"       trigger_signal()")
                    print(f"   ```")
        
        # Get prediction distribution
        cursor.execute("""
            SELECT prediction_rounds
            FROM signals
            WHERE method_id = ?
            ORDER BY prediction_rounds
        """, (method_id,))
        
        predictions = [row[0] for row in cursor.fetchall()]
        
        if predictions:
            print(f"\nPrediction Distribution:")
            print(f"  Min: {min(predictions)} rounds")
            print(f"  Median: {int(np.median(predictions))} rounds")
            print(f"  Max: {max(predictions)} rounds")
            print(f"  Mode: {max(set(predictions), key=predictions.count)} rounds")
    
    # Overall recommendations
    print(f"\n{'='*100}")
    print("OVERALL RECOMMENDATIONS")
    print("="*100)
    
    print(f"\nCurrent state:")
    print(f"  Total signals: 435,109")
    print(f"  Total rounds: {total_rounds:,}")
    print(f"  Signals/round: {435109/total_rounds:.1f}")
    
    print(f"\nTarget state:")
    print(f"  Signals/round: 2-3")
    print(f"  Total signals: ~{total_rounds*2.5:,.0f}")
    print(f"  Reduction needed: {435109 - total_rounds*2.5:,.0f} signals ({(1 - total_rounds*2.5/435109)*100:.1f}%)")
    
    print(f"\nHow to achieve:")
    print(f"  1. Add confidence thresholds to each method (see suggestions above)")
    print(f"  2. Add stricter conditions to method logic")
    print(f"  3. Target 20-40% trigger rate per method")
    print(f"  4. With 10 methods at 30% each, expect ~3 signals/round")
    
    print(f"\n{'='*100}")
    print("QUICK FIX OPTIONS")
    print("="*100)
    
    print(f"\nOption A: Filter by confidence (EASIEST)")
    print(f"  In backfill_signals.py or wherever signals are created:")
    print(f"  ```python")
    print(f"  # Only record signal if confidence meets threshold")
    print(f"  if confidence >= 0.50:  # Adjust per method")
    print(f"      record_signal(method_id, prediction, confidence)")
    print(f"  ```")
    
    print(f"\nOption B: Stricter method conditions (BETTER)")
    print(f"  Update each method's trigger logic to be more selective")
    print(f"  See per-method suggestions above")
    
    print(f"\nOption C: Combination filter (COMPROMISE)")
    print(f"  Only record signals when 2+ methods agree:")
    print(f"  ```python")
    print(f"  triggered_methods = get_triggered_methods()")
    print(f"  if len(triggered_methods) >= 2:")
    print(f"      for method in triggered_methods:")
    print(f"          record_signal(method)")
    print(f"  ```")
    
    conn.close()
    
    print(f"\n{'='*100}")
    print("✅ Analysis complete")
    print("="*100)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze method selectivity')
    parser.add_argument('--db', default='./crasher_data.db', help='Database path')
    args = parser.parse_args()
    
    analyze_method_triggers(args.db)
