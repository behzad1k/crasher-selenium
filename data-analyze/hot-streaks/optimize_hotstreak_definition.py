#!/usr/bin/env python3
"""
Hot Streak Definition Optimizer
Tests different hot streak definitions to find optimal parameters
"""

import sqlite3
import sys


def test_hotstreak_definitions(db_path: str = "./crasher_data.db"):
    """Test various hot streak definitions"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*100)
    print("HOT STREAK DEFINITION OPTIMIZER")
    print("="*100)
    
    # Get all multipliers
    cursor.execute("SELECT multiplier FROM multipliers ORDER BY id")
    multipliers = [row[0] for row in cursor.fetchall()]
    
    total_rounds = len(multipliers)
    print(f"\nTotal rounds: {total_rounds:,}")
    
    # Test different definitions
    test_cases = [
        # (window_size, min_percentage, min_multiplier, description)
        (10, 0.65, 2.0, "Current (too easy)"),
        (12, 0.70, 2.0, "Slightly stricter"),
        (15, 0.70, 2.0, "Longer window, 70%"),
        (15, 0.75, 2.0, "Longer window, 75%"),
        (15, 0.80, 2.0, "Very strict percentage"),
        (12, 0.70, 2.5, "Higher multiplier (2.5x)"),
        (15, 0.70, 2.5, "Higher mult + longer"),
        (15, 0.75, 2.5, "Strict: 75% ≥2.5x"),
        (20, 0.65, 2.0, "Very long window"),
        (20, 0.70, 2.5, "Long + high mult"),
    ]
    
    print(f"\n{'='*100}")
    print("TESTING HOT STREAK DEFINITIONS")
    print("="*100)
    
    print(f"\n{'Definition':<35} {'Count':<10} {'%':<8} {'Avg Gap':<10} {'Med Gap':<10} {'Verdict'}")
    print("-"*100)
    
    best_option = None
    best_score = float('inf')
    
    for window_size, min_pct, min_mult, description in test_cases:
        # Detect hot streaks
        hot_streaks = []
        
        for i in range(len(multipliers) - window_size):
            window = multipliers[i:i + window_size]
            above_threshold = sum(1 for m in window if m >= min_mult)
            percentage = above_threshold / window_size
            
            if percentage >= min_pct:
                # Avoid overlapping detections
                if not hot_streaks or (i - hot_streaks[-1]) >= window_size:
                    hot_streaks.append(i)
        
        count = len(hot_streaks)
        pct_of_total = (count / total_rounds * 100) if total_rounds > 0 else 0
        
        # Calculate gaps
        if len(hot_streaks) > 1:
            gaps = [hot_streaks[i+1] - hot_streaks[i] for i in range(len(hot_streaks)-1)]
            avg_gap = sum(gaps) / len(gaps)
            med_gap = sorted(gaps)[len(gaps)//2]
        else:
            avg_gap = 0
            med_gap = 0
        
        # Determine verdict
        if avg_gap == 0:
            verdict = "❌ No streaks"
        elif avg_gap < 10:
            verdict = "❌ Too frequent"
        elif avg_gap < 20:
            verdict = "⚠️  Still frequent"
        elif avg_gap < 35:
            verdict = "✅ Good (20-35r)"
        elif avg_gap < 50:
            verdict = "✅ Very good (35-50r)"
        else:
            verdict = "⚠️  Too rare (>50r)"
        
        # Score: target 25-40 round gap
        if 20 <= avg_gap <= 50:
            score = abs(avg_gap - 30)  # Target 30
            if score < best_score:
                best_score = score
                best_option = (window_size, min_pct, min_mult, description, count, avg_gap, med_gap)
        
        desc_str = f"{description} ({window_size}r, {min_pct*100:.0f}%, ≥{min_mult}x)"
        
        print(f"{desc_str:<35} {count:>8,} {pct_of_total:>6.1f}% {avg_gap:>9.1f}r "
              f"{med_gap:>9.0f}r {verdict}")
    
    # Recommendation
    print(f"\n{'='*100}")
    print("RECOMMENDATION")
    print("="*100)
    
    if best_option:
        window, pct, mult, desc, count, avg_gap, med_gap = best_option
        
        print(f"\n🏆 BEST OPTION: {desc}")
        print(f"   Window: {window} rounds")
        print(f"   Threshold: {pct*100:.0f}% of rounds ≥ {mult}x")
        print(f"   Results: {count:,} hot streaks")
        print(f"   Average gap: {avg_gap:.1f} rounds")
        print(f"   Median gap: {med_gap:.0f} rounds")
        
        print(f"\n📝 CODE TO USE:")
        print(f"```python")
        print(f"def detect_hot_streak(multipliers, start_idx):")
        print(f"    window_size = {window}")
        print(f"    if start_idx + window_size > len(multipliers):")
        print(f"        return False")
        print(f"    ")
        print(f"    window = multipliers[start_idx:start_idx + window_size]")
        print(f"    above_threshold = sum(1 for m in window if m >= {mult})")
        print(f"    percentage = above_threshold / window_size")
        print(f"    ")
        print(f"    return percentage >= {pct}")
        print(f"```")
        
        print(f"\n⚙️  WHERE TO CHANGE:")
        print(f"   1. Open: backfill_signals.py")
        print(f"   2. Find: GameStateBuilder class")
        print(f"   3. Find: detect_next_hotstreak() or similar function")
        print(f"   4. Replace the detection logic with code above")
        
        print(f"\n🔄 AFTER CHANGING:")
        print(f"   1. Delete old signals: sqlite3 crasher_data.db 'DELETE FROM signals; DELETE FROM signal_fact_check;'")
        print(f"   2. Regenerate signals: python backfill_signals.py")
        print(f"   3. Fact-check: python fact_check_signals.py")
        print(f"   4. Retest significance: python test_significance.py")
        
    else:
        print("\n⚠️  No good option found!")
        print("   Try even stricter criteria:")
        print("   - 20 rounds with 75%+ ≥2.5x")
        print("   - 15 rounds with 80%+ ≥3.0x")
    
    # Show distribution
    if best_option:
        window, pct, mult, desc, count, avg_gap, med_gap = best_option
        
        print(f"\n{'='*100}")
        print(f"GAP DISTRIBUTION FOR RECOMMENDED OPTION")
        print("="*100)
        
        # Recalculate with best option
        hot_streaks = []
        for i in range(len(multipliers) - window):
            win = multipliers[i:i + window]
            above = sum(1 for m in win if m >= mult)
            if above / window >= pct:
                if not hot_streaks or (i - hot_streaks[-1]) >= window:
                    hot_streaks.append(i)
        
        if len(hot_streaks) > 1:
            gaps = [hot_streaks[i+1] - hot_streaks[i] for i in range(len(hot_streaks)-1)]
            
            # Histogram
            buckets = {
                '1-10r': 0,
                '11-20r': 0,
                '21-30r': 0,
                '31-40r': 0,
                '41-50r': 0,
                '51-75r': 0,
                '76-100r': 0,
                '100+r': 0,
            }
            
            for gap in gaps:
                if gap <= 10:
                    buckets['1-10r'] += 1
                elif gap <= 20:
                    buckets['11-20r'] += 1
                elif gap <= 30:
                    buckets['21-30r'] += 1
                elif gap <= 40:
                    buckets['31-40r'] += 1
                elif gap <= 50:
                    buckets['41-50r'] += 1
                elif gap <= 75:
                    buckets['51-75r'] += 1
                elif gap <= 100:
                    buckets['76-100r'] += 1
                else:
                    buckets['100+r'] += 1
            
            print(f"\n{'Range':<15} {'Count':<10} {'%':<10} {'Bar'}")
            print("-"*70)
            
            total_gaps = len(gaps)
            for range_name, cnt in buckets.items():
                pct_gaps = (cnt / total_gaps * 100) if total_gaps > 0 else 0
                bar = '█' * int(pct_gaps / 2)
                print(f"{range_name:<15} {cnt:>8,} {pct_gaps:>8.1f}% {bar}")
    
    conn.close()
    
    print(f"\n{'='*100}")
    print("✅ Analysis complete")
    print("="*100)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Optimize hot streak definition')
    parser.add_argument('--db', default='./crasher_data.db', help='Database path')
    args = parser.parse_args()
    
    test_hotstreak_definitions(args.db)
