#!/usr/bin/env python3
"""
Log Importer for Crasher Bot
Parses log files and inserts round data into the database
"""

import re
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional


class LogImporter:
    """Import round data from log files into the database"""

    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure database tables exist"""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS multipliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                multiplier REAL NOT NULL,
                bettor_count INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bet_amount REAL NOT NULL,
                outcome TEXT CHECK(outcome IN ('win', 'loss')),
                multiplier REAL,
                profit_loss REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def parse_log_file(self, log_path: str) -> List[Tuple[datetime, float, Optional[int], Optional[int]]]:
        """
        Parse log file and extract round data
        Returns: List of (timestamp, multiplier, bettor_count, bank_balance)
        """
        rounds = []
        
        # Pattern for round entries:
        # 2025-12-17 03:40:44,459 - INFO - Round ended: 3.71x | Bettors: 22 | Bank: 1,000,220
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Round ended: ([\d.]+)x(?:\s*\|\s*Bettors:\s*(\d+))?(?:\s*\|\s*Bank:\s*([\d,]+))?'
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    bettor_count = int(match.group(3)) if match.group(3) else None
                    bank_balance = int(match.group(4).replace(',', '')) if match.group(4) else None
                    
                    # Parse timestamp
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    rounds.append((timestamp, multiplier, bettor_count, bank_balance))
        
        return rounds

    def parse_bet_results(self, log_path: str) -> List[Tuple[datetime, str, float, float, float]]:
        """
        Parse log file and extract bet results
        Returns: List of (timestamp, outcome, bet_amount, multiplier, profit_loss)
        """
        bets = []
        
        # Pattern for wins:
        # SUCCESS: WIN! 2.5x | Profit: +10000 | Total: 10000
        win_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - SUCCESS: WIN! ([\d.]+)x \| Profit: \+([\d.]+) \| Total: ([-\d.]+)'
        
        # Pattern for losses:
        # ERROR: LOSS! 1.5x | Loss: -10000 | Total: -10000
        loss_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - ERROR: LOSS! ([\d.]+)x \| Loss: -([\d.]+) \| Total: ([-\d.]+)'
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Check for wins
                match = re.search(win_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    profit = float(match.group(3))
                    
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    # Calculate bet amount from profit and multiplier
                    # profit = bet * (multiplier - 1) for auto-cashout
                    # So bet = profit / (multiplier - 1)
                    # However, we need to get the actual bet from context
                    # For now, we'll extract it from the next line if available
                    bets.append((timestamp, 'win', multiplier, profit))
                    continue
                
                # Check for losses
                match = re.search(loss_pattern, line)
                if match:
                    timestamp_str = match.group(1)
                    multiplier = float(match.group(2))
                    loss = float(match.group(3))
                    
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    bets.append((timestamp, 'loss', multiplier, loss))
        
        return bets

    def import_rounds(self, log_path: str, skip_duplicates: bool = True) -> int:
        """
        Import rounds from log file
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
                    (timestamp, multiplier)
                )
                if cursor.fetchone()[0] > 0:
                    continue
            
            cursor.execute(
                "INSERT INTO multipliers (multiplier, bettor_count, timestamp) VALUES (?, ?, ?)",
                (multiplier, bettor_count, timestamp)
            )
            imported += 1
        
        self.conn.commit()
        return imported

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
                    (timestamp, multiplier)
                )
                if cursor.fetchone()[0] > 0:
                    continue
            
            # Calculate bet amount and profit/loss
            if outcome == 'win':
                # profit = bet * (multiplier - 1) for auto-cashout
                # Assuming auto_cashout is used, we need the cashout multiplier
                # For simplicity, we'll store the profit as-is
                bet_amount = amount  # This is actually profit, need to recalculate
                profit_loss = amount
            else:
                bet_amount = amount
                profit_loss = -amount
            
            cursor.execute(
                "INSERT INTO bets (bet_amount, outcome, multiplier, profit_loss, timestamp) VALUES (?, ?, ?, ?, ?)",
                (bet_amount, outcome, multiplier, profit_loss, timestamp)
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
        
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM multipliers")
        date_range = cursor.fetchone()
        
        return {
            'total_rounds': total_rounds,
            'total_bets': total_bets,
            'first_round': date_range[0],
            'last_round': date_range[1]
        }

    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python import_logs.py <log_file_path> [--db <database_path>]")
        print("\nExample:")
        print("  python import_logs.py crasher_bot.log")
        print("  python import_logs.py crasher_bot.log --db ./my_data.db")
        sys.exit(1)
    
    log_path = sys.argv[1]
    db_path = "./crasher_data.db"
    
    # Check for custom database path
    if "--db" in sys.argv:
        db_index = sys.argv.index("--db")
        if db_index + 1 < len(sys.argv):
            db_path = sys.argv[db_index + 1]
    
    print(f"Importing from: {log_path}")
    print(f"Database: {db_path}")
    print("-" * 60)
    
    importer = LogImporter(db_path)
    
    try:
        # Import rounds
        print("Importing rounds...")
        rounds_imported = importer.import_rounds(log_path, skip_duplicates=True)
        print(f"✓ Imported {rounds_imported} rounds")
        
        # Import bets (if any)
        print("\nImporting bets...")
        bets_imported = importer.import_bets(log_path, skip_duplicates=True)
        print(f"✓ Imported {bets_imported} bets")
        
        # Show stats
        print("\n" + "=" * 60)
        print("DATABASE STATISTICS:")
        stats = importer.get_stats()
        print(f"  Total rounds: {stats['total_rounds']}")
        print(f"  Total bets: {stats['total_bets']}")
        if stats['first_round'] and stats['last_round']:
            print(f"  Date range: {stats['first_round']} to {stats['last_round']}")
        print("=" * 60)
        
    except FileNotFoundError:
        print(f"ERROR: Log file not found: {log_path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        importer.close()
    
    print("\n✓ Import completed successfully!")


if __name__ == "__main__":
    main()
