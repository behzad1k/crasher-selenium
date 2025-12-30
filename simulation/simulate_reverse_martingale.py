#!/usr/bin/env python3
"""
Classic Martingale Strategy Simulator

Simulates a strategy that waits for N consecutive rounds ABOVE a threshold,
then bets on the NEXT round (assuming it will be below threshold).

Strategy:
1. Wait for N consecutive rounds >= threshold
2. Place bet expecting next round < threshold
3. If LOSS: Double bet and wait for next N consecutive trigger
4. If WIN: Reset to base bet
5. Exclude bet rounds from future trigger windows

Usage:
    python3 simulate_classic_martingale.py 2.0 --base-bet 1000
    python3 simulate_classic_martingale.py 2.0 --base-bet 1000 --trigger-count 3
    python3 simulate_classic_martingale.py 2.0 --base-bet 1000 --trigger-count 3 --multiplier 2.0
    python3 simulate_classic_martingale.py 3.0 --base-bet 500 --all-sessions --detailed
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple


@dataclass
class Bet:
    """Record of a single bet"""

    session_id: int
    round_number: int
    bet_amount: float
    multiplier: float
    won: bool
    profit_loss: float
    consecutive_losses: int
    trigger_multipliers: List[float]  # The N rounds that triggered this bet
    trigger_round_indices: List[int]  # The actual round indices of the trigger


@dataclass
class SessionResult:
    """Results for a single session"""

    session_id: int
    total_rounds: int
    total_bets: int
    wins: int
    losses: int
    profit_loss: float
    max_bet: float
    max_consecutive_losses: int
    bets: List[Bet]


def get_sessions(db_path: str) -> List[int]:
    """Get all session IDs from database"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT session_id
        FROM multipliers
        WHERE session_id IS NOT NULL
        ORDER BY session_id
    """)

    sessions = [row[0] for row in cursor.fetchall()]
    conn.close()

    return sessions


def get_multipliers(db_path: str, session_id: int = None) -> List[Tuple[int, float]]:
    """
    Get multipliers from database
    Returns list of (session_id, multiplier) tuples in chronological order
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if session_id:
        query = """
            SELECT session_id, multiplier
            FROM multipliers
            WHERE session_id = ?
            ORDER BY id ASC
        """
        cursor.execute(query, (session_id,))
    else:
        # All sessions
        query = """
            SELECT session_id, multiplier
            FROM multipliers
            WHERE session_id IS NOT NULL
            ORDER BY id ASC
        """
        cursor.execute(query)

    results = cursor.fetchall()
    conn.close()

    return results


