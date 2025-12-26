#!/usr/bin/env python3
"""
Log Importer for Crasher Bot
Parses log files and inserts round data into the database with session detection
"""

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class LogImporter:
    """Import round data from log files into the database"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path)
        self._ensure_tables()
        self.max_gap_minutes = 3  # Maximum gap between rounds in same session

    def _ensure_tables(self):
        """Ensure database tables exist"""
        cursor = self.conn.cursor()

        # Multipliers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                session_id INTEGER REFERENCES sessions(id)
            )
        """)

        # Bets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT,
                bet_amount REAL NOT NULL,
                outcome TEXT CHECK(outcome IN ('win', 'loss')),
                multiplier REAL,
                profit_loss REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Sessions table
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
            bank_balance = round_data[3]

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

    def import_rounds_with_sessions(
        self, log_path: str, skip_duplicates: bool = True
    ) -> Tuple[int, int]:
        """
        Import rounds from log file and automatically detect sessions
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

            # Create session
            session_id = self.create_session(session_dict)
            sessions_created += 1

            # Import rounds for this session
            for timestamp, multiplier, bettor_count, bank_balance in session_dict[
                "rounds"
            ]:
                if skip_duplicates:
                    # Check if this exact round exists
                    cursor.execute(
                        "SELECT COUNT(*) FROM multipliers WHERE timestamp = ? AND multiplier = ?",
                        (timestamp, multiplier),
                    )
                    if cursor.fetchone()[0] > 0:
                        continue

                cursor.execute(
                    """INSERT INTO multipliers
                       (multiplier, bettor_count, timestamp, session_id)
                       VALUES (?, ?, ?, ?)""",
                    (multiplier, bettor_count, timestamp, session_id),
                )
                rounds_imported += 1

            self.conn.commit()
            print(f"  ✓ Imported {len(session_dict['rounds'])} rounds")

        return rounds_imported, sessions_created

    def detect_sessions_for_existing_data(self) -> int:
        """
        Detect and assign sessions for existing data without session_id
        Returns: Number of sessions created
        """
        cursor = self.conn.cursor()

        # Get all rounds without session_id, ordered by timestamp
        cursor.execute("""
            SELECT id, multiplier, bettor_count, timestamp
            FROM multipliers
            WHERE session_id IS NULL
            ORDER BY timestamp ASC
        """)

        rows = cursor.fetchall()

        if not rows:
            print("No unassigned rounds found")
            return 0

        print(f"Found {len(rows)} unassigned rounds")
        print("Detecting sessions...")

        # Convert to round format
        rounds = []
        round_ids = []

        for row in rows:
            round_id, multiplier, bettor_count, timestamp_str = row
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            rounds.append((timestamp, multiplier, bettor_count, None))
            round_ids.append(round_id)

        # Detect sessions
        sessions = self.detect_sessions_from_rounds(rounds)
        print(f"Detected {len(sessions)} sessions")

        sessions_created = 0
        round_idx = 0

        for session_idx, session_dict in enumerate(sessions, 1):
            print(f"\nCreating session {session_idx}/{len(sessions)}...")
            print(f"  Start: {session_dict['start_timestamp']}")
            print(f"  End: {session_dict['end_timestamp']}")
            print(f"  Rounds: {session_dict['total_rounds']}")

            # Create session
            session_id = self.create_session(session_dict)
            sessions_created += 1

            # Assign session_id to rounds
            rounds_in_session = session_dict["total_rounds"]
            session_round_ids = round_ids[round_idx : round_idx + rounds_in_session]

            for rid in session_round_ids:
                cursor.execute(
                    "UPDATE multipliers SET session_id = ? WHERE id = ?",
                    (session_id, rid),
                )

            round_idx += rounds_in_session
            self.conn.commit()
            print(f"  ✓ Assigned session to {rounds_in_session} rounds")

        return sessions_created

    def import_rounds(self, log_path: str, skip_duplicates: bool = True) -> int:
        """
        Import rounds from log file (without session detection)
        Returns: Number of rounds imported
        """
        rounds = self.parse_log_file(log_path)

        cursor = self.conn.cursor()
        imported = 0

        for timestamp, multiplier, bettor_count, bank_balance in rounds:
            if skip_duplicates:
                # Check if this exact round exists (same timestamp and multiplier)
                cursor.execute(
                    "SELECT COUNT(*) FROM multipliers WHERE timestamp = ? AND multiplier = ?",
                    (timestamp, multiplier),
                )
                if cursor.fetchone()[0] > 0:
                    continue

            cursor.execute(
                "INSERT INTO multipliers (multiplier, bettor_count, timestamp) VALUES (?, ?, ?)",
                (multiplier, bettor_count, timestamp),
            )
            imported += 1

        self.conn.commit()
        return imported

    def parse_bet_results(
        self, log_path: str
    ) -> List[Tuple[datetime, str, float, float, float]]:
        """
        Parse log file and extract bet results
        Returns: List of (timestamp, outcome, bet_amount, multiplier, profit_loss)
        """
        bets = []

        # Pattern for wins:
        # SUCCESS: WIN! 2.5x | Profit: +10000 | Total: 10000
        win_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - SUCCESS: WIN! ([\d.]+)x \| Profit: \+([\d.]+) \| Total: ([-\d.]+)"

        # Pattern for losses:
        # ERROR: LOSS! 1.5x | Loss: -10000 | Total: -10000
        loss_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - ERROR: LOSS! ([\d.]+)x \| Loss: -([\d.]+) \| Total: ([-\d.]+)"

        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                # Check for wins
                match = re.search(win_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    profit = float(match.group(3))

                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    bets.append((timestamp, "win", multiplier, profit))
                    continue

                # Check for losses
                match = re.search(loss_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    loss = float(match.group(3))

                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    bets.append((timestamp, "loss", multiplier, loss))

        return bets

    def import_bets(self, log_path: str, skip_duplicates: bool = True) -> int:
        """
        Import bets from log file
        Returns: Number of bets imported
        """
        bets = self.parse_bet_results(log_path)

        cursor = self.conn.cursor()
        imported = 0

        for timestamp, outcome, multiplier, amount in bets:
            if skip_duplicates:
                # Check if this exact bet exists
                cursor.execute(
                    "SELECT COUNT(*) FROM bets WHERE timestamp = ? AND multiplier = ?",
                    (timestamp, multiplier),
                )
                if cursor.fetchone()[0] > 0:
                    continue

            # Calculate bet amount and profit/loss
            if outcome == "win":
                bet_amount = amount
                profit_loss = amount
            else:
                bet_amount = amount
                profit_loss = -amount

            cursor.execute(
                "INSERT INTO bets (bet_amount, outcome, multiplier, profit_loss, timestamp) VALUES (?, ?, ?, ?, ?)",
                (bet_amount, outcome, multiplier, profit_loss, timestamp),
            )
            imported += 1

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

        cursor.execute("SELECT COUNT(*) FROM multipliers WHERE session_id IS NULL")
        unassigned_rounds = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM multipliers")
        date_range = cursor.fetchone()

        return {
            "total_rounds": total_rounds,
            "total_bets": total_bets,
            "total_sessions": total_sessions,
            "unassigned_rounds": unassigned_rounds,
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
        print("  --with-sessions       Import rounds and auto-detect sessions")
        print("  --detect-sessions     Detect sessions for existing unassigned data")
        print("  --show-sessions       Display session summary")
        print("\nExamples:")
        print("  # Import with automatic session detection:")
        print("  python import_logs.py crasher_bot.log --with-sessions")
        print()
        print("  # Import without sessions (old behavior):")
        print("  python import_logs.py crasher_bot.log")
        print()
        print("  # Detect sessions for existing data:")
        print("  python import_logs.py --detect-sessions --db ./crasher_data.db")
        print()
        print("  # Show session summary:")
        print("  python import_logs.py --show-sessions --db ./crasher_data.db")
        sys.exit(0)

    # Parse arguments
    log_path = None
    db_path = "./crasher_data.db"
    with_sessions = False
    detect_sessions = False
    show_sessions = False

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
        elif arg == "--with-sessions":
            with_sessions = True
            i += 1
        elif arg == "--detect-sessions":
            detect_sessions = True
            i += 1
        elif arg == "--show-sessions":
            show_sessions = True
            i += 1
        elif not arg.startswith("--"):
            log_path = arg
            i += 1
        else:
            i += 1

    print("=" * 60)
    print("CRASHER BOT LOG IMPORTER")
    print("=" * 60)
    print(f"Database: {db_path}")

    importer = LogImporter(db_path)

    try:
        # Show sessions mode
        if show_sessions:
            print("\nSESSION SUMMARY:")
            print("-" * 60)
            sessions = importer.get_session_summary()

            if not sessions:
                print("No sessions found in database")
            else:
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
                    print(f"  Rounds: {actual} (recorded: {total})")

            stats = importer.get_stats()
            print("\n" + "=" * 60)
            print("OVERALL STATISTICS:")
            print(f"  Total Sessions: {stats['total_sessions']}")
            print(f"  Total Rounds: {stats['total_rounds']}")
            print(f"  Unassigned Rounds: {stats['unassigned_rounds']}")
            print("=" * 60)

            importer.close()
            return

        # Detect sessions for existing data
        if detect_sessions:
            print("\nDetecting sessions for existing data...")
            print("-" * 60)
            sessions_created = importer.detect_sessions_for_existing_data()
            print(f"\n✓ Created {sessions_created} sessions")

            stats = importer.get_stats()
            print("\n" + "=" * 60)
            print("DATABASE STATISTICS:")
            print(f"  Total rounds: {stats['total_rounds']}")
            print(f"  Total sessions: {stats['total_sessions']}")
            print(f"  Unassigned rounds: {stats['unassigned_rounds']}")
            print("=" * 60)

            importer.close()
            return

        # Import mode
        if not log_path:
            print("\nError: Log file path required for import")
            print("Use --help for usage information")
            sys.exit(1)

        print(f"Log file: {log_path}")
        print("-" * 60)

        if with_sessions:
            # Import with session detection
            print("\nImporting with automatic session detection...")
            rounds_imported, sessions_created = importer.import_rounds_with_sessions(
                log_path, skip_duplicates=True
            )
            print(f"\n✓ Imported {rounds_imported} rounds")
            print(f"✓ Created {sessions_created} sessions")
        else:
            # Import without sessions (old behavior)
            print("\nImporting rounds (without session detection)...")
            rounds_imported = importer.import_rounds(log_path, skip_duplicates=True)
            print(f"✓ Imported {rounds_imported} rounds")

            print("\nImporting bets...")
            bets_imported = importer.import_bets(log_path, skip_duplicates=True)
            print(f"✓ Imported {bets_imported} bets")

        # Show stats
        print("\n" + "=" * 60)
        print("DATABASE STATISTICS:")
        stats = importer.get_stats()
        print(f"  Total rounds: {stats['total_rounds']}")
        print(f"  Total bets: {stats['total_bets']}")
        print(f"  Total sessions: {stats['total_sessions']}")
        print(f"  Unassigned rounds: {stats['unassigned_rounds']}")
        if stats["first_round"] and stats["last_round"]:
            print(f"  Date range: {stats['first_round']} to {stats['last_round']}")
        print("=" * 60)

        if stats["unassigned_rounds"] > 0:
            print("\n⚠️  You have unassigned rounds.")
            print("Run with --detect-sessions to assign them:")
            print(f"  python import_logs.py --detect-sessions --db {db_path}")

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
#  python3 import_logs.py crasher_bot\(4\).log --with-sessions --db ../crasher_data.db --show-sessions
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
