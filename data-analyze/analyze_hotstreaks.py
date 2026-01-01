import csv
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def get_all_multipliers(db_path: str) -> List[Dict]:
    """Fetch all multipliers ordered by timestamp and session."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.multiplier, m.timestamp, m.session_id
        FROM multipliers m
        ORDER BY m.session_id, m.timestamp
    """)

    multipliers = []
    for row in cursor.fetchall():
        multipliers.append(
            {
                "id": row[0],
                "multiplier": row[1],
                "timestamp": row[2],
                "session_id": row[3],
            }
        )

    conn.close()
    return multipliers


def is_hot_streak(window: List[float], window_size: int) -> Optional[str]:
    """
    Check if a window is a hot streak.
    Returns 'strong', 'weak', or None
    """
    if len(window) < 10 or len(window) > 15:
        return None

    above_2x = sum(1 for m in window if m >= 2.0)
    percentage = above_2x / len(window)

    if percentage >= 0.80:
        return "strong"
    elif percentage >= 0.65:
        return "weak"
    return None


def find_hot_streaks(multipliers: List[Dict]) -> List[Dict]:
    """Find all hot streaks in the data."""
    hot_streaks = []
    i = 0

    while i < len(multipliers):
        # Try windows from 10 to 15 rounds
        found_streak = False

        for window_size in range(15, 9, -1):  # Start with largest window
            if i + window_size > len(multipliers):
                continue

            window = [m["multiplier"] for m in multipliers[i : i + window_size]]
            streak_type = is_hot_streak(window, window_size)

            if streak_type:
                # Calculate average
                avg = sum(window) / len(window)

                hot_streaks.append(
                    {
                        "start_index": i,
                        "end_index": i + window_size - 1,
                        "length": window_size,
                        "type": streak_type,
                        "average": avg,
                        "multipliers": window,
                        "timestamp": multipliers[i]["timestamp"],
                        "session_id": multipliers[i]["session_id"],
                    }
                )

                # Skip past this streak
                i += window_size
                found_streak = True
                break

        if not found_streak:
            i += 1

    return hot_streaks


def find_next_cold_streak(multipliers: List[Dict], start_index: int) -> Optional[Dict]:
    """Find the next cold streak (5+ consecutive rounds under 2.0x)."""
    i = start_index

    while i < len(multipliers):
        # Check if we have a cold streak starting here
        cold_count = 0
        j = i

        while j < len(multipliers) and multipliers[j]["multiplier"] < 2.0:
            cold_count += 1
            j += 1

        if cold_count >= 5:
            return {
                "start_index": i,
                "length": cold_count,
                "rounds_after_hotstreak": i - start_index,
            }

        i += 1

    return None


def find_next_hot_streak(hot_streaks: List[Dict], current_index: int) -> Optional[int]:
    """Find rounds until next hot streak."""
    if current_index >= len(hot_streaks) - 1:
        return None

    current_end = hot_streaks[current_index]["end_index"]
    next_start = hot_streaks[current_index + 1]["start_index"]

    return next_start - current_end - 1


def get_surrounding_rounds(
    multipliers: List[Dict], start_index: int, end_index: int
) -> Tuple[List[float], List[float]]:
    """Get 20 rounds before and after the hot streak."""
    before_start = max(0, start_index - 20)
    before = [m["multiplier"] for m in multipliers[before_start:start_index]]

    after_end = min(len(multipliers), end_index + 21)
    after = [m["multiplier"] for m in multipliers[end_index + 1 : after_end]]

    # Pad with empty values if less than 20
    before = [""] * (20 - len(before)) + before
    after = after + [""] * (20 - len(after))

    return before, after


def analyze_and_export(db_path: str, output_csv: str):
    """Main analysis function."""
    print("Loading multipliers from database...")
    multipliers = get_all_multipliers(db_path)
    print(f"Loaded {len(multipliers)} multipliers")

    print("Finding hot streaks...")
    hot_streaks = find_hot_streaks(multipliers)
    print(f"Found {len(hot_streaks)} hot streaks")

    print("Analyzing streaks and writing to CSV...")
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "streak_length",
            "streak_type",
            "timestamp",
            "session_id",
            "streak_average",
            "next_streak_in",
            "next_cold_streak_in",
            "next_cold_streak_length",
            "multipliers_of_the_streak",
            "last_20_rounds_before_hotstreak",
            "next_20_rounds_after_hotstreak",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for idx, streak in enumerate(hot_streaks):
            # Find next hot streak distance
            next_hot_distance = find_next_hot_streak(hot_streaks, idx)

            # Find next cold streak
            cold_streak = find_next_cold_streak(multipliers, streak["end_index"] + 1)

            # If next hot streak comes before next cold streak, don't count the cold streak
            if next_hot_distance is not None and cold_streak is not None:
                if next_hot_distance < cold_streak["rounds_after_hotstreak"]:
                    cold_streak = None

            # Get surrounding rounds
            before, after = get_surrounding_rounds(
                multipliers, streak["start_index"], streak["end_index"]
            )

            row = {
                "streak_length": streak["length"],
                "streak_type": streak["type"],
                "timestamp": streak["timestamp"],
                "session_id": streak["session_id"],
                "streak_average": f"{streak['average']:.2f}",
                "next_streak_in": next_hot_distance
                if next_hot_distance is not None
                else "",
                "next_cold_streak_in": cold_streak["rounds_after_hotstreak"]
                if cold_streak
                else "",
                "next_cold_streak_length": cold_streak["length"] if cold_streak else "",
                "multipliers_of_the_streak": "|".join(
                    [f"{m:.2f}" for m in streak["multipliers"]]
                ),
                "last_20_rounds_before_hotstreak": "|".join(
                    [f"{m:.2f}" if m != "" else "" for m in before]
                ),
                "next_20_rounds_after_hotstreak": "|".join(
                    [f"{m:.2f}" if m != "" else "" for m in after]
                ),
            }

            writer.writerow(row)

            if (idx + 1) % 100 == 0:
                print(f"Processed {idx + 1}/{len(hot_streaks)} streaks")

    print(f"\nAnalysis complete! Results saved to {output_csv}")
    print(f"Total hot streaks found: {len(hot_streaks)}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python analyze_hotstreaks.py <path_to_database.db> [output.csv]")
        print(
            "Example: python analyze_hotstreaks.py crasher_data.db hotstreaks_analysis.csv"
        )
        sys.exit(1)

    db_path = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "hotstreaks_analysis.csv"

    try:
        analyze_and_export(db_path, output_csv)
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