def simulate_session(
    multipliers: List[float],
    session_id: int,
    threshold: float,
    trigger_count: int,
    base_bet: float,
    bet_multiplier: float,
    auto_cashout: float = 2.0,
) -> SessionResult:
    """
    Simulate the CLASSIC martingale strategy on a session

    Strategy:
    - Wait for trigger_count consecutive rounds >= threshold
    - Place bet expecting next round < threshold (< auto_cashout)
    - LOSS: Double bet, wait for next trigger
    - WIN: Reset to base bet, wait for next trigger
    - Exclude bet rounds from future trigger windows
    """
    bets = []
    excluded_rounds: Set[int] = (
        set()
    )  # Rounds we've bet on (cannot be part of future triggers)
    current_bet = base_bet
    consecutive_losses = 0

    i = 0
    while i < len(multipliers):
        # Check for trigger: N consecutive rounds >= threshold
        if i + trigger_count <= len(multipliers):
            # Get window indices
            window_indices = list(range(i, i + trigger_count))

            # Skip if any round in the window has been bet on
            if any(idx in excluded_rounds for idx in window_indices):
                i += 1
                continue

            # Get the multipliers for this window
            window = [multipliers[idx] for idx in window_indices]

            # All rounds in window must be >= threshold
            if all(m >= threshold for m in window):
                # Trigger found! Place bet on the NEXT round
                bet_round_idx = i + trigger_count

                # Check if we have a round to bet on
                if bet_round_idx >= len(multipliers):
                    break  # Ran out of data

                next_mult = multipliers[bet_round_idx]

                # Check if we won (we bet that next round will REACH auto_cashout)
                # So we WIN if next_mult >= auto_cashout (we successfully cashed out)
                won = next_mult >= auto_cashout

                if won:
                    # We cashed out at our target multiplier
                    profit = current_bet * (auto_cashout - 1)
                else:
                    # Round crashed before reaching our cashout target
                    profit = -current_bet

                # Record bet with CURRENT consecutive_losses (before updating)
                bet = Bet(
                    session_id=session_id,
                    round_number=bet_round_idx,
                    bet_amount=current_bet,
                    multiplier=next_mult,
                    won=won,
                    profit_loss=profit,
                    consecutive_losses=consecutive_losses,  # Record losses BEFORE this bet
                    trigger_multipliers=window[:],
                    trigger_round_indices=window_indices[:],
                )

                # Now update for next bet
                if won:
                    consecutive_losses = 0
                    next_bet = base_bet  # Reset to base bet after win
                else:
                    consecutive_losses += 1
                    next_bet = current_bet * bet_multiplier  # Increase bet after loss
                bets.append(bet)

                # Mark the bet round as excluded
                excluded_rounds.add(bet_round_idx)

                # Update current bet for next time
                current_bet = next_bet

                # Move past the trigger window (but not the bet round)
                # This allows overlapping triggers as long as they don't include bet rounds
                i = i + 1
                continue

        i += 1

    # Calculate session stats
    total_bets = len(bets)
    wins = sum(1 for b in bets if b.won)
    losses = total_bets - wins
    profit_loss = sum(b.profit_loss for b in bets)
    max_bet = max((b.bet_amount for b in bets), default=0)
    max_consecutive_losses = max((b.consecutive_losses for b in bets), default=0)

    return SessionResult(
        session_id=session_id,
        total_rounds=len(multipliers),
        total_bets=total_bets,
        wins=wins,
        losses=losses,
        profit_loss=profit_loss,
        max_bet=max_bet,
        max_consecutive_losses=max_consecutive_losses,
        bets=bets,
    )


def print_session_summary(result: SessionResult, detailed: bool = False):
    """Print summary for a single session"""
    win_rate = (result.wins / result.total_bets * 100) if result.total_bets > 0 else 0

    print(f"\n{'=' * 80}")
    print(f"SESSION #{result.session_id}")
    print(f"{'=' * 80}")
    print(f"Total Rounds: {result.total_rounds}")
    print(f"Total Bets: {result.total_bets}")
    print(f"Wins: {result.wins} ({win_rate:.1f}%)")
    print(f"Losses: {result.losses}")
    print(f"Max Consecutive Losses: {result.max_consecutive_losses}")
    print(f"Max Bet: ${result.max_bet:,.0f}")

    profit_symbol = "+" if result.profit_loss >= 0 else ""
    profit_color = "✅" if result.profit_loss >= 0 else "❌"
    print(f"Profit/Loss: {profit_color} {profit_symbol}${result.profit_loss:,.0f}")

    if detailed and result.bets:
        print(f"\n{'─' * 80}")
        print(f"DETAILED BETS:")
        print(f"{'─' * 80}")

        for i, bet in enumerate(result.bets, 1):
            trigger_str = ", ".join(f"{m:.2f}x" for m in bet.trigger_multipliers)
            trigger_rounds_str = ", ".join(f"#{r}" for r in bet.trigger_round_indices)
            outcome = "WIN" if bet.won else "LOSS"
            outcome_symbol = "✅" if bet.won else "❌"

            print(f"\nBet #{i}:")
            print(f"  Trigger Rounds: {trigger_rounds_str}")
            print(f"  Trigger Values: [{trigger_str}]")
            print(f"  Bet Round: #{bet.round_number}")
            print(f"  Bet Amount: ${bet.bet_amount:,.0f}")
            print(f"  Actual Multiplier: {bet.multiplier:.2f}x")
            print(f"  Result: {outcome_symbol} {outcome}")
            print(f"  Profit/Loss: {bet.profit_loss:+,.0f}")
            print(f"  Consecutive Losses: {bet.consecutive_losses}")


