#!/usr/bin/env python3
"""
Verify Combination Occurrences
Checks actual vs reported occurrence counts
"""

import sqlite3
import sys


def verify_occurrences(db_path: str = "./crasher_data.db"):
    """Verify combination occurrence counts"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*100)
    print("COMBINATION OCCURRENCE VERIFICATION")
    print("="*100)
    
    # Get total rounds
    cursor.execute("SELECT COUNT(*) FROM multipliers")
    total_rounds = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT multiplier_id) FROM signals")
    rounds_with_signals = cursor.fetchone()[0]
    
    print(f"\nDatabase Stats:")
    print(f"  Total rounds: {total_rounds:,}")
    print(f"  Rounds with signals: {rounds_with_signals:,}")
    print(f"  Coverage: {rounds_with_signals/total_rounds*100:.1f}%")
    
    # Check top combinations
    cursor.execute("""
        SELECT combo_id, short_name, method_ids, checked_occurrences
        FROM combinations
        WHERE combo_id >= 11
        ORDER BY actual_accuracy DESC
        LIMIT 20
    """)
    
    print(f"\n{'='*100}")
    print("TOP 20 COMBINATIONS - OCCURRENCE VERIFICATION")
    print("="*100)
    
    print(f"\n{'ID':<5} {'Combo':<25} {'Reported':<15} {'Actual':<15} {'Diff':<10} {'%'}")
    print("-"*100)
    
    for combo_id, short_name, method_ids_str, reported_count in cursor.fetchall():
        method_ids = [int(m) for m in method_ids_str.split(',')]
        placeholders = ','.join('?' * len(method_ids))
        
        # Get ACTUAL count: unique multipliers where ALL methods triggered
        cursor.execute(f"""
            SELECT COUNT(DISTINCT multiplier_id)
            FROM (
                SELECT multiplier_id
                FROM signals
                WHERE method_id IN ({placeholders})
                GROUP BY multiplier_id
                HAVING COUNT(DISTINCT method_id) = ?
            )
        """, method_ids + [len(method_ids)])
        
        actual_count = cursor.fetchone()[0]
        
        diff = abs(reported_count - actual_count)
        pct_of_total = (actual_count / total_rounds * 100) if total_rounds > 0 else 0
        
        status = "✓" if diff == 0 else "✗"
        
        print(f"{combo_id:<5} {short_name:<25} {reported_count:>13,} {actual_count:>13,} "
              f"{diff:>8,} {status} {pct_of_total:>5.1f}%")
    
    # Detailed analysis for top combo
    print(f"\n{'='*100}")
    print("DETAILED ANALYSIS: M3+M6+M7+M10")
    print("="*100)
    
    method_ids = [3, 6, 7, 10]
    
    # Count rounds with each individual method
    print(f"\nIndividual Method Counts:")
    for m_id in method_ids:
        cursor.execute("""
            SELECT COUNT(DISTINCT multiplier_id)
            FROM signals
            WHERE method_id = ?
        """, (m_id,))
        count = cursor.fetchone()[0]
        pct = (count / total_rounds * 100) if total_rounds > 0 else 0
        print(f"  M{m_id}: {count:,} rounds ({pct:.1f}% of total)")
    
    # Count with all 4 methods
    cursor.execute("""
        SELECT COUNT(DISTINCT multiplier_id)
        FROM (
            SELECT multiplier_id
            FROM signals
            WHERE method_id IN (3,6,7,10)
            GROUP BY multiplier_id
            HAVING COUNT(DISTINCT method_id) = 4
        )
    """)
    combo_count = cursor.fetchone()[0]
    combo_pct = (combo_count / total_rounds * 100) if total_rounds > 0 else 0
    
    print(f"\nCombination M3+M6+M7+M10:")
    print(f"  Actual occurrences: {combo_count:,} rounds ({combo_pct:.1f}% of total)")
    
    # Check if reasonable
    if combo_pct > 50:
        print(f"\n⚠️  WARNING: {combo_pct:.1f}% seems very high!")
        print(f"  This means M3+M6+M7+M10 all triggered together in over half of all rounds.")
    
    # Sample some rounds to verify
    cursor.execute("""
        SELECT multiplier_id, COUNT(DISTINCT method_id) as method_count
        FROM signals
        WHERE method_id IN (3,6,7,10)
        GROUP BY multiplier_id
        HAVING COUNT(DISTINCT method_id) = 4
        LIMIT 5
    """)
    
    print(f"\nSample rounds where all 4 methods triggered:")
    print(f"{'Multiplier ID':<15} {'Methods Present'}")
    print("-"*40)
    
    for mult_id, method_count in cursor.fetchall():
        cursor.execute("""
            SELECT method_id
            FROM signals
            WHERE multiplier_id = ?
            ORDER BY method_id
        """, (mult_id,))
        
        all_methods = [row[0] for row in cursor.fetchall()]
        our_methods = [m for m in all_methods if m in [3,6,7,10]]
        
        print(f"{mult_id:<15} M{',M'.join(map(str, our_methods))} "
              f"(total methods: {len(all_methods)})")
    
    # Check original Top 10
    print(f"\n{'='*100}")
    print("ORIGINAL TOP 10 VERIFICATION")
    print("="*100)
    
    cursor.execute("""
        SELECT combo_id, short_name, method_ids, checked_occurrences
        FROM combinations
        WHERE combo_id <= 10
        ORDER BY combo_id
    """)
    
    print(f"\n{'ID':<5} {'Combo':<25} {'Reported':<15} {'Actual':<15} {'Diff'}")
    print("-"*80)
    
    for combo_id, short_name, method_ids_str, reported_count in cursor.fetchall():
        method_ids = [int(m) for m in method_ids_str.split(',')]
        placeholders = ','.join('?' * len(method_ids))
        
        cursor.execute(f"""
            SELECT COUNT(DISTINCT multiplier_id)
            FROM (
                SELECT multiplier_id
                FROM signals
                WHERE method_id IN ({placeholders})
                GROUP BY multiplier_id
                HAVING COUNT(DISTINCT method_id) = ?
            )
        """, method_ids + [len(method_ids)])
        
        actual_count = cursor.fetchone()[0]
        diff = abs(reported_count - actual_count)
        status = "✓" if diff == 0 else "✗"
        
        print(f"{combo_id:<5} {short_name:<25} {reported_count:>13,} {actual_count:>13,} "
              f"{diff:>8,} {status}")
    
    conn.close()
    
    print(f"\n{'='*100}")
    print("✅ Verification complete")
    print("="*100)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify combination occurrences')
    parser.add_argument('--db', default='./crasher_data.db', help='Database path')
    args = parser.parse_args()
    
    verify_occurrences(args.db)
