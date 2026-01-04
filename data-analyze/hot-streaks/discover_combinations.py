#!/usr/bin/env python3
"""
Combination Discovery - Test All 2 & 3 Method Combinations
Finds the best minimalist combinations from your actual data
"""

import json
import sqlite3
import sys
from itertools import combinations
from typing import Dict, List, Tuple


class CombinationTester:
    """Test all possible method combinations"""

    def __init__(self, db_path: str, verbose: bool = True):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.verbose = verbose

    def log(self, message: str):
        if self.verbose:
            print(message)

    def get_method_names(self) -> Dict[int, str]:
        """Get method names from database"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT method_id, short_title FROM methods ORDER BY method_id")
        return {method_id: name for method_id, name in cursor.fetchall()}

    def test_combination(self, method_ids: List[int]) -> Dict:
        """
        Test a specific combination of methods
        Returns: {
            'methods': [1, 2, 3],
            'combo_str': 'M1+M2+M3',
            'total_occurrences': 1234,
            'checked': 567,
            'successful': 340,
            'accuracy': 60.0,
            'avg_confidence': 0.55,
            'avg_prediction': 12.3,
            'avg_margin_error': 8.5
        }
        """
        cursor = self.conn.cursor()

        # Find all multipliers where ALL these methods triggered
        placeholders = ",".join("?" * len(method_ids))

        # Get all multipliers with signals from these methods
        cursor.execute(
            f"""
            SELECT
                s.multiplier_id,
                COUNT(DISTINCT s.method_id) as method_count
            FROM signals s
            WHERE s.method_id IN ({placeholders})
            GROUP BY s.multiplier_id
            HAVING COUNT(DISTINCT s.method_id) = ?
        """,
            method_ids + [len(method_ids)],
        )

        multiplier_ids = [row[0] for row in cursor.fetchall()]
        total_occurrences = len(multiplier_ids)

        if total_occurrences == 0:
            return None

        # Get fact-check results for these multipliers
        # Join through signals table to get multiplier_id
        mult_placeholders = ",".join("?" * len(multiplier_ids))

        cursor.execute(
            f"""
            SELECT
                sig.multiplier_id,
                AVG(sfc.predicted_rounds) as avg_pred,
                AVG(sfc.actual_rounds) as avg_actual,
                AVG(sfc.confidence) as avg_conf,
                AVG(sfc.margin_error) as avg_error,
                COUNT(DISTINCT sfc.method_id) as method_count
            FROM signal_fact_check sfc
            JOIN signals sig ON sfc.signal_id = sig.id
            WHERE sfc.method_id IN ({placeholders})
              AND sig.multiplier_id IN ({mult_placeholders})
            GROUP BY sig.multiplier_id
            HAVING COUNT(DISTINCT sfc.method_id) = ?
        """,
            method_ids + multiplier_ids + [len(method_ids)],
        )

        results = cursor.fetchall()
        checked = len(results)

        if checked == 0:
            return None

        # Calculate statistics
        successful = 0
        total_conf = 0
        total_pred = 0
        total_error = 0

        for mult_id, avg_pred, avg_actual, avg_conf, avg_error, meth_count in results:
            if avg_pred is not None and avg_actual is not None:
                margin = abs(avg_actual - avg_pred)
                if margin <= 10:
                    successful += 1
                total_conf += avg_conf if avg_conf else 0
                total_pred += avg_pred if avg_pred else 0
                total_error += avg_error if avg_error else 0

        accuracy = (successful / checked * 100) if checked > 0 else 0
        avg_confidence = total_conf / checked if checked > 0 else 0
        avg_prediction = total_pred / checked if checked > 0 else 0
        avg_margin_error = total_error / checked if checked > 0 else 0

        combo_str = "+".join([f"M{m}" for m in method_ids])

        return {
            "methods": method_ids,
            "combo_str": combo_str,
            "total_occurrences": total_occurrences,
            "checked": checked,
            "successful": successful,
            "accuracy": accuracy,
            "avg_confidence": avg_confidence,
            "avg_prediction": avg_prediction,
            "avg_margin_error": avg_margin_error,
        }

    def test_all_combinations(
        self, min_size: int = 2, max_size: int = 3, min_occurrences: int = 100
    ) -> List[Dict]:
        """
        Test all possible combinations of specified sizes

        Args:
            min_size: Minimum combination size (default: 2)
            max_size: Maximum combination size (default: 3)
            min_occurrences: Minimum occurrences to include (default: 100)

        Returns:
            List of combination results, sorted by accuracy
        """
        method_ids = list(range(1, 11))  # Methods 1-10
        all_results = []

        for size in range(min_size, max_size + 1):
            self.log(f"\n{'=' * 80}")
            self.log(f"Testing {size}-Method Combinations")
            self.log(f"{'=' * 80}")

            # Generate all combinations of this size
            combos = list(combinations(method_ids, size))
            total_combos = len(combos)

            self.log(f"Total combinations to test: {total_combos}")

            tested = 0
            skipped = 0

            for i, combo in enumerate(combos, 1):
                if i % 10 == 0:
                    self.log(
                        f"  Progress: {i}/{total_combos} ({i / total_combos * 100:.1f}%)"
                    )

                result = self.test_combination(list(combo))

                if result and result["checked"] >= min_occurrences:
                    all_results.append(result)
                    tested += 1
                else:
                    skipped += 1

            self.log(f"\n  ✓ Tested: {tested}, Skipped: {skipped} (insufficient data)")

        # Sort by accuracy
        all_results.sort(key=lambda x: x["accuracy"], reverse=True)

        return all_results

    def save_to_database(self, results: List[Dict], min_accuracy: float = 60.0):
        """
        Save high-performing combinations to the combinations table

        Args:
            results: List of combination results
            min_accuracy: Minimum accuracy to save (default: 60%)
        """
        cursor = self.conn.cursor()

        # Filter results by accuracy
        high_performers = [r for r in results if r["accuracy"] >= min_accuracy]

        if not high_performers:
            self.log(f"\n⚠️  No combinations found with accuracy >= {min_accuracy}%")
            return

        self.log(f"\n{'=' * 80}")
        self.log(f"SAVING TO DATABASE")
        self.log(f"{'=' * 80}")
        self.log(
            f"\nFound {len(high_performers)} combinations with accuracy >= {min_accuracy}%"
        )

        # Get current max combo_id
        cursor.execute("SELECT MAX(combo_id) FROM combinations")
        result = cursor.fetchone()
        next_id = (
            (result[0] + 1) if result[0] else 11
        )  # Start from 11 if original top 10 exist

        saved_count = 0
        updated_count = 0

        for combo_result in high_performers:
            method_ids_str = ",".join(map(str, combo_result["methods"]))

            # Check if combination already exists
            cursor.execute(
                """
                SELECT combo_id, actual_accuracy
                FROM combinations
                WHERE method_ids = ?
            """,
                (method_ids_str,),
            )

            existing = cursor.fetchone()

            if existing:
                # Update existing combination
                existing_id, existing_accuracy = existing

                # Only update if new accuracy is different
                if abs(existing_accuracy - combo_result["accuracy"]) > 0.1:
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
                            combo_result["accuracy"],
                            combo_result["accuracy"],
                            combo_result["checked"],
                            combo_result["successful"],
                            combo_result["avg_confidence"],
                            existing_id,
                        ),
                    )

                    self.log(
                        f"  ✓ Updated #{existing_id}: {combo_result['combo_str']} "
                        f"({existing_accuracy:.1f}% → {combo_result['accuracy']:.1f}%)"
                    )
                    updated_count += 1
            else:
                # Insert new combination
                # Generate a descriptive name
                size = len(combo_result["methods"])
                if size == 2:
                    name = f"Duo {combo_result['combo_str']}"
                elif size == 3:
                    name = f"Trio {combo_result['combo_str']}"
                elif size == 4:
                    name = f"Quad {combo_result['combo_str']}"
                else:
                    name = f"{size}-Method {combo_result['combo_str']}"

                # Use accuracy as initial_accuracy for discovered combos
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
                        combo_result["combo_str"],
                        method_ids_str,
                        combo_result["accuracy"],
                        combo_result["accuracy"],
                        combo_result["accuracy"],
                        combo_result["checked"],
                        combo_result["successful"],
                        combo_result["avg_confidence"],
                    ),
                )

                self.log(
                    f"  ✓ Added #{next_id}: {combo_result['combo_str']} ({combo_result['accuracy']:.1f}%)"
                )
                next_id += 1
                saved_count += 1

        self.conn.commit()

        self.log(f"\n{'=' * 80}")
        self.log(f"✅ Database updated!")
        self.log(f"   New combinations added: {saved_count}")
        self.log(f"   Existing combinations updated: {updated_count}")
        self.log(f"   Total high performers: {len(high_performers)}")
        self.log(f"{'=' * 80}")

    def save_results(
        self, results: List[Dict], output_file: str = "combination_results.json"
    ):
        """Save results to JSON file"""
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        self.log(f"\n✓ Results saved to {output_file}")

    def print_report(self, results: List[Dict], top_n: int = 20):
        """Print comprehensive report"""

        print("\n" + "=" * 100)
        print("COMBINATION DISCOVERY RESULTS")
        print("=" * 100)

        # Overall statistics
        print(f"\nTotal combinations tested: {len(results)}")

        if not results:
            print("\n⚠️  No combinations found with sufficient data!")
            return

        avg_accuracy = sum(r["accuracy"] for r in results) / len(results)
        print(f"Average accuracy: {avg_accuracy:.1f}%")
        print(
            f"Best accuracy: {results[0]['accuracy']:.1f}% ({results[0]['combo_str']})"
        )
        print(
            f"Worst accuracy: {results[-1]['accuracy']:.1f}% ({results[-1]['combo_str']})"
        )

        # Top N combinations
        print(f"\n{'=' * 100}")
        print(f"TOP {top_n} COMBINATIONS BY ACCURACY")
        print("=" * 100)

        print(
            f"\n{'Rank':<6} {'Combo':<20} {'Accuracy':<10} {'Checked':<10} {'Success':<10} {'Avg Error':<10} {'Avg Conf'}"
        )
        print("-" * 100)

        for i, result in enumerate(results[:top_n], 1):
            print(
                f"{i:<6} {result['combo_str']:<20} {result['accuracy']:>7.1f}% "
                f"{result['checked']:>9,} {result['successful']:>9,} "
                f"{result['avg_margin_error']:>9.1f}r {result['avg_confidence'] * 100:>8.1f}%"
            )

        # Breakdown by size
        print(f"\n{'=' * 100}")
        print("BREAKDOWN BY COMBINATION SIZE")
        print("=" * 100)

        by_size = {}
        for result in results:
            size = len(result["methods"])
            if size not in by_size:
                by_size[size] = []
            by_size[size].append(result)

        for size in sorted(by_size.keys()):
            combos = by_size[size]
            avg_acc = sum(c["accuracy"] for c in combos) / len(combos)
            best = max(combos, key=lambda x: x["accuracy"])

            print(f"\n{size}-Method Combinations:")
            print(f"  Count: {len(combos)}")
            print(f"  Average accuracy: {avg_acc:.1f}%")
            print(f"  Best: {best['combo_str']} ({best['accuracy']:.1f}%)")

        # Method frequency in top combinations
        print(f"\n{'=' * 100}")
        print("METHOD FREQUENCY IN TOP 20")
        print("=" * 100)

        method_counts = {}
        for result in results[:20]:
            for method_id in result["methods"]:
                method_counts[method_id] = method_counts.get(method_id, 0) + 1

        method_names = self.get_method_names()

        print(f"\n{'Method':<8} {'Frequency':<12} {'Percentage'}")
        print("-" * 50)

        for method_id in sorted(
            method_counts.keys(), key=lambda x: method_counts[x], reverse=True
        ):
            freq = method_counts[method_id]
            pct = freq / 20 * 100
            name = method_names.get(method_id, f"M{method_id}")
            print(f"{name:<8} {freq:>10}/20 {pct:>10.0f}%")

        # Best by specific sizes
        print(f"\n{'=' * 100}")
        print("BEST COMBINATIONS BY SIZE")
        print("=" * 100)

        for size in sorted(by_size.keys()):
            best = by_size[size][0]  # Already sorted by accuracy
            print(f"\nBest {size}-Method Combo: {best['combo_str']}")
            print(f"  Accuracy: {best['accuracy']:.1f}%")
            print(f"  Tested: {best['checked']:,} occurrences")
            print(f"  Success: {best['successful']:,}/{best['checked']:,}")
            print(f"  Avg margin error: {best['avg_margin_error']:.1f} rounds")
            print(f"  Avg confidence: {best['avg_confidence'] * 100:.1f}%")

        # Comparison with original Top 10
        print(f"\n{'=' * 100}")
        print("COMPARISON WITH ORIGINAL TOP 10")
        print("=" * 100)

        original_combos = {
            "M1+M3+M4+M5+M6": 49.2,
            "M1+M4+M5+M6": 50.2,
            "M1+M2+M4+M5": 51.9,
            "M3+M4+M5+M6": 56.1,
            "M2+M3+M4+M6": 59.2,
            "M1+M3+M4+M5": 49.9,
            "M2+M4+M6": 60.6,
            "M1+M3+M5+M6": 48.5,
            "M1+M2+M4+M6": 53.8,
            "M3+M4+M5": 56.6,
        }

        print(
            f"\n{'Original Combo':<20} {'Original Acc':<15} {'New Discovery':<20} {'New Acc'}"
        )
        print("-" * 80)

        for orig_combo, orig_acc in sorted(
            original_combos.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            best_new = results[0]
            print(
                f"{orig_combo:<20} {orig_acc:>13.1f}% {best_new['combo_str']:<20} {best_new['accuracy']:>8.1f}%"
            )

        print(f"\nBest original: M2+M4+M6 (60.6%)")
        print(
            f"Best new discovery: {results[0]['combo_str']} ({results[0]['accuracy']:.1f}%)"
        )

        if results[0]["accuracy"] > 60.6:
            improvement = results[0]["accuracy"] - 60.6
            print(f"✅ Improvement: +{improvement:.1f}%")
        else:
            decline = 60.6 - results[0]["accuracy"]
            print(f"⚠️  Original was better by {decline:.1f}%")

    def close(self):
        self.conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Test all 2-method and 3-method combinations"
    )
    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database (default: ./crasher_data.db)",
    )
    parser.add_argument(
        "--min-size", type=int, default=2, help="Minimum combination size (default: 2)"
    )
    parser.add_argument(
        "--max-size", type=int, default=3, help="Maximum combination size (default: 3)"
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=100,
        help="Minimum occurrences to include (default: 100)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of top results to show (default: 20)",
    )
    parser.add_argument(
        "--output",
        default="combination_results.json",
        help="Output JSON file (default: combination_results.json)",
    )
    parser.add_argument(
        "--save-to-db",
        action="store_true",
        help="Save high-performing combinations to database",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=60.0,
        help="Minimum accuracy to save to database (default: 60.0)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

    args = parser.parse_args()

    try:
        tester = CombinationTester(args.db, verbose=not args.quiet)

        # Test all combinations
        results = tester.test_all_combinations(
            min_size=args.min_size,
            max_size=args.max_size,
            min_occurrences=args.min_occurrences,
        )

        # Save results
        tester.save_results(results, args.output)

        # Save to database if requested
        if args.save_to_db:
            tester.save_to_database(results, min_accuracy=args.min_accuracy)

        # Print report
        tester.print_report(results, top_n=args.top_n)

        tester.close()

        print("\n✅ Analysis complete!")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