def print_overall_summary(results: List[SessionResult], args):
    """Print overall summary across all sessions"""
    print(f"\n{'=' * 80}")
    print(f"OVERALL SUMMARY - ALL SESSIONS")
    print(f"{'=' * 80}")

    total_sessions = len(results)
    total_rounds = sum(r.total_rounds for r in results)
    total_bets = sum(r.total_bets for r in results)
    total_wins = sum(r.wins for r in results)
    total_losses = sum(r.losses for r in results)
    total_profit = sum(r.profit_loss for r in results)

    profitable_sessions = sum(1 for r in results if r.profit_loss > 0)
    losing_sessions = sum(1 for r in results if r.profit_loss < 0)
    breakeven_sessions = sum(1 for r in results if r.profit_loss == 0)

    win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0
    avg_profit_per_session = total_profit / total_sessions if total_sessions > 0 else 0
    avg_bets_per_session = total_bets / total_sessions if total_sessions > 0 else 0

    max_consecutive_losses_overall = max(
        (r.max_consecutive_losses for r in results), default=0
    )
    max_bet_overall = max((r.max_bet for r in results), default=0)

    print(f"\nStrategy Parameters:")
    print(f"  Threshold: >= {args.threshold}x")
    print(f"  Trigger Count: {args.trigger_count} consecutive rounds")
    print(f"  Base Bet: ${args.base_bet:,.0f}")
    print(f"  Bet Multiplier: {args.multiplier}x (on LOSS - classic martingale)")
    print(f"  Cashout Target: {args.cashout}x")
    print(f"  Win Condition: Multiplier reaches {args.cashout}x or higher")

    print(f"\nData Summary:")
    print(f"  Total Sessions: {total_sessions}")
    print(f"  Total Rounds: {total_rounds:,}")
    print(f"  Total Bets Placed: {total_bets:,}")
    print(f"  Betting Frequency: {(total_bets / total_rounds * 100):.2f}% of rounds")

    print(f"\nResults:")
    print(f"  Total Wins: {total_wins} ({win_rate:.1f}%)")
    print(f"  Total Losses: {total_losses}")
    print(f"  Win Rate: {win_rate:.1f}%")

    print(f"\nSession Performance:")
    print(
        f"  Profitable Sessions: {profitable_sessions} ({profitable_sessions / total_sessions * 100:.1f}%)"
    )
    print(
        f"  Losing Sessions: {losing_sessions} ({losing_sessions / total_sessions * 100:.1f}%)"
    )
    print(f"  Breakeven Sessions: {breakeven_sessions}")

    print(f"\nFinancials:")
    profit_symbol = "+" if total_profit >= 0 else ""
    profit_emoji = "✅" if total_profit >= 0 else "❌"
    print(f"  Total Profit/Loss: {profit_emoji} {profit_symbol}${total_profit:,.0f}")
    print(f"  Avg Per Session: {profit_symbol}${avg_profit_per_session:,.0f}")
    print(
        f"  Avg Per Bet: {profit_symbol}${(total_profit / total_bets):,.0f}"
        if total_bets > 0
        else "  Avg Per Bet: N/A"
    )

    print(f"\nRisk Metrics:")
    print(f"  Max Consecutive Losses: {max_consecutive_losses_overall}")
    print(f"  Max Bet Required: ${max_bet_overall:,.0f}")
    print(f"  Avg Bets Per Session: {avg_bets_per_session:.1f}")

    # Required bankroll
    required_bankroll = max_bet_overall * 2  # 2x for safety
    print(f"  Recommended Bankroll: ${required_bankroll:,.0f} (2x max bet)")

    # ROI
    total_wagered = sum(bet.bet_amount for r in results for bet in r.bets)
    roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0
    print(f"  Total Wagered: ${total_wagered:,.0f}")
    print(f"  ROI: {roi:+.2f}%")


