#!/usr/bin/env python3
"""
Database Migration: Add Sessions Support
Adds sessions table and session_id column to multipliers table
"""

import sqlite3
import sys
from datetime import datetime


def migrate_database(db_path: str = "./crasher_data.db"):
    """Add sessions table and migrate existing data"""
    
    print(f"Migrating database: {db_path}")
    print("=" * 60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if sessions table already exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='sessions'
        """)
        
        if cursor.fetchone():
            print("⚠️  Sessions table already exists!")
            response = input("Do you want to recreate it? This will delete existing sessions (y/N): ")
            if response.lower() != 'y':
                print("Migration cancelled.")
                return False
            
            # Drop existing sessions table
            cursor.execute("DROP TABLE sessions")
            print("✓ Dropped existing sessions table")
        
        # Create sessions table
        print("\nCreating sessions table...")
        cursor.execute("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_timestamp DATETIME NOT NULL,
                end_timestamp DATETIME,
                start_balance REAL,
                end_balance REAL,
                total_rounds INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created sessions table")
        
        # Check if session_id column exists in multipliers
        cursor.execute("PRAGMA table_info(multipliers)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'session_id' not in columns:
            print("\nAdding session_id column to multipliers table...")
            cursor.execute("""
                ALTER TABLE multipliers 
                ADD COLUMN session_id INTEGER REFERENCES sessions(id)
            """)
            print("✓ Added session_id column")
        else:
            print("\n⚠️  session_id column already exists in multipliers table")
        
        # Check if strategy_name column exists in bets (for multi-strategy support)
        cursor.execute("PRAGMA table_info(bets)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'strategy_name' not in columns:
            print("\nAdding strategy_name column to bets table...")
            cursor.execute("""
                ALTER TABLE bets 
                ADD COLUMN strategy_name TEXT
            """)
            print("✓ Added strategy_name column to bets")
        
        conn.commit()
        
        # Get statistics
        cursor.execute("SELECT COUNT(*) FROM multipliers")
        total_rounds = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM multipliers WHERE session_id IS NULL")
        unassigned_rounds = cursor.fetchone()[0]
        
        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY:")
        print(f"  Total rounds in database: {total_rounds}")
        print(f"  Rounds without session: {unassigned_rounds}")
        print("=" * 60)
        
        if unassigned_rounds > 0:
            print("\n⚠️  You have rounds without session assignments.")
            print("Run the import script with --detect-sessions to assign them:")
            print(f"  python import_logs.py crasher_bot.log --detect-sessions")
        
        print("\n✓ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        conn.close()


def main():
    db_path = "./crasher_data.db"
    
    if len(sys.argv) >= 2:
        db_path = sys.argv[1]
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python migrate_add_sessions.py [database_path]")
        print("\nExample:")
        print("  python migrate_add_sessions.py")
        print("  python migrate_add_sessions.py ./crasher_data.db")
        return
    
    migrate_database(db_path)


if __name__ == "__main__":
    main()
