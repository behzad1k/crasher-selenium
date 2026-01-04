#!/usr/bin/env python3
"""
View Fact-Check Results
Quick script to view fact-check tables and key statistics
"""

import sqlite3
import sys


def view_fact_check_results(db_path: str = "./crasher_data.db"):
    """View fact-check results"""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 80)
    print("FACT-CHECK TABLES VIEWER")
    print("=" * 80)

    # Check tables exist
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('methods', 'signal_fact_check',
                                        'combinations', 'combination_fact_check')
        ORDER BY name
    """)

    tables = [row[0] for row in cursor.fetchall()]

    if not tables:
        print("\n❌ No fact-check tables found!")
        print("Run: python fact_check_signals.py")
        return

    print(f"\n✓ Found tables: {', '.join(tables)}")

    # Methods table
    if "methods" in tables:
        print("\n" + "=" * 80)
        print("METHODS TABLE")
        print("=" * 80)

        cursor.execute("SELECT COUNT(*) FROM methods")
        count = cursor.fetchone()[0]
        print(f"\nTotal methods: {count}")

        if count > 0:
            cursor.execute("""
                SELECT
                    short_title,
                    title,
                    initial_accuracy,
                    actual_accuracy,
                    adjusted_accuracy,
                    checked_signals
                FROM methods
                ORDER BY method_id
                LIMIT 5
            """)

            print("\nSample (first 5):")
            print(
                f"{'ID':<5} {'Title':<35} {'Initial':<9} {'Actual':<9} {'Adjusted':<9} {'Checked'}"
            )
            print("-" * 80)

            for row in cursor.fetchall():
                short, title, initial, actual, adjusted, checked = row
                actual_str = f"{actual:.1f}%" if actual is not None else "N/A"
                adjusted_str = f"{adjusted:.1f}%" if adjusted is not None else "N/A"
                title_short = title[:33]
                print(
                    f"{short:<5} {title_short:<35} {initial:>7.1f}% {actual_str:>8} {adjusted_str:>8} {checked:>7,}"
                )

    # Signal fact-check table
    if "signal_fact_check" in tables:
        print("\n" + "=" * 80)
        print("SIGNAL_FACT_CHECK TABLE")
        print("=" * 80)

        cursor.execute("SELECT COUNT(*) FROM signal_fact_check")
        count = cursor.fetchone()[0]
        print(f"\nTotal fact-checked signals: {count:,}")

        if count > 0:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN successful THEN 1 ELSE 0 END) as successful,
                    AVG(margin_error) as avg_error,
                    AVG(confidence) * 100 as avg_confidence
                FROM signal_fact_check
            """)

            total, successful, avg_error, avg_conf = cursor.fetchone()
            success_rate = (successful / total * 100) if total > 0 else 0

            print(f"\nOverall Statistics:")
            print(
                f"  Successful predictions: {successful:,}/{total:,} ({success_rate:.1f}%)"
            )
            print(f"  Average margin error: {avg_error:.1f} rounds")
            print(f"  Average confidence: {avg_conf:.1f}%")

            # Sample records
            cursor.execute("""
                SELECT
                    m.short_title,
                    sfc.predicted_rounds,
                    sfc.actual_rounds,
                    sfc.margin_error,
                    sfc.successful,
                    sfc.confidence * 100 as conf
                FROM signal_fact_check sfc
                JOIN methods m ON sfc.method_id = m.method_id
                ORDER BY sfc.id DESC
                LIMIT 10
            """)

            print("\nSample (most recent 10):")
            print(
                f"{'Method':<8} {'Predicted':<10} {'Actual':<10} {'Error':<8} {'Success':<9} {'Conf'}"
            )
            print("-" * 60)

            for row in cursor.fetchall():
                method, pred, actual, error, success, conf = row
                success_str = "✓" if success else "✗"
                print(
                    f"{method:<8} {pred:>9}r {actual:>9}r {error:>7}r {success_str:^9} {conf:>5.1f}%"
                )

    # Combinations table
    if "combinations" in tables:
        print("\n" + "=" * 80)
        print("COMBINATIONS TABLE")
        print("=" * 80)

        cursor.execute("SELECT COUNT(*) FROM combinations")
        count = cursor.fetchone()[0]
        print(f"\nTotal combinations: {count}")

        if count > 0:
            cursor.execute("""
                SELECT
                    combo_id,
                    short_name,
                    initial_accuracy,
                    actual_accuracy,
                    adjusted_accuracy,
                    checked_occurrences,
                    successful_occurrences
                FROM combinations
                ORDER BY combo_id
            """)

            print(
                f"\n{'#':<3} {'Combo':<20} {'Initial':<9} {'Actual':<9} {'Adjusted':<9} {'Success'}"
            )
            print("-" * 70)

            for row in cursor.fetchall():
                cid, name, initial, actual, adjusted, checked, successful = row
                actual_str = f"{actual:.1f}%" if actual is not None else "N/A"
                adjusted_str = f"{adjusted:.1f}%" if adjusted is not None else "N/A"
                success_str = f"{successful}/{checked}" if checked > 0 else "N/A"
                print(
                    f"{cid:<3} {name:<20} {initial:>7.1f}% {actual_str:>8} {adjusted_str:>8} {success_str:>8}"
                )

    # Combination fact-check table
    if "combination_fact_check" in tables:
        print("\n" + "=" * 80)
        print("COMBINATION_FACT_CHECK TABLE")
        print("=" * 80)

        cursor.execute("SELECT COUNT(*) FROM combination_fact_check")
        count = cursor.fetchone()[0]
        print(f"\nTotal fact-checked combinations: {count:,}")

        if count > 0:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN successful THEN 1 ELSE 0 END) as successful,
                    AVG(margin_error) as avg_error
                FROM combination_fact_check
            """)

            total, successful, avg_error = cursor.fetchone()
            success_rate = (successful / total * 100) if total > 0 else 0

            print(f"\nOverall Statistics:")
            print(
                f"  Successful predictions: {successful:,}/{total:,} ({success_rate:.1f}%)"
            )
            print(f"  Average margin error: {avg_error:.1f} rounds")

    # Best and worst performers
    if "methods" in tables and "signal_fact_check" in tables:
        print("\n" + "=" * 80)
        print("TOP & BOTTOM PERFORMERS")
        print("=" * 80)

        cursor.execute("""
            SELECT short_title, actual_accuracy
            FROM methods
            WHERE actual_accuracy IS NOT NULL
            ORDER BY actual_accuracy DESC
            LIMIT 3
        """)

        print("\n🏆 Top 3 Methods:")
        for idx, (method, acc) in enumerate(cursor.fetchall(), 1):
            print(f"  {idx}. {method}: {acc:.1f}%")

        cursor.execute("""
            SELECT short_title, actual_accuracy
            FROM methods
            WHERE actual_accuracy IS NOT NULL
            ORDER BY actual_accuracy ASC
            LIMIT 3
        """)

        print("\n⚠️  Bottom 3 Methods:")
        for idx, (method, acc) in enumerate(cursor.fetchall(), 1):
            print(f"  {idx}. {method}: {acc:.1f}%")

    print("\n" + "=" * 80)
    print("✅ View complete")
    print("=" * 80)

    conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="View fact-check results")
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database (default: ./crasher_data.db)",
    )

    args = parser.parse_args()

    try:
        view_fact_check_results(args.db)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