def print_insights(results: List[SessionResult], args):
    """Print strategic insights based on simulation"""
    print(f"\n{'=' * 80}")
    print(f"STRATEGIC INSIGHTS")
    print(f"{'=' * 80}")

    total_bets = sum(r.total_bets for r in results)
    total_wins = sum(r.wins for r in results)
    total_profit = sum(r.profit_loss for r in results)
    win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0

    # Analyze win/loss patterns
    all_bets = [bet for r in results for bet in r.bets]

    if all_bets:
        # Group by consecutive losses
        by_loss_count = {}
        for bet in all_bets:
            count = bet.consecutive_losses
            if count not in by_loss_count:
                by_loss_count[count] = {"wins": 0, "losses": 0, "total": 0}
            by_loss_count[count]["total"] += 1
            if bet.won:
                by_loss_count[count]["wins"] += 1
            else:
                by_loss_count[count]["losses"] += 1

        print(f"\n1. Win Rate by Position in Martingale Sequence:")
        for count in sorted(by_loss_count.keys())[:10]:
            data = by_loss_count[count]
            rate = (data["wins"] / data["total"] * 100) if data["total"] > 0 else 0
            bet_amount = args.base_bet * (args.multiplier**count)
            print(
                f"   After {count} losses (${bet_amount:,.0f}): {data['wins']}/{data['total']} wins ({rate:.1f}%)"
            )

    # Strategy effectiveness
    print(f"\n2. Strategy Effectiveness:")
    if win_rate > 50:
        print(f"   ✅ Win rate ({win_rate:.1f}%) is above 50% - Strategy has an edge!")
    else:
        print(f"   ❌ Win rate ({win_rate:.1f}%) is below 50% - House edge is winning")

    if total_profit > 0:
        print(f"   ✅ Overall profitable: +${total_profit:,.0f}")
    else:
        print(f"   ❌ Overall losing: ${total_profit:,.0f}")

    # Risk assessment
    max_loss = max((r.max_consecutive_losses for r in results), default=0)
    max_bet = max((r.max_bet for r in results), default=0)

    print(f"\n3. Risk Assessment:")
    if max_loss > 5:
        print(f"   ⚠️  Max {max_loss} consecutive losses detected!")
        print(f"      Required bankroll to survive: ${max_bet * 2:,.0f}")
    else:
        print(f"   ✅ Manageable risk: Max {max_loss} consecutive losses")

    # Bankruptcy risk
    print(f"\n4. Bankruptcy Risk Analysis:")
    print(f"   With base bet ${args.base_bet:,.0f} and multiplier {args.multiplier}x:")
    for i in range(1, 11):
        required_bet = args.base_bet * (args.multiplier**i)
        print(f"      Loss #{i}: Next bet would be ${required_bet:,.0f}")
        if required_bet > 100000:
            print(f"      ⚠️  Exceeds reasonable bankroll at loss #{i}")
            break

    # Recommendations
    print(f"\n5. Recommendations:")

    if win_rate < 50:
        print(f"   💡 Consider adjusting trigger_count (current: {args.trigger_count})")
        print(
            f"      Try: --trigger-count {args.trigger_count + 1} or {args.trigger_count + 2}"
        )

    if max_loss > 7:
        print(f"   💡 High risk of large losses. Consider:")
        print(f"      - Lower bet multiplier (current: {args.multiplier}x)")
        print(f"      - Try: --multiplier 1.5 for slower progression")
        print(f"      - Or use a stop-loss after N consecutive losses")

    if total_profit > 0 and win_rate > 55:
        print(f"   ✅ Strategy appears profitable!")
        print(f"   💡 Consider backtesting on more data to confirm")

    # Frequency analysis
    total_rounds = sum(r.total_rounds for r in results)
    betting_frequency = (total_bets / total_rounds * 100) if total_rounds > 0 else 0

    print(f"\n6. Betting Frequency:")
    print(f"   You bet on {betting_frequency:.2f}% of rounds")

    if betting_frequency < 1:
        print(
            f"   💡 Very conservative - only {total_bets} bets in {total_rounds:,} rounds"
        )
    elif betting_frequency > 10:
        print(f"   ⚠️  High frequency - consider higher trigger_count")
    else:
        print(f"   ✅ Reasonable betting frequency")


