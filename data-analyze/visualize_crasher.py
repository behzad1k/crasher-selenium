#!/usr/bin/env python3
"""
Crasher Game Visualization
Generates visual graphs of multiplier movements per session
"""

import argparse
import sqlite3
from datetime import timedelta
from typing import Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class CrasherVisualizer:
    """Create visualizations for crasher game data"""

    def __init__(self, db_path: str = "./crasher_data.db", threshold: float = 2.0):
        self.conn = sqlite3.connect(db_path)
        self.threshold = threshold
        self.max_gap_minutes = 3

    def load_data(self) -> pd.DataFrame:
        """Load and prepare data"""
        query = "SELECT id, multiplier, bettor_count, timestamp FROM multipliers ORDER BY timestamp ASC"
        df = pd.read_sql_query(query, self.conn)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # Detect sessions
        df["time_diff"] = df["timestamp"].diff()
        df["new_session"] = df["time_diff"] > timedelta(minutes=self.max_gap_minutes)
        df["session_id"] = df["new_session"].cumsum()
        if len(df) > 0:
            df.loc[0, "session_id"] = 0

        # Normalize multipliers > 10x for better visualization
        df["multiplier_display"] = df["multiplier"].apply(lambda x: min(x, 10.0))
        df["is_over_10x"] = df["multiplier"] > 10.0
        df["under_threshold"] = df["multiplier"] < self.threshold

        return df

    def plot_session_overview(self, df: pd.DataFrame, output_path: str):
        """Plot overview of all sessions"""
        sessions = df["session_id"].unique()
        num_sessions = len(sessions)

        fig, axes = plt.subplots(
            min(num_sessions, 12),
            1,
            figsize=(16, min(num_sessions * 2, 24)),
            squeeze=False,
        )

        fig.suptitle(
            f"Crasher Game Multipliers by Session (Threshold: {self.threshold}x)",
            fontsize=16,
            fontweight="bold",
        )

        for idx, session_id in enumerate(
            sorted(sessions)[:12]
        ):  # Limit to first 12 sessions
            session_df = df[df["session_id"] == session_id].copy()
            session_df["round_num"] = range(len(session_df))

            ax = axes[idx, 0]

            # Plot multipliers
            colors = ["red" if x else "gray" for x in session_df["under_threshold"]]
            scatter = ax.scatter(
                session_df["round_num"],
                session_df["multiplier_display"],
                c=colors,
                alpha=0.6,
                s=30,
            )

            # Mark 10x+ multipliers
            over_10x = session_df[session_df["is_over_10x"]]
            if len(over_10x) > 0:
                ax.scatter(
                    over_10x["round_num"],
                    [10.0] * len(over_10x),
                    marker="^",
                    c="green",
                    s=100,
                    label="10x+",
                    zorder=5,
                )

            # Add threshold line
            ax.axhline(
                y=self.threshold,
                color="blue",
                linestyle="--",
                linewidth=2,
                label=f"Threshold ({self.threshold}x)",
                alpha=0.7,
            )

            # Add 10x line
            ax.axhline(
                y=10.0,
                color="green",
                linestyle="--",
                linewidth=1,
                label="10x",
                alpha=0.5,
            )

            # Styling
            ax.set_xlabel("Round Number")
            ax.set_ylabel("Multiplier (capped at 10x)")
            ax.set_title(
                f"Session {int(session_id)} - {len(session_df)} rounds - "
                f"{session_df['timestamp'].min().strftime('%Y-%m-%d %H:%M')}",
                fontsize=10,
            )
            ax.grid(True, alpha=0.3)
            ax.set_ylim(0, 11)

            # Legend
            red_patch = mpatches.Patch(
                color="red", alpha=0.6, label=f"Under {self.threshold}x"
            )
            gray_patch = mpatches.Patch(
                color="gray", alpha=0.6, label=f"{self.threshold}x - 10x"
            )
            green_marker = plt.Line2D(
                [0],
                [0],
                marker="^",
                color="w",
                markerfacecolor="green",
                markersize=10,
                label="10x+",
            )
            ax.legend(
                handles=[red_patch, gray_patch, green_marker],
                loc="upper right",
                fontsize=8,
            )

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Session overview saved to: {output_path}")

    def plot_multiplier_distribution(self, df: pd.DataFrame, output_path: str):
        """Plot distribution of multipliers"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 1. Histogram of all multipliers (capped at 10)
        ax1 = axes[0, 0]
        ax1.hist(
            df["multiplier_display"],
            bins=50,
            color="steelblue",
            alpha=0.7,
            edgecolor="black",
        )
        ax1.axvline(
            x=self.threshold,
            color="red",
            linestyle="--",
            linewidth=2,
            label=f"Threshold ({self.threshold}x)",
        )
        ax1.axvline(x=10.0, color="green", linestyle="--", linewidth=2, label="10x")
        ax1.set_xlabel("Multiplier (capped at 10x)")
        ax1.set_ylabel("Frequency")
        ax1.set_title("Distribution of Multipliers")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 2. Pie chart: Under threshold vs Over threshold
        ax2 = axes[0, 1]
        under = (df["multiplier"] < self.threshold).sum()
        over = (df["multiplier"] >= self.threshold).sum()
        ax2.pie(
            [under, over],
            labels=[f"Under {self.threshold}x", f"{self.threshold}x+"],
            autopct="%1.1f%%",
            colors=["red", "green"],
            startangle=90,
        )
        ax2.set_title(f"Rounds Distribution: Under vs Over {self.threshold}x")

        # 3. Box plot by session
        ax3 = axes[1, 0]
        sessions_to_plot = sorted(df["session_id"].unique())[:10]
        session_data = [
            df[df["session_id"] == s]["multiplier_display"].values
            for s in sessions_to_plot
        ]
        bp = ax3.boxplot(session_data, labels=[f"S{int(s)}" for s in sessions_to_plot])
        ax3.axhline(
            y=self.threshold, color="red", linestyle="--", linewidth=2, alpha=0.7
        )
        ax3.axhline(y=10.0, color="green", linestyle="--", linewidth=1, alpha=0.5)
        ax3.set_xlabel("Session ID")
        ax3.set_ylabel("Multiplier (capped at 10x)")
        ax3.set_title("Multiplier Distribution by Session (First 10 Sessions)")
        ax3.grid(True, alpha=0.3)

        # 4. Timeline of 10x+ occurrences
        ax4 = axes[1, 1]
        df["cumulative_rounds"] = range(len(df))
        over_10x_df = df[df["multiplier"] > 10.0].copy()

        if len(over_10x_df) > 0:
            ax4.scatter(
                over_10x_df["cumulative_rounds"],
                over_10x_df["multiplier"],
                c="green",
                alpha=0.6,
                s=50,
            )
            ax4.set_xlabel("Cumulative Round Number")
            ax4.set_ylabel("Multiplier Value")
            ax4.set_title(f"10x+ Multiplier Occurrences ({len(over_10x_df)} total)")
            ax4.grid(True, alpha=0.3)

            # Add horizontal line at 10x
            ax4.axhline(y=10.0, color="green", linestyle="--", linewidth=1, alpha=0.5)
        else:
            ax4.text(
                0.5,
                0.5,
                "No 10x+ multipliers in dataset",
                ha="center",
                va="center",
                transform=ax4.transAxes,
                fontsize=12,
            )
            ax4.set_title("10x+ Multiplier Occurrences")

        plt.suptitle(
            f"Multiplier Analysis (Threshold: {self.threshold}x)",
            fontsize=16,
            fontweight="bold",
            y=0.995,
        )
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Distribution analysis saved to: {output_path}")

    def plot_streak_analysis(self, df: pd.DataFrame, output_path: str):
        """Plot streak analysis"""
        # Find streaks
        df_copy = df.copy()
        df_copy["under_threshold"] = df_copy["multiplier"] < self.threshold

        streaks = []
        current_streak = 0

        for idx, row in df_copy.iterrows():
            if row["under_threshold"]:
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append(current_streak)
                current_streak = 0

        if current_streak > 0:
            streaks.append(current_streak)

        if not streaks:
            print("No streaks found")
            return

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 1. Streak length distribution
        ax1 = axes[0, 0]
        streak_counts = pd.Series(streaks).value_counts().sort_index()
        ax1.bar(streak_counts.index, streak_counts.values, color="steelblue", alpha=0.7)
        ax1.set_xlabel("Streak Length (consecutive rounds)")
        ax1.set_ylabel("Frequency")
        ax1.set_title(f"Distribution of Streaks Under {self.threshold}x")
        ax1.grid(True, alpha=0.3, axis="y")

        # 2. Cumulative distribution
        ax2 = axes[0, 1]
        sorted_streaks = sorted(streaks)
        cumulative_pct = [i / len(streaks) * 100 for i in range(1, len(streaks) + 1)]
        ax2.plot(sorted_streaks, cumulative_pct, color="darkblue", linewidth=2)
        ax2.set_xlabel("Streak Length")
        ax2.set_ylabel("Cumulative Percentage")
        ax2.set_title("Cumulative Distribution of Streak Lengths")
        ax2.grid(True, alpha=0.3)
        ax2.axhline(
            y=95, color="red", linestyle="--", alpha=0.5, label="95th percentile"
        )
        ax2.axhline(
            y=99, color="darkred", linestyle="--", alpha=0.5, label="99th percentile"
        )
        ax2.legend()

        # 3. Streak statistics
        ax3 = axes[1, 0]
        ax3.axis("off")

        stats_text = f"""
        STREAK STATISTICS (Under {self.threshold}x)

        Total Streaks: {len(streaks)}
        Shortest Streak: {min(streaks)}
        Longest Streak: {max(streaks)}
        Average Streak: {np.mean(streaks):.2f}
        Median Streak: {np.median(streaks):.2f}
        Std Deviation: {np.std(streaks):.2f}

        Percentiles:
        50th (Median): {np.percentile(streaks, 50):.0f}
        75th: {np.percentile(streaks, 75):.0f}
        90th: {np.percentile(streaks, 90):.0f}
        95th: {np.percentile(streaks, 95):.0f}
        99th: {np.percentile(streaks, 99):.0f}
        """

        ax3.text(
            0.1,
            0.9,
            stats_text,
            transform=ax3.transAxes,
            fontsize=11,
            verticalalignment="top",
            family="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.3),
        )

        # 4. Top 20 longest streaks
        ax4 = axes[1, 1]
        top_streaks = sorted(streaks, reverse=True)[:20]
        ax4.barh(range(len(top_streaks)), top_streaks, color="darkred", alpha=0.7)
        ax4.set_xlabel("Streak Length")
        ax4.set_ylabel("Rank")
        ax4.set_title("Top 20 Longest Streaks")
        ax4.invert_yaxis()
        ax4.grid(True, alpha=0.3, axis="x")

        plt.suptitle(
            f"Streak Analysis (Threshold: {self.threshold}x)",
            fontsize=16,
            fontweight="bold",
            y=0.995,
        )
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Streak analysis saved to: {output_path}")

    def plot_10x_analysis(self, df: pd.DataFrame, output_path: str):
        """Plot specific analysis for 10x+ multipliers"""
        # Find streaks without 10x+
        df_copy = df.copy()
        df_copy["no_10x"] = df_copy["multiplier"] < 10.0

        streaks = []
        current_streak = 0

        for idx, row in df_copy.iterrows():
            if row["no_10x"]:
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append(current_streak)
                current_streak = 0

        if current_streak > 0:
            streaks.append(current_streak)

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 1. Distribution of streaks without 10x
        ax1 = axes[0, 0]
        if streaks:
            streak_counts = pd.Series(streaks).value_counts().sort_index()
            # Limit to streaks up to 80 for visibility
            streak_counts_display = streak_counts[streak_counts.index <= 80]
            ax1.bar(
                streak_counts_display.index,
                streak_counts_display.values,
                color="steelblue",
                alpha=0.7,
                edgecolor="black",
            )
            ax1.axvline(
                x=50,
                color="orange",
                linestyle="--",
                linewidth=2,
                label="Trigger (50 rounds)",
            )
            ax1.axvline(
                x=77,
                color="red",
                linestyle="--",
                linewidth=2,
                label="Wipeout (77 rounds)",
            )
            ax1.set_xlabel("Consecutive Rounds Without 10x+")
            ax1.set_ylabel("Frequency")
            ax1.set_title('Distribution of "No 10x+" Streaks (up to 80)')
            ax1.legend()
            ax1.grid(True, alpha=0.3, axis="y")

        # 2. Key thresholds
        ax2 = axes[0, 1]
        if streaks:
            thresholds = {
                "< 50 (Safe)": sum(1 for s in streaks if s < 50),
                "50-76 (Trigger, Win)": sum(1 for s in streaks if 50 <= s < 77),
                "77+ (Wipeout)": sum(1 for s in streaks if s >= 77),
            }

            colors = ["green", "orange", "red"]
            ax2.bar(thresholds.keys(), thresholds.values(), color=colors, alpha=0.7)
            ax2.set_ylabel("Frequency")
            ax2.set_title("Streaks by Critical Thresholds")
            ax2.grid(True, alpha=0.3, axis="y")

            # Add value labels on bars
            for i, (k, v) in enumerate(thresholds.items()):
                ax2.text(i, v, str(v), ha="center", va="bottom", fontweight="bold")

        # 3. Gaps between 10x+ multipliers
        ax3 = axes[1, 0]
        over_10x_indices = df[df["multiplier"] >= 10.0].index.tolist()
        if len(over_10x_indices) > 1:
            gaps = [
                over_10x_indices[i + 1] - over_10x_indices[i] - 1
                for i in range(len(over_10x_indices) - 1)
            ]
            ax3.hist(gaps, bins=30, color="green", alpha=0.7, edgecolor="black")
            ax3.axvline(
                x=np.mean(gaps),
                color="red",
                linestyle="--",
                linewidth=2,
                label=f"Average: {np.mean(gaps):.1f}",
            )
            ax3.set_xlabel("Gap Between 10x+ Multipliers (rounds)")
            ax3.set_ylabel("Frequency")
            ax3.set_title("Distribution of Gaps Between 10x+ Events")
            ax3.legend()
            ax3.grid(True, alpha=0.3, axis="y")

        # 4. Statistics
        ax4 = axes[1, 1]
        ax4.axis("off")

        if streaks:
            total_rounds = len(df)
            over_10x_count = (df["multiplier"] >= 10.0).sum()
            trigger_count = sum(1 for s in streaks if s >= 50)
            wipeout_count = sum(1 for s in streaks if s >= 77)

            stats_text = f"""
            10X+ MULTIPLIER STATISTICS

            Total Rounds: {total_rounds:,}
            10x+ Occurrences: {over_10x_count} ({over_10x_count / total_rounds * 100:.2f}%)
            Average Gap: {total_rounds / max(over_10x_count, 1):.1f} rounds

            STREAK STATISTICS (No 10x+)
            Total Streaks: {len(streaks)}
            Longest Streak: {max(streaks)}
            Average Streak: {np.mean(streaks):.2f}

            CRITICAL EVENTS
            Trigger Events (50+): {trigger_count}
            Wipeout Events (77+): {wipeout_count}

            Win Rate (if using strategy):
            {((trigger_count - wipeout_count) / max(trigger_count, 1) * 100):.1f}%
            """

            ax4.text(
                0.1,
                0.9,
                stats_text,
                transform=ax4.transAxes,
                fontsize=11,
                verticalalignment="top",
                family="monospace",
                bbox=dict(boxstyle="round", facecolor="lightgreen", alpha=0.3),
            )

        plt.suptitle(
            "10x+ Multiplier Analysis", fontsize=16, fontweight="bold", y=0.995
        )
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"10x+ analysis saved to: {output_path}")

    def generate_all_visualizations(self, output_dir: str = "data-analyze/outputs"):
        """Generate all visualizations"""
        print("Loading data...")
        df = self.load_data()

        if len(df) == 0:
            print("No data found in database")
            return

        print(f"Loaded {len(df)} rounds across {df['session_id'].nunique()} sessions")

        print("\nGenerating visualizations...")

        # Session overview
        self.plot_session_overview(df, f"{output_dir}/session_overview.png")

        # Distribution analysis
        self.plot_multiplier_distribution(
            df, f"{output_dir}/multiplier_distribution.png"
        )

        # Streak analysis
        self.plot_streak_analysis(df, f"{output_dir}/streak_analysis.png")

        # 10x analysis
        self.plot_10x_analysis(df, f"{output_dir}/10x_analysis.png")

        print("\n✓ All visualizations completed!")

    def close(self):
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate visualizations for crasher game data"
    )
    parser.add_argument(
        "--db", default="./crasher_data.db", help="Path to database file"
    )
    parser.add_argument(
        "--threshold", type=float, default=2.0, help="Multiplier threshold"
    )
    parser.add_argument(
        "--output", default="data-analyze/outputs", help="Output directory"
    )

    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Threshold: {args.threshold}x")
    print(f"Output Directory: {args.output}")

    visualizer = CrasherVisualizer(args.db, args.threshold)

    try:
        visualizer.generate_all_visualizations(args.output)
    except Exception as e:
        print(f"Error generating visualizations: {e}")
        import traceback

        traceback.print_exc()
    finally:
        visualizer.close()


if __name__ == "__main__":
    main()
