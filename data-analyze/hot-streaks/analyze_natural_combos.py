#!/usr/bin/env python3
"""
Quick Combo Analyzer - See what combinations naturally occur most in your data
This helps identify which combinations are worth testing
"""

import sqlite3
import sys
from collections import Counter


def analyze_natural_combinations(db_path: str = "./crasher_data.db", min_methods: int = 2, max_methods: int = 3):
    """Analyze which combinations naturally occur in the data"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*80)
    print("NATURAL COMBINATION FREQUENCY ANALYSIS")
    print("="*80)
    
    # Get all method combinations from signals
    cursor.execute("""
        SELECT 
            GROUP_CONCAT(method_id ORDER BY method_id) as combo,
            COUNT(*) as occurrences
        FROM signals
        GROUP BY multiplier_id
        HAVING COUNT(*) >= ? AND COUNT(*) <= ?
    """, (min_methods, max_methods))
    
    combo_counter = Counter()
    
    for combo, count in cursor.fetchall():
        combo_counter[combo] += 1
    
    total_combos = sum(combo_counter.values())
    
    print(f"\nTotal multipliers with {min_methods}-{max_methods} methods: {total_combos:,}")
    print(f"Unique combinations: {len(combo_counter):,}")
    
    # Top combinations
    print(f"\n{'='*80}")
    print(f"TOP 30 MOST FREQUENT COMBINATIONS")
    print("="*80)
    
    print(f"\n{'Rank':<6} {'Combo':<25} {'Occurrences':<15} {'%':<8} {'Size'}")
    print("-"*80)
    
    for rank, (combo, count) in enumerate(combo_counter.most_common(30), 1):
        percentage = (count / total_combos * 100) if total_combos > 0 else 0
        combo_formatted = '+'.join([f"M{m}" for m in combo.split(',')])
        size = len(combo.split(','))
        print(f"{rank:<6} {combo_formatted:<25} {count:<15,} {percentage:>6.1f}% {size}")
    
    # Breakdown by size
    print(f"\n{'='*80}")
    print("BREAKDOWN BY SIZE")
    print("="*80)
    
    by_size = {}
    for combo, count in combo_counter.items():
        size = len(combo.split(','))
        if size not in by_size:
            by_size[size] = []
        by_size[size].append((combo, count))
    
    for size in sorted(by_size.keys()):
        combos = by_size[size]
        total = sum(c[1] for c in combos)
        avg = total / len(combos) if combos else 0
        top = max(combos, key=lambda x: x[1])
        top_formatted = '+'.join([f"M{m}" for m in top[0].split(',')])
        
        print(f"\n{size}-Method Combinations:")
        print(f"  Unique combinations: {len(combos):,}")
        print(f"  Total occurrences: {total:,}")
        print(f"  Average per combo: {avg:.0f}")
        print(f"  Most frequent: {top_formatted} ({top[1]:,} times)")
    
    # Method frequency
    print(f"\n{'='*80}")
    print("METHOD FREQUENCY IN TOP 30")
    print("="*80)
    
    method_counts = {}
    for combo, count in combo_counter.most_common(30):
        for method in combo.split(','):
            method_id = int(method)
            method_counts[method_id] = method_counts.get(method_id, 0) + 1
    
    cursor.execute("SELECT method_id, short_title FROM methods ORDER BY method_id")
    method_names = {m_id: name for m_id, name in cursor.fetchall()}
    
    print(f"\n{'Method':<8} {'Frequency':<12} {'%'}")
    print("-"*40)
    
    for method_id in sorted(method_counts.keys(), key=lambda x: method_counts[x], reverse=True):
        freq = method_counts[method_id]
        pct = (freq / 30 * 100)
        name = method_names.get(method_id, f"M{method_id}")
        print(f"{name:<8} {freq:>10}/30 {pct:>6.0f}%")
    
    # Suggestions
    print(f"\n{'='*80}")
    print("TESTING SUGGESTIONS")
    print("="*80)
    
    print("\nBased on frequency, these combinations appear most often:")
    print("(Worth testing for accuracy)")
    
    for rank, (combo, count) in enumerate(combo_counter.most_common(10), 1):
        combo_formatted = '+'.join([f"M{m}" for m in combo.split(',')])
        print(f"  {rank}. {combo_formatted:<20} ({count:,} occurrences)")
    
    conn.close()
    
    print("\n" + "="*80)
    print("✅ Analysis complete")
    print("="*80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Analyze natural combination frequencies'
    )
    parser.add_argument(
        '--db',
        default='./crasher_data.db',
        help='Path to database (default: ./crasher_data.db)'
    )
    parser.add_argument(
        '--min-methods',
        type=int,
        default=2,
        help='Minimum methods in combo (default: 2)'
    )
    parser.add_argument(
        '--max-methods',
        type=int,
        default=3,
        help='Maximum methods in combo (default: 3)'
    )
    
    args = parser.parse_args()
    
    analyze_natural_combinations(args.db, args.min_methods, args.max_methods)
