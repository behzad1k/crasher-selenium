#!/usr/bin/env python3
"""
Add Combinations to Database
Reads combination_results.json and adds high-performers to the combinations table
"""

import json
import sqlite3
import sys


def add_combinations_to_db(
    json_file: str = "combination_results.json",
    db_path: str = "./crasher_data.db",
    min_accuracy: float = 60.0,
    verbose: bool = True,
):
    """Add combinations from JSON to database"""

    def log(msg):
        if verbose:
            print(msg)

    # Load results
    try:
        with open(json_file, "r") as f:
            results = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File '{json_file}' not found!")
        print("Run discover_combinations.py first to generate results.")
        return

    # Filter by accuracy
    high_performers = [r for r in results if r["accuracy"] >= min_accuracy]

    log("=" * 80)
    log("ADD COMBINATIONS TO DATABASE")
    log("=" * 80)
    log(f"\nSource file: {json_file}")
    log(f"Total combinations in file: {len(results)}")
    log(f"Combinations with accuracy >= {min_accuracy}%: {len(high_performers)}")

    if not high_performers:
        log(f"\n⚠️  No combinations found with accuracy >= {min_accuracy}%")
        return

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if combinations table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='combinations'
    """)

    if not cursor.fetchone():
        log("\n❌ Error: 'combinations' table does not exist!")
        log("Run fact_check_signals.py first to create the table.")
        conn.close()
        return

    # Get current max combo_id
    cursor.execute("SELECT MAX(combo_id) FROM combinations")
    result = cursor.fetchone()
    next_id = (result[0] + 1) if result[0] else 11

    log(f"\nStarting combo_id: {next_id}")
    log(f"\n{'=' * 80}")
    log("PROCESSING COMBINATIONS")
    log("=" * 80)

    saved_count = 0
    updated_count = 0
    skipped_count = 0

    # Sort by accuracy descending
    high_performers.sort(key=lambda x: x["accuracy"], reverse=True)

    for i, combo in enumerate(high_performers, 1):
        method_ids_str = ",".join(map(str, combo["methods"]))

        # Check if exists
        cursor.execute(
            """
            SELECT combo_id, name, actual_accuracy
            FROM combinations
            WHERE method_ids = ?
        """,
            (method_ids_str,),
        )

        existing = cursor.fetchone()

        if existing:
            existing_id, existing_name, existing_accuracy = existing

            # Update if accuracy changed significantly
            if abs(existing_accuracy - combo["accuracy"]) > 0.1:
                cursor.execute(
                    """
                    UPDATE combinations
                    SET actual_accuracy = ?,
                        adjusted_accuracy = (initial_accuracy + ?) / 2,
                        checked_occurrences = ?,
                        successful_occurrences = ?,
                        avg_confidence = ?,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE combo_id = ?
                """,
                    (
                        combo["accuracy"],
                        combo["accuracy"],
                        combo["checked"],
                        combo["successful"],
                        combo["avg_confidence"],
                        existing_id,
                    ),
                )

                log(
                    f"  [{i}/{len(high_performers)}] ✓ Updated #{existing_id}: {combo['combo_str']} "
                    f"({existing_accuracy:.1f}% → {combo['accuracy']:.1f}%)"
                )
                updated_count += 1
            else:
                log(
                    f"  [{i}/{len(high_performers)}] ⊘ Skipped #{existing_id}: {combo['combo_str']} "
                    f"(already at {existing_accuracy:.1f}%)"
                )
                skipped_count += 1
        else:
            # Generate name
            size = len(combo["methods"])
            if size == 2:
                name = f"Discovered Duo {combo['combo_str']}"
            elif size == 3:
                name = f"Discovered Trio {combo['combo_str']}"
            elif size == 4:
                name = f"Discovered Quad {combo['combo_str']}"
            else:
                name = f"Discovered {size}-Method {combo['combo_str']}"

            # Insert new
            cursor.execute(
                """
                INSERT INTO combinations
                (combo_id, name, short_name, method_ids, initial_accuracy,
                 actual_accuracy, adjusted_accuracy, checked_occurrences,
                 successful_occurrences, avg_confidence, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (
                    next_id,
                    name,
                    combo["combo_str"],
                    method_ids_str,
                    combo["accuracy"],
                    combo["accuracy"],
                    combo["accuracy"],
                    combo["checked"],
                    combo["successful"],
                    combo["avg_confidence"],
                ),
            )

            log(
                f"  [{i}/{len(high_performers)}] ✓ Added #{next_id}: {combo['combo_str']} "
                f"({combo['accuracy']:.1f}% | {combo['checked']:,} checks)"
            )
            next_id += 1
            saved_count += 1

    conn.commit()

    log(f"\n{'=' * 80}")
    log("✅ DATABASE UPDATED!")
    log("=" * 80)
    log(f"   New combinations added: {saved_count}")
    log(f"   Existing updated: {updated_count}")
    log(f"   Skipped (no change): {skipped_count}")
    log(f"   Total processed: {len(high_performers)}")
    log("=" * 80)

    # Show top 10 in database
    log("\nTop 10 Combinations in Database (by actual accuracy):")
    log("-" * 80)

    cursor.execute("""
        SELECT combo_id, short_name, actual_accuracy, checked_occurrences
        FROM combinations
        WHERE actual_accuracy IS NOT NULL
        ORDER BY actual_accuracy DESC
        LIMIT 10
    """)

    log(f"{'#':<5} {'Combo':<25} {'Accuracy':<12} {'Checks'}")
    log("-" * 80)

    for combo_id, short_name, accuracy, checks in cursor.fetchall():
        log(f"{combo_id:<5} {short_name:<25} {accuracy:>9.1f}% {checks:>12,}")

    conn.close()

    log("\n✅ Complete!")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add high-performing combinations from JSON to database"
    )
    parser.add_argument(
        "--json",
        default="combination_results.json",
        help="JSON file with results (default: combination_results.json)",
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Database path (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=57.0,
        help="Minimum accuracy to add (default: 60.0)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

    args = parser.parse_args()

    try:
        add_combinations_to_db(
            json_file=args.json,
            db_path=args.db,
            min_accuracy=args.min_accuracy,
            verbose=not args.quiet,
        )
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
