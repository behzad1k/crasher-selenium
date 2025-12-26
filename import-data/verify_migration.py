#!/usr/bin/env python3
"""
Database Migration Verification Script
Checks if database has been properly migrated to support sessions
"""

import sqlite3
import sys
from datetime import datetime


def check_database_schema(db_path: str = "../crasher_data.db"):
    """Verify database schema has session support"""

    print("=" * 70)
    print("DATABASE MIGRATION VERIFICATION")
    print("=" * 70)
    print(f"\nDatabase: {db_path}\n")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check for sessions table
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='sessions'
        """)

        has_sessions_table = cursor.fetchone() is not None

        # Check for session_id column in multipliers
        cursor.execute("PRAGMA table_info(multipliers)")
        multipliers_columns = {col[1]: col[2] for col in cursor.fetchall()}
        has_session_id = "session_id" in multipliers_columns

        # Check for strategy_name in bets
        cursor.execute("PRAGMA table_info(bets)")
        bets_columns = {col[1]: col[2] for col in cursor.fetchall()}
        has_strategy_name = "strategy_name" in bets_columns

        # Get counts
        cursor.execute("SELECT COUNT(*) FROM multipliers")
        total_rounds = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM multipliers WHERE session_id IS NOT NULL")
        assigned_rounds = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sessions")
        total_sessions = cursor.fetchone()[0]

        # Display results
        print("SCHEMA CHECK:")
        print("-" * 70)

        status = "✓" if has_sessions_table else "✗"
        print(f"  {status} Sessions table exists: {has_sessions_table}")

        status = "✓" if has_session_id else "✗"
        print(f"  {status} Multipliers.session_id column exists: {has_session_id}")

        status = "✓" if has_strategy_name else "✗"
        print(f"  {status} Bets.strategy_name column exists: {has_strategy_name}")

        print(f"\nDATA STATUS:")
        print("-" * 70)
        print(f"  Total rounds: {total_rounds:,}")
        print(f"  Assigned to sessions: {assigned_rounds:,}")
        print(f"  Unassigned rounds: {total_rounds - assigned_rounds:,}")
        print(f"  Total sessions: {total_sessions}")

        # Migration status
        print(f"\nMIGRATION STATUS:")
        print("-" * 70)

        if not has_sessions_table or not has_session_id:
            print("  ⚠️  MIGRATION REQUIRED")
            print("\n  Run: python migrate_add_sessions.py")
            return False

        if total_rounds > 0 and assigned_rounds == 0:
            print("  ⚠️  SESSION ASSIGNMENT REQUIRED")
            print("\n  All rounds exist but none are assigned to sessions.")
            print("  Run: python import_logs.py --detect-sessions")
            return False

        if total_rounds > assigned_rounds:
            unassigned = total_rounds - assigned_rounds
            print(f"  ⚠️  PARTIAL SESSION ASSIGNMENT")
            print(
                f"\n  {unassigned:,} rounds ({unassigned / total_rounds * 100:.1f}%) are not assigned to sessions."
            )
            print("  Run: python import_logs.py --detect-sessions")
            return False

        print("  ✓ MIGRATION COMPLETE")
        print("\n  All schema changes applied successfully.")
        if total_rounds > 0:
            print(
                f"  All {total_rounds:,} rounds are assigned to {total_sessions} sessions."
            )

        # Show session summary if exists
        if total_sessions > 0:
            print(f"\nSESSION SUMMARY:")
            print("-" * 70)

            cursor.execute("""
                SELECT
                    id,
                    start_timestamp,
                    end_timestamp,
                    start_balance,
                    end_balance,
                    total_rounds
                FROM sessions
                ORDER BY start_timestamp
                LIMIT 5
            """)

            sessions = cursor.fetchall()

            for session in sessions:
                sid, start, end, start_bal, end_bal, rounds = session
                print(f"\n  Session {sid}:")
                print(f"    Period: {start} → {end}")
                if start_bal and end_bal:
                    profit = end_bal - start_bal
                    print(
                        f"    Balance: {start_bal:,.0f} → {end_bal:,.0f} ({profit:+,.0f})"
                    )
                print(f"    Rounds: {rounds}")

            if total_sessions > 5:
                print(f"\n  ... and {total_sessions - 5} more sessions")
                print("\n  Run: python import_logs.py --show-sessions")
                print("  to see complete session list.")

        print("\n" + "=" * 70)

        conn.close()
        return True

    except sqlite3.OperationalError as e:
        print(f"\n❌ Database error: {e}")
        print("\nThe database file may not exist or may be corrupted.")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    db_path = "./crasher_data.db"

    if len(sys.argv) >= 2:
        if sys.argv[1] in ["--help", "-h"]:
            print("Usage: python verify_migration.py [database_path]")
            print("\nExample:")
            print("  python verify_migration.py")
            print("  python verify_migration.py ./crasher_data.db")
            return
        db_path = sys.argv[1]

    import os

    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        print("\nMake sure you've run the bot at least once to create the database.")
        sys.exit(1)

    success = check_database_schema(db_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
