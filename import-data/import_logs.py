#!/usr/bin/env python3
"""
Log Importer for Crasher Bot
Parses log files and creates a new database with sessions automatically detected
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class LogImporter:
    """Import round data from log files into the database with automatic session detection"""

    def __init__(self, db_path: str = "./crasher_data.db", create_new: bool = False):
        """
        Initialize the log importer

        Args:
            db_path: Path to the database file
            create_new: If True, creates a fresh database (deletes existing)
        """
        if create_new and os.path.exists(db_path):
            print(f"⚠️  Removing existing database: {db_path}")
            os.remove(db_path)

        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        self.max_gap_minutes = 3  # Maximum gap between rounds in same session

    def _create_tables(self):
        """Create all database tables with sessions support built-in"""
        cursor = self.conn.cursor()

        # Sessions table (created first for foreign key reference)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_timestamp DATETIME NOT NULL,
                end_timestamp DATETIME,
                start_balance REAL,
                end_balance REAL,
                total_rounds INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Multipliers table with session_id
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME NOT NULL,
                session_id INTEGER NOT NULL REFERENCES sessions(id),
                UNIQUE(timestamp, multiplier)
            )
        """)

        # Bets table with strategy support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT,
                bet_amount REAL NOT NULL,
                outcome TEXT CHECK(outcome IN ('win', 'loss')) NOT NULL,
                multiplier REAL,
                profit_loss REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(timestamp, multiplier, bet_amount)
            )
        """)

        # Create indexes for better query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_multipliers_session
            ON multipliers(session_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_multipliers_timestamp
            ON multipliers(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_timestamp
            ON bets(timestamp)
        """)

        self.conn.commit()

    def parse_log_file(
        self, log_path: str
    ) -> List[Tuple[datetime, float, Optional[int], Optional[int]]]:
        """
        Parse log file and extract round data
        Returns: List of (timestamp, multiplier, bettor_count, bank_balance)
        """
        rounds = []

        # Pattern for round entries:
        # 2025-12-17 03:40:44,459 - INFO - Round ended: 3.71x | Bettors: 22 | Bank: 1,000,220
        pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Round ended: ([\d.]+)x(?:\s*\|\s*Bettors:\s*(\d+))?(?:\s*\|\s*Bank:\s*([\d,]+))?"

        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    bettor_count = int(match.group(3)) if match.group(3) else None
                    bank_balance = (
                        int(match.group(4).replace(",", "")) if match.group(4) else None
                    )

                    # Parse timestamp
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    rounds.append((timestamp, multiplier, bettor_count, bank_balance))

        return rounds

    def detect_sessions_from_rounds(
        self, rounds: List[Tuple[datetime, float, Optional[int], Optional[int]]]
    ) -> List[Dict]:
        """
        Detect sessions based on time gaps between rounds
        Returns: List of session dictionaries
        """
        if not rounds:
            return []

        sessions = []
        current_session_rounds = []

        for i, round_data in enumerate(rounds):
            timestamp = round_data[0]

            if i == 0:
                # First round starts first session
                current_session_rounds.append(round_data)
            else:
                prev_timestamp = rounds[i - 1][0]
                time_gap = (timestamp - prev_timestamp).total_seconds() / 60

                if time_gap > self.max_gap_minutes:
                    # Gap detected - save current session and start new one
                    if current_session_rounds:
                        sessions.append(
                            self._create_session_dict(current_session_rounds)
                        )
                    current_session_rounds = [round_data]
                else:
                    # Continue current session
                    current_session_rounds.append(round_data)

        # Don't forget the last session
        if current_session_rounds:
            sessions.append(self._create_session_dict(current_session_rounds))

        return sessions

    def _create_session_dict(
        self, session_rounds: List[Tuple[datetime, float, Optional[int], Optional[int]]]
    ) -> Dict:
        """Create session dictionary from round data"""
        start_timestamp = session_rounds[0][0]
        end_timestamp = session_rounds[-1][0]

        # Get first and last bank balances (if available)
        start_balance = None
        end_balance = None

        for round_data in session_rounds:
            if round_data[3] is not None:
                start_balance = round_data[3]
                break

        for round_data in reversed(session_rounds):
            if round_data[3] is not None:
                end_balance = round_data[3]
                break

        return {
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "start_balance": start_balance,
            "end_balance": end_balance,
            "total_rounds": len(session_rounds),
            "rounds": session_rounds,
        }

    def create_session(self, session_dict: Dict) -> int:
        """
        Create a session in the database
        Returns: session_id
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO sessions (
                start_timestamp,
                end_timestamp,
                start_balance,
                end_balance,
                total_rounds
            ) VALUES (?, ?, ?, ?, ?)
        """,
            (
                session_dict["start_timestamp"],
                session_dict["end_timestamp"],
                session_dict["start_balance"],
                session_dict["end_balance"],
                session_dict["total_rounds"],
            ),
        )

        self.conn.commit()
        return cursor.lastrowid

    def import_rounds_with_sessions(self, log_path: str) -> Tuple[int, int]:
        """
        Import rounds from log file and automatically detect sessions
        All rounds are automatically assigned to sessions
        Returns: (rounds_imported, sessions_created)
        """
        print("Parsing log file...")
        rounds = self.parse_log_file(log_path)

        if not rounds:
            print("No rounds found in log file")
            return 0, 0

        print(f"Found {len(rounds)} rounds")

        print("Detecting sessions...")
        sessions = self.detect_sessions_from_rounds(rounds)

        print(f"Detected {len(sessions)} sessions")

        cursor = self.conn.cursor()
        rounds_imported = 0
        sessions_created = 0

        for session_idx, session_dict in enumerate(sessions, 1):
            print(f"\nProcessing session {session_idx}/{len(sessions)}...")
            print(f"  Start: {session_dict['start_timestamp']}")
            print(f"  End: {session_dict['end_timestamp']}")
            print(f"  Rounds: {session_dict['total_rounds']}")
            if session_dict["start_balance"]:
                print(f"  Start Balance: {session_dict['start_balance']:,}")
            if session_dict["end_balance"]:
                print(f"  End Balance: {session_dict['end_balance']:,}")
                if session_dict["start_balance"]:
                    profit = session_dict["end_balance"] - session_dict["start_balance"]
                    print(f"  Profit/Loss: {profit:+,.0f}")

            # Create session
            session_id = self.create_session(session_dict)
            sessions_created += 1

            # Import rounds for this session
            for timestamp, multiplier, bettor_count, bank_balance in session_dict[
                "rounds"
            ]:
                try:
                    cursor.execute(
                        """INSERT INTO multipliers
                           (multiplier, bettor_count, timestamp, session_id)
                           VALUES (?, ?, ?, ?)""",
                        (multiplier, bettor_count, timestamp, session_id),
                    )
                    rounds_imported += 1
                except sqlite3.IntegrityError:
                    # Skip duplicates (same timestamp and multiplier)
                    pass

            self.conn.commit()
            print(f"  ✓ Imported {len(session_dict['rounds'])} rounds")

        return rounds_imported, sessions_created

    def parse_bet_results(
        self, log_path: str
    ) -> List[Tuple[datetime, str, str, float, float, float]]:
        """
        Parse log file and extract bet results
        Returns: List of (timestamp, strategy_name, outcome, bet_amount, multiplier, profit_loss)
        """
        bets = []

        # Pattern for wins with strategy:
        # [StrategyName] ✓ WIN! 2.5x | Profit: +10000 | Strategy Total: 10000 | Global Total: 10000
        win_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - \[([^\]]+)\] ✓ WIN! ([\d.]+)x \| Profit: \+([\d.]+)"

        # Pattern for losses with strategy:
        # [StrategyName] ✗ LOSS! 1.5x | Loss: -10000 | Strategy Total: -10000 | Global Total: -10000
        loss_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - \[([^\]]+)\] ✗ LOSS! ([\d.]+)x \| Loss: -([\d.]+)"

        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                # Check for wins
                match = re.search(win_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    strategy_name = match.group(2)
                    multiplier = float(match.group(3))
                    profit = float(match.group(4))

                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    # Calculate bet amount from profit: bet_amount * (multiplier - 1) = profit
                    # So bet_amount = profit / (multiplier - 1)
                    # But we need to extract it from next line or calculate
                    # For now, we'll store profit as bet_amount for wins
                    bet_amount = profit / (multiplier - 1) if multiplier > 1 else profit

                    bets.append(
                        (
                            timestamp,
                            strategy_name,
                            "win",
                            bet_amount,
                            multiplier,
                            profit,
                        )
                    )
                    continue

                # Check for losses
                match = re.search(loss_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    strategy_name = match.group(2)
                    multiplier = float(match.group(3))
                    loss = float(match.group(4))

                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    # For losses, the loss IS the bet amount
                    bet_amount = loss

                    bets.append(
                        (
                            timestamp,
                            strategy_name,
                            "loss",
                            bet_amount,
                            multiplier,
                            -loss,
                        )
                    )

        return bets

    def import_bets(self, log_path: str) -> int:
        """
        Import bets from log file
        Returns: Number of bets imported
        """
        bets = self.parse_bet_results(log_path)

        cursor = self.conn.cursor()
        imported = 0

        for (
            timestamp,
            strategy_name,
            outcome,
            bet_amount,
            multiplier,
            profit_loss,
        ) in bets:
            try:
                cursor.execute(
                    """INSERT INTO bets
                       (strategy_name, bet_amount, outcome, multiplier, profit_loss, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        strategy_name,
                        bet_amount,
                        outcome,
                        multiplier,
                        profit_loss,
                        timestamp,
                    ),
                )
                imported += 1
            except sqlite3.IntegrityError:
                # Skip duplicates
                pass

        self.conn.commit()
        return imported

    def get_stats(self):
        """Get database statistics"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM multipliers")
        total_rounds = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM bets")
        total_bets = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sessions")
        total_sessions = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM multipliers")
        date_range = cursor.fetchone()

        return {
            "total_rounds": total_rounds,
            "total_bets": total_bets,
            "total_sessions": total_sessions,
            "first_round": date_range[0],
            "last_round": date_range[1],
        }

    def get_session_summary(self):
        """Get summary of all sessions"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                s.id,
                s.start_timestamp,
                s.end_timestamp,
                s.start_balance,
                s.end_balance,
                s.total_rounds,
                COUNT(m.id) as actual_rounds
            FROM sessions s
            LEFT JOIN multipliers m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.start_timestamp
        """)

        return cursor.fetchall()

    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import sys

    if len(sys.argv) < 2 or "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python import_logs.py <log_file_path> [options]")
        print("\nOptions:")
        print("  --db <path>           Database path (default: ./crasher_data.db)")
        print("  --new                 Create a fresh database (deletes existing)")
        print("  --show-sessions       Display session summary after import")
        print("  --gap <minutes>       Max gap in minutes between rounds (default: 3)")
        print("\nExamples:")
        print("  # Import log file and create database with sessions:")
        print("  python import_logs.py crasher_bot.log")
        print()
        print("  # Create fresh database from log:")
        print("  python import_logs.py crasher_bot.log --new")
        print()
        print("  # Import with custom session gap:")
        print("  python import_logs.py crasher_bot.log --gap 5")
        print()
        print("  # Show sessions after import:")
        print("  python import_logs.py crasher_bot.log --show-sessions")
        sys.exit(0)

    # Parse arguments
    log_path = None
    db_path = "./crasher_data.db"
    create_new = False
    show_sessions = False
    max_gap = 3

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        if arg == "--db":
            if i + 1 < len(sys.argv):
                db_path = sys.argv[i + 1]
                i += 2
            else:
                print("Error: --db requires a path")
                sys.exit(1)
        elif arg == "--new":
            create_new = True
            i += 1
        elif arg == "--show-sessions":
            show_sessions = True
            i += 1
        elif arg == "--gap":
            if i + 1 < len(sys.argv):
                max_gap = int(sys.argv[i + 1])
                i += 2
            else:
                print("Error: --gap requires a number")
                sys.exit(1)
        elif not arg.startswith("--"):
            log_path = arg
            i += 1
        else:
            i += 1

    if not log_path:
        print("\nError: Log file path required")
        print("Use --help for usage information")
        sys.exit(1)

    print("=" * 60)
    print("CRASHER BOT LOG IMPORTER")
    print("=" * 60)
    print(f"Log file: {log_path}")
    print(f"Database: {db_path}")
    if create_new:
        print("Mode: CREATE NEW DATABASE")
    print(f"Session gap threshold: {max_gap} minutes")
    print("-" * 60)

    # Create importer
    importer = LogImporter(db_path, create_new=create_new)
    importer.max_gap_minutes = max_gap

    try:
        # Import rounds with automatic session detection
        print("\nImporting rounds with automatic session detection...")
        rounds_imported, sessions_created = importer.import_rounds_with_sessions(
            log_path
        )
        print(f"\n✓ Imported {rounds_imported} rounds")
        print(f"✓ Created {sessions_created} sessions")

        # Import bets
        print("\nImporting bets...")
        bets_imported = importer.import_bets(log_path)
        print(f"✓ Imported {bets_imported} bets")

        # Show stats
        print("\n" + "=" * 60)
        print("DATABASE STATISTICS:")
        stats = importer.get_stats()
        print(f"  Total rounds: {stats['total_rounds']}")
        print(f"  Total bets: {stats['total_bets']}")
        print(f"  Total sessions: {stats['total_sessions']}")
        if stats["first_round"] and stats["last_round"]:
            print(f"  Date range: {stats['first_round']} to {stats['last_round']}")
        print("=" * 60)

        # Show session summary if requested
        if show_sessions and stats["total_sessions"] > 0:
            print("\nSESSION SUMMARY:")
            print("-" * 60)
            sessions = importer.get_session_summary()

            for session in sessions:
                session_id, start, end, start_bal, end_bal, total, actual = session
                print(f"\nSession {session_id}:")
                print(f"  Start: {start}")
                print(f"  End: {end}")
                if start_bal:
                    print(f"  Start Balance: {start_bal:,}")
                if end_bal:
                    print(f"  End Balance: {end_bal:,}")
                    if start_bal:
                        profit = end_bal - start_bal
                        print(f"  Profit/Loss: {profit:+,.0f}")
                print(f"  Rounds: {actual}")

    except FileNotFoundError:
        print(f"\n❌ Error: Log file not found: {log_path}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        importer.close()

    print("\n✓ Import completed successfully!")


if __name__ == "__main__":
    main()
#  python3 import_logs.py crasher_bot\(4\).log --new
# DELETE FROM multipliers WHERE timestamp >= "2025-12-21 07:11:38" AND timestamp <= "2025-12-21 07:15:14";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-23 01:18:05" AND timestamp <= "2025-12-23 01:18:29";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-24 04:41:56" AND timestamp <= "2025-12-24 04:43:06";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-23 18:56:01" AND timestamp <= "2025-12-23 18:56:20";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-24 03:37:55" AND timestamp <= "2025-12-24 03:38:48";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-24 03:49:28" AND timestamp <= "2025-12-24 03:49:55";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-24 12:06:05" AND timestamp <= "2025-12-24 12:06:37";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-22 16:46:04" AND timestamp <= "2025-12-22 16:46:41";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-23 16:44:50" AND timestamp <= "2025-12-23 16:45:20";
# DELETE FROM multipliers WHERE timestamp >= "2025-12-18 14:17:52" AND timestamp <= "2025-12-18 14:18:17";