def main():
    parser = argparse.ArgumentParser(
        description="Simulate classic martingale strategy on historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Your requested strategy: 3 consecutive rounds >=2.0x, bet $1000, double on loss
  %(prog)s 2.0 --base-bet 1000 --trigger-count 3 --multiplier 2.0

  # More conservative: 4 consecutive, smaller multiplier
  %(prog)s 2.0 --base-bet 1000 --trigger-count 4 --multiplier 1.5

  # All sessions with details
  %(prog)s 2.0 --base-bet 1000 --all-sessions --detailed
        """,
    )

    parser.add_argument(
        "threshold", type=float, help="Multiplier threshold (e.g., 2.0 for >= 2.0x)"
    )

    parser.add_argument(
        "--base-bet", type=float, default=1000, help="Base bet amount (default: 1000)"
    )

    parser.add_argument(
        "--trigger-count",
        type=int,
        default=3,
        help="Number of consecutive rounds >= threshold to trigger bet (default: 3)",
    )

    parser.add_argument(
        "--multiplier",
        type=float,
        default=2.0,
        help="Bet multiplier on LOSS - classic martingale progression (default: 2.0)",
    )

    parser.add_argument(
        "--cashout",
        type=float,
        default=2.0,
        help="Cashout target multiplier - we win if round reaches this or higher (default: 2.0)",
    )

    parser.add_argument("--session", type=int, help="Simulate specific session only")

    parser.add_argument(
        "--all-sessions", action="store_true", help="Simulate all sessions (default)"
    )

    parser.add_argument(
        "--detailed", action="store_true", help="Show detailed bet information"
    )

    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)",
    )

    args = parser.parse_args()

    # Validate args
    if args.threshold < 1.0:
        print(f"ERROR: Threshold must be >= 1.0")
        sys.exit(1)

    if args.base_bet <= 0:
        print(f"ERROR: Base bet must be > 0")
        sys.exit(1)

    if args.trigger_count < 1:
        print(f"ERROR: Trigger count must be >= 1")
        sys.exit(1)

    if args.multiplier < 1.0:
        print(f"ERROR: Multiplier must be >= 1.0")
        sys.exit(1)

    # Get sessions to simulate
    try:
        if args.session:
            sessions = [args.session]
        else:
            sessions = get_sessions(args.db)
            if not sessions:
                print(f"ERROR: No sessions found in database")
                sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to read database: {e}")
        sys.exit(1)

    print(f"\n{'=' * 80}")
    print(f"CLASSIC MARTINGALE STRATEGY SIMULATION")
    print(f"{'=' * 80}")
    print(
        f"\nStrategy: Wait for {args.trigger_count} consecutive rounds >= {args.threshold}x,"
    )
    print(f"          then bet on the NEXT round with cashout at {args.cashout}x")
    print(f"          WIN: If multiplier reaches {args.cashout}x or higher")
    print(f"          LOSS: If multiplier crashes before {args.cashout}x")
    print(f"          After LOSS: Multiply bet by {args.multiplier}x")
    print(f"          After WIN: Reset to base bet ${args.base_bet:,.0f}")
    print(f"          Rounds you bet on are excluded from future triggers")
    print(f"\nSimulating {len(sessions)} session(s)...")
    print(f"{'=' * 80}")

    # Simulate each session
    results = []
    for session_id in sessions:
        data = get_multipliers(args.db, session_id)
        multipliers = [m for _, m in data]

        if not multipliers:
            continue

        result = simulate_session(
            multipliers=multipliers,
            session_id=session_id,
            threshold=args.threshold,
            trigger_count=args.trigger_count,
            base_bet=args.base_bet,
            bet_multiplier=args.multiplier,
            auto_cashout=args.cashout,
        )

        results.append(result)

        # Print session summary
        if args.session or args.detailed:
            print_session_summary(result, args.detailed)

    # Print overall summary
    if len(results) > 1 or not args.detailed:
        print_overall_summary(results, args)

    # Print insights
    print_insights(results, args)

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    main()
