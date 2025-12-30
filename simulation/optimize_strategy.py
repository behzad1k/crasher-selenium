#!/usr/bin/env python3
"""
Classic Martingale Strategy Optimizer

Tests multiple parameter combinations to find the best profit/bankroll ratio.
Uses the classic martingale strategy (double on loss, reset on win).

The optimizer evaluates strategies based on:
1. Profit/Bankroll Ratio: Higher is better
2. Win Rate: Ideally > 50%
3. Max Consecutive Losses: Lower is better (risk management)
4. Total Profit: Higher is better

Usage:
    python3 optimize_classic_martingale.py
    python3 optimize_classic_martingale.py --min-threshold 1.5 --max-threshold 3.0
    python3 optimize_classic_martingale.py --top 10 --detailed
"""

import argparse
import csv
import sqlite3
import sys
from dataclasses import dataclass
from itertools import product
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


@dataclass
class StrategyParams:
    """Parameters for a strategy"""

    threshold: float
    trigger_count: int
    base_bet: float
    bet_multiplier: float
    cashout: float


@dataclass
class StrategyResult:
    """Results for a strategy across all sessions"""

    params: StrategyParams
    total_profit: float
    total_bets: int
    win_rate: float
    max_consecutive_losses: int
    max_bet: float
    profitable_sessions: int
    total_sessions: int
    avg_profit_per_session: float
    profit_bankroll_ratio: float  # Key metric: profit / required_bankroll
    required_bankroll: float
    sessions: List[SessionResult]


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
    """Get multipliers from database"""
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
    """
    bets = []
    excluded_rounds: Set[int] = set()
    current_bet = base_bet
    consecutive_losses = 0

    i = 0
    while i < len(multipliers):
        if i + trigger_count <= len(multipliers):
            window_indices = list(range(i, i + trigger_count))

            if any(idx in excluded_rounds for idx in window_indices):
                i += 1
                continue

            window = [multipliers[idx] for idx in window_indices]

            if all(m >= threshold for m in window):
                bet_round_idx = i + trigger_count

                if bet_round_idx >= len(multipliers):
                    break

                next_mult = multipliers[bet_round_idx]
                # We WIN if multiplier reaches our cashout target
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
                )

                # Now update for next bet
                if won:
                    consecutive_losses = 0
                    next_bet = base_bet
                else:
                    consecutive_losses += 1
                    next_bet = current_bet * bet_multiplier
                bets.append(bet)

                excluded_rounds.add(bet_round_idx)
                current_bet = next_bet
                i = i + 1
                continue

        i += 1

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


def evaluate_strategy(
    sessions: List[int],
    db_path: str,
    params: StrategyParams,
) -> StrategyResult:
    """Evaluate a strategy across all sessions"""
    results = []

    for session_id in sessions:
        data = get_multipliers(db_path, session_id)
        multipliers = [m for _, m in data]

        if not multipliers:
            continue

        result = simulate_session(
            multipliers=multipliers,
            session_id=session_id,
            threshold=params.threshold,
            trigger_count=params.trigger_count,
            base_bet=params.base_bet,
            bet_multiplier=params.bet_multiplier,
            auto_cashout=params.cashout,
        )

        results.append(result)

    if not results:
        return None

    # Calculate aggregate statistics
    total_profit = sum(r.profit_loss for r in results)
    total_bets = sum(r.total_bets for r in results)
    total_wins = sum(r.wins for r in results)
    win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0
    max_consecutive_losses = max((r.max_consecutive_losses for r in results), default=0)
    max_bet = max((r.max_bet for r in results), default=0)
    profitable_sessions = sum(1 for r in results if r.profit_loss > 0)
    total_sessions = len(results)
    avg_profit_per_session = total_profit / total_sessions if total_sessions > 0 else 0

    # Calculate required bankroll (conservative: 3x max bet)
    required_bankroll = max_bet * 3 if max_bet > 0 else params.base_bet * 3

    # Calculate profit/bankroll ratio (key metric)
    profit_bankroll_ratio = (
        (total_profit / required_bankroll) if required_bankroll > 0 else 0
    )

    return StrategyResult(
        params=params,
        total_profit=total_profit,
        total_bets=total_bets,
        win_rate=win_rate,
        max_consecutive_losses=max_consecutive_losses,
        max_bet=max_bet,
        profitable_sessions=profitable_sessions,
        total_sessions=total_sessions,
        avg_profit_per_session=avg_profit_per_session,
        profit_bankroll_ratio=profit_bankroll_ratio,
        required_bankroll=required_bankroll,
        sessions=results,
    )


def print_strategy_result(result: StrategyResult, rank: int = None):
    """Print a single strategy result"""
    params = result.params

    if rank:
        print(f"\n{'=' * 80}")
        print(f"RANK #{rank}")
    else:
        print(f"\n{'=' * 80}")

    print(f"{'=' * 80}")
    print(f"Strategy Parameters:")
    print(f"  Threshold: >= {params.threshold}x")
    print(f"  Trigger Count: {params.trigger_count} consecutive rounds")
    print(f"  Base Bet: ${params.base_bet:,.0f}")
    print(f"  Bet Multiplier: {params.bet_multiplier}x")
    print(f"  Cashout: {params.cashout}x")

    print(f"\nPerformance Metrics:")
    profit_symbol = "+" if result.total_profit >= 0 else ""
    profit_emoji = "✅" if result.total_profit >= 0 else "❌"
    print(f"  Total Profit: {profit_emoji} {profit_symbol}${result.total_profit:,.0f}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  Total Bets: {result.total_bets:,}")
    print(
        f"  Profitable Sessions: {result.profitable_sessions}/{result.total_sessions} ({result.profitable_sessions / result.total_sessions * 100:.1f}%)"
    )
    print(f"  Avg Profit/Session: {profit_symbol}${result.avg_profit_per_session:,.0f}")

    print(f"\nRisk Metrics:")
    print(f"  Max Consecutive Losses: {result.max_consecutive_losses}")
    print(f"  Max Bet Required: ${result.max_bet:,.0f}")
    print(f"  Required Bankroll: ${result.required_bankroll:,.0f}")

    print(f"\n⭐ KEY METRIC:")
    ratio_symbol = "+" if result.profit_bankroll_ratio >= 0 else ""
    ratio_emoji = "✅" if result.profit_bankroll_ratio >= 0 else "❌"
    print(
        f"  {ratio_emoji} Profit/Bankroll Ratio: {ratio_symbol}{result.profit_bankroll_ratio:.2%}"
    )
    print(
        f"      (You make ${result.profit_bankroll_ratio:.2f} per $1 of bankroll required)"
    )


def optimize(
    sessions: List[int],
    db_path: str,
    thresholds: List[float],
    trigger_counts: List[int],
    base_bets: List[float],
    bet_multipliers: List[float],
    cashouts: List[float],
    min_bets: int = 10,
) -> List[StrategyResult]:
    """
    Test all parameter combinations and return ranked results
    """
    results = []
    total_combinations = (
        len(thresholds)
        * len(trigger_counts)
        * len(base_bets)
        * len(bet_multipliers)
        * len(cashouts)
    )

    print(f"\n{'=' * 80}")
    print(f"OPTIMIZATION IN PROGRESS")
    print(f"{'=' * 80}")
    print(f"Testing {total_combinations} strategy combinations...")
    print(f"This may take a few minutes...\n")

    tested = 0
    for threshold in thresholds:
        for trigger_count in trigger_counts:
            for base_bet in base_bets:
                for bet_multiplier in bet_multipliers:
                    for cashout in cashouts:
                        tested += 1
                        if tested % 10 == 0:
                            print(
                                f"Progress: {tested}/{total_combinations} ({tested / total_combinations * 100:.1f}%)",
                                end="\r",
                            )

                        params = StrategyParams(
                            threshold=threshold,
                            trigger_count=trigger_count,
                            base_bet=base_bet,
                            bet_multiplier=bet_multiplier,
                            cashout=cashout,
                        )

                        result = evaluate_strategy(sessions, db_path, params)

                        # Only keep strategies with minimum bet count
                        if result and result.total_bets >= min_bets:
                            results.append(result)

    print(f"\nProgress: {tested}/{total_combinations} (100.0%) - Complete!  ")
    print(f"\nFound {len(results)} viable strategies (with >= {min_bets} bets)")

    # Remove duplicate strategies (same params = same results)
    seen_params = set()
    unique_results = []
    duplicates_removed = 0

    for result in results:
        # Create a tuple of parameters that uniquely identify the strategy
        param_key = (
            result.params.threshold,
            result.params.trigger_count,
            result.params.base_bet,
            result.params.bet_multiplier,
            result.params.cashout,
        )

        if param_key not in seen_params:
            seen_params.add(param_key)
            unique_results.append(result)
        else:
            duplicates_removed += 1

    if duplicates_removed > 0:
        print(f"Removed {duplicates_removed} duplicate strategies")
        results = unique_results

    # Sort by profit/bankroll ratio (descending)
    results.sort(key=lambda r: r.profit_bankroll_ratio, reverse=True)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Optimize classic martingale strategy parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--db",
        default="./crasher_data.db",
        help="Path to database file (default: ./crasher_data.db)",
    )

    parser.add_argument(
        "--min-threshold",
        type=float,
        default=1.5,
        help="Minimum threshold to test (default: 1.5)",
    )

    parser.add_argument(
        "--max-threshold",
        type=float,
        default=6,
        help="Maximum threshold to test (default: 3.0)",
    )

    parser.add_argument(
        "--threshold-step",
        type=float,
        default=0.5,
        help="Threshold step size (default: 0.5)",
    )

    parser.add_argument(
        "--min-trigger",
        type=int,
        default=2,
        help="Minimum trigger count to test (default: 2)",
    )

    parser.add_argument(
        "--max-trigger",
        type=int,
        default=8,
        help="Maximum trigger count to test (default: 5)",
    )

    parser.add_argument(
        "--base-bets",
        type=float,
        nargs="+",
        default=[1000],
        help="Base bet amounts to test (default: 1000)",
    )

    parser.add_argument(
        "--multipliers",
        type=float,
        nargs="+",
        default=[1, 1.2, 1.5, 2.0, 2.5],
        help="Bet multipliers to test (default: 1.5 2.0 2.5)",
    )

    parser.add_argument(
        "--cashouts",
        type=float,
        nargs="+",
        default=[1.5, 2.0, 2.5, 3, 4, 5, 10],
        help="Cashout values to test (default: 2.0)",
    )

    parser.add_argument(
        "--min-bets",
        type=int,
        default=500,
        help="Minimum number of bets required for a strategy to be viable (default: 10)",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of top strategies to display (default: 5)",
    )

    parser.add_argument(
        "--max-bankroll",
        type=float,
        default=10000000,
        help="Maximum required bankroll in dollars (default: 10,000,000)",
    )

    parser.add_argument(
        "--csv-output",
        type=str,
        default=None,
        help="Output CSV file path (e.g., results.csv). If not specified, no CSV is generated.",
    )

    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed information for top strategies",
    )

    args = parser.parse_args()

    # Generate parameter ranges
    thresholds = []
    current = args.min_threshold
    while current <= args.max_threshold:
        thresholds.append(round(current, 1))
        current += args.threshold_step

    trigger_counts = list(range(args.min_trigger, args.max_trigger + 1))

    print(f"\n{'=' * 80}")
    print(f"CLASSIC MARTINGALE STRATEGY OPTIMIZER")
    print(f"{'=' * 80}")
    print(f"\nParameter Ranges:")
    print(f"  Thresholds: {thresholds}")
    print(f"  Trigger Counts: {trigger_counts}")
    print(f"  Base Bets: {args.base_bets}")
    print(f"  Bet Multipliers: {args.multipliers}")

    # Warning for multiplier = 1.0
    if 1.0 in args.multipliers or any(m <= 1.0 for m in args.multipliers):
        print(f"\n  ⚠️  WARNING: Multiplier of 1.0 means NO BET PROGRESSION!")
        print(
            f"      This is NOT a martingale strategy - you'll always bet the same amount."
        )
        print(f"      Consider using multipliers like: 1.3, 1.5, 2.0")

    print(f"  Cashouts: {args.cashouts}")
    print(f"  Minimum Bets Required: {args.min_bets}")

    # Get sessions
    try:
        sessions = get_sessions(args.db)
        if not sessions:
            print(f"\nERROR: No sessions found in database")
            sys.exit(1)
        print(f"\nLoaded {len(sessions)} sessions from database")
    except Exception as e:
        print(f"\nERROR: Failed to read database: {e}")
        sys.exit(1)

    # Optimize
    results = optimize(
        sessions=sessions,
        db_path=args.db,
        thresholds=thresholds,
        trigger_counts=trigger_counts,
        base_bets=args.base_bets,
        bet_multipliers=args.multipliers,
        cashouts=args.cashouts,
        min_bets=args.min_bets,
    )

    if not results:
        print(f"\n❌ No viable strategies found!")
        print(f"Try adjusting parameter ranges or lowering --min-bets")
        sys.exit(1)

    # Filter by max bankroll
    results_before_filter = len(results)
    results = [r for r in results if r.required_bankroll <= args.max_bankroll]

    if len(results) < results_before_filter:
        print(
            f"\n🔍 Filtered out {results_before_filter - len(results)} strategies exceeding ${args.max_bankroll:,.0f} bankroll"
        )

    if not results:
        print(
            f"\n❌ No strategies found within ${args.max_bankroll:,.0f} bankroll limit!"
        )
        print(f"Try increasing --max-bankroll or adjusting parameter ranges")
        sys.exit(1)

    # Export to CSV if requested
    if args.csv_output:
        csv_path = args.csv_output
        with open(csv_path, "w", newline="") as csvfile:
            fieldnames = [
                "Rank",
                "Threshold",
                "Trigger",
                "BaseBet",
                "Multiplier",
                "Cashout",
                "P/B_Ratio_%",
                "Profit",
                "WinRate_%",
                "MaxLoss",
                "Required_Bankroll",
                "Total_Bets",
                "Profitable_Sessions",
                "Total_Sessions",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for i, result in enumerate(results, 1):
                writer.writerow(
                    {
                        "Rank": i,
                        "Threshold": result.params.threshold,
                        "Trigger": result.params.trigger_count,
                        "BaseBet": result.params.base_bet,
                        "Multiplier": result.params.bet_multiplier,
                        "Cashout": result.params.cashout,
                        "P/B_Ratio_%": round(result.profit_bankroll_ratio * 100, 2),
                        "Profit": round(result.total_profit, 2),
                        "WinRate_%": round(result.win_rate, 2),
                        "MaxLoss": result.max_consecutive_losses,
                        "Required_Bankroll": round(result.required_bankroll, 2),
                        "Total_Bets": result.total_bets,
                        "Profitable_Sessions": result.profitable_sessions,
                        "Total_Sessions": result.total_sessions,
                    }
                )

        print(f"\n✅ CSV exported to: {csv_path}")
        print(f"   Total strategies exported: {len(results)}")

    # Display top results
    print(f"\n{'=' * 80}")
    print(f"TOP {min(args.top, len(results))} STRATEGIES")
    print(f"(Ranked by Profit/Bankroll Ratio)")
    print(f"{'=' * 80}")

    for i, result in enumerate(results[: args.top], 1):
        print_strategy_result(result, rank=i)

    # Summary comparison
    print(f"\n{'=' * 80}")
    print(f"QUICK COMPARISON - TOP {min(args.top, len(results))} STRATEGIES")
    print(f"{'=' * 80}")
    print(
        f"\n{'Rank':<6} {'Thresh':<8} {'Trig':<6} {'Base':<10} {'Mult':<6} {'Cash':<6} {'P/B%':<10} {'Profit':<15} {'WR%':<8} {'MaxL':<6} {'Bankroll':<12}"
    )
    print(
        f"{'-' * 6} {'-' * 8} {'-' * 6} {'-' * 10} {'-' * 6} {'-' * 6} {'-' * 10} {'-' * 15} {'-' * 8} {'-' * 6} {'-' * 12}"
    )

    for i, result in enumerate(results[: args.top], 1):
        p = result.params
        profit_str = f"${result.total_profit:,.0f}"
        ratio_str = f"{result.profit_bankroll_ratio:+.1%}"
        win_rate_str = f"{result.win_rate:.1f}"
        bankroll_str = f"${result.required_bankroll:,.0f}"

        print(
            f"#{i:<5} {p.threshold:<8.1f} {p.trigger_count:<6} ${p.base_bet:<9,.0f} {p.bet_multiplier:<6.1f} {p.cashout:<6.1f} {ratio_str:<10} {profit_str:<15} {win_rate_str:<8} {result.max_consecutive_losses:<6} {bankroll_str:<12}"
        )

    # Best strategy recommendation
    if results:
        best = results[0]
        print(f"\n{'=' * 80}")
        print(f"🏆 RECOMMENDED STRATEGY")
        print(f"{'=' * 80}")
        print(f"\nCommand to run this strategy:")
        print(f"\npython3 simulate_classic_martingale.py {best.params.threshold} \\")
        print(f"    --base-bet {best.params.base_bet:.0f} \\")
        print(f"    --trigger-count {best.params.trigger_count} \\")
        print(f"    --multiplier {best.params.bet_multiplier} \\")
        print(f"    --cashout {best.params.cashout} \\")
        print(f"    --all-sessions --detailed")

        print(f"\nExpected Results:")
        print(f"  💰 Total Profit: ${best.total_profit:,.0f}")
        print(f"  📊 Profit/Bankroll: {best.profit_bankroll_ratio:+.2%}")
        print(f"  🎯 Win Rate: {best.win_rate:.1f}%")
        print(f"  💳 Required Bankroll: ${best.required_bankroll:,.0f}")
        print(f"  ⚠️  Max Consecutive Losses: {best.max_consecutive_losses}")

    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    main()
