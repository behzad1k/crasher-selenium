#!/usr/bin/env python3
"""
Master Analysis Runner
Runs complete analysis pipeline for crasher game data
"""

import os
import subprocess
import sys
from datetime import datetime


def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80)


def print_section(text):
    """Print formatted section"""
    print("\n" + "-" * 80)
    print(text)
    print("-" * 80)


def run_analysis_suite():
    """Run complete analysis suite"""

    import sys

    # Parse arguments
    db_path = "./crasher_data.db"
    threshold = 2.0

    if "--db" in sys.argv:
        idx = sys.argv.index("--db")
        if idx + 1 < len(sys.argv):
            db_path = sys.argv[idx + 1]

    if "--threshold" in sys.argv:
        idx = sys.argv.index("--threshold")
        if idx + 1 < len(sys.argv):
            try:
                threshold = float(sys.argv[idx + 1])
            except ValueError:
                print(f"Invalid threshold value, using default 2.0")

    print_header("CRASHER GAME ANALYSIS SUITE")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {db_path}")
    print(f"Threshold: {threshold}x\n")

    # Check if database exists
    db_path = "./crasher_data.db"
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        print("\nPlease run the import script first:")
        print("  python import_logs.py crasher_bot.log")
        return False

    print(f"✓ Found database: {db_path}")

    # Check for required packages
    print_section("Checking Dependencies")
    try:
        import pandas

        print("✓ pandas installed")
    except ImportError:
        print("❌ pandas not installed")
        print("\nInstall with: pip install pandas --break-system-packages")
        return False

    try:
        import openpyxl

        print("✓ openpyxl installed")
    except ImportError:
        print("❌ openpyxl not installed")
        print("\nInstall with: pip install openpyxl --break-system-packages")
        return False

    # Get row count
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM multipliers")
    row_count = cursor.fetchone()[0]
    conn.close()

    print(f"\n✓ Database contains {row_count:,} rounds")

    if row_count == 0:
        print("\n❌ No data in database!")
        print("\nPlease run the import script first:")
        print("  python import_logs.py crasher_bot.log")
        return False

    # Run console analysis
    print_section("Running Console Analysis")
    print("This will analyze streaks, sessions, and risk...")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "data-analyze/analyze_crasher.py",
                db_path,
                str(threshold),
            ],
            capture_output=False,
            text=True,
        )
        if result.returncode != 0:
            print("\n⚠️  Console analysis had issues")
        else:
            print("\n✓ Console analysis completed")
    except Exception as e:
        print(f"\n❌ Console analysis failed: {e}")

    # Run Excel report generation
    print_section("Generating Excel Report")
    print("Creating detailed Excel report with multiple sheets...")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "data-analyze/generate_excel_report.py",
                db_path,
                str(threshold),
            ],
            capture_output=False,
            text=True,
        )
        if result.returncode != 0:
            print("\n⚠️  Excel generation had issues")
        else:
            print("\n✓ Excel report generated")
    except Exception as e:
        print(f"\n❌ Excel generation failed: {e}")

    # Run visualizations
    print_section("Generating Visualizations")
    print("Creating graphs and charts...")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "data-analyze/visualize_crasher.py",
                "--db",
                db_path,
                "--threshold",
                str(threshold),
            ],
            capture_output=False,
            text=True,
        )
        if result.returncode != 0:
            print("\n⚠️  Visualization had issues")
        else:
            print("\n✓ Visualizations completed")
    except Exception as e:
        print(f"\n❌ Visualization failed: {e}")

    # Summary
    print_header("ANALYSIS COMPLETE")

    print("\nGenerated Files:")
    print("  📊 /mnt/user-data/outputs/crasher_analysis.xlsx - Detailed Excel report")
    print("  📄 /mnt/user-data/outputs/analysis_report.json - JSON data export")
    print("  📈 /mnt/user-data/outputs/session_overview.png - Session graphs")
    print(
        "  📈 /mnt/user-data/outputs/multiplier_distribution.png - Distribution analysis"
    )
    print("  📈 /mnt/user-data/outputs/streak_analysis.png - Streak patterns")
    print("  📈 /mnt/user-data/outputs/10x_analysis.png - 10x multiplier analysis")
    print(
        "  📖 /mnt/user-data/outputs/STRATEGY_ANALYSIS.md - Strategic recommendations"
    )

    print("\nNext Steps:")
    print("  1. Open the Excel report to review detailed analysis")
    print("  2. Read STRATEGY_ANALYSIS.md for recommendations")
    print("  3. Check the console output above for key findings")
    print("  4. Look for:")
    print("     - Longest streak of consecutive under-2.0x rounds")
    print("     - Frequency of 15+ consecutive rounds (catastrophic events)")
    print("     - Win rate vs. loss rate for your strategy")
    print("     - Session-by-session variability")

    print("\n⚠️  IMPORTANT: Remember this is gambling. Past performance does not")
    print("    guarantee future results. Only bet what you can afford to lose.")

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return True


def main():
    """Main entry point"""
    try:
        success = run_analysis_suite()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
