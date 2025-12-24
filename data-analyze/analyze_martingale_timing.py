#!/usr/bin/env python3
"""
Hot Streak & Losing Streak Time Analysis
Analyzes when hot streaks (8+ consecutive over 2x) and losing streaks (under 2x) occur
Provides hourly frequency breakdown per day for martingale strategy optimization
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import seaborn as sns


class TimeBasedStreakAnalyzer:
    """Analyze hot and cold streaks with time-based frequency analysis"""
    
    def __init__(self, db_path: str = "./crasher_data.db"):
        self.conn = sqlite3.connect(db_path)
        self.hot_threshold = 2.0
        self.hot_min_length = 8  # Minimum 8 consecutive rounds for hot streak
        self.cold_threshold = 2.0
    
    def load_data_by_session(self) -> Dict[int, List[Tuple]]:
        """Load all multipliers grouped by session"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                session_id,
                timestamp,
                multiplier,
                bettor_count,
                id
            FROM multipliers
            WHERE session_id IS NOT NULL
            ORDER BY session_id, timestamp
        """)
        
        rows = cursor.fetchall()
        
        if not rows:
            print("❌ No data found with session assignments!")
            return {}
        
        sessions = {}
        for session_id, timestamp_str, multiplier, bettor_count, round_id in rows:
            if session_id not in sessions:
                sessions[session_id] = []
            
            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            sessions[session_id].append((timestamp, multiplier, bettor_count, round_id))
        
        return sessions
    
    def find_hot_streaks(self, sessions: Dict[int, List[Tuple]]) -> List[Dict]:
        """
        Find hot streaks: 8+ consecutive rounds over 2.0x
        Returns: List of hot streak dictionaries
        """
        all_streaks = []
        
        for session_id, rounds in sessions.items():
            current_streak = []
            
            for timestamp, multiplier, bettor_count, round_id in rounds:
                if multiplier >= self.hot_threshold:
                    current_streak.append({
                        'timestamp': timestamp,
                        'multiplier': multiplier,
                        'bettor_count': bettor_count,
                        'round_id': round_id
                    })
                else:
                    # Save if meets minimum length
                    if len(current_streak) >= self.hot_min_length:
                        all_streaks.append({
                            'session_id': session_id,
                            'length': len(current_streak),
                            'start_time': current_streak[0]['timestamp'],
                            'end_time': current_streak[-1]['timestamp'],
                            'start_round_id': current_streak[0]['round_id'],
                            'end_round_id': current_streak[-1]['round_id'],
                            'multipliers': [r['multiplier'] for r in current_streak],
                            'bettor_counts': [r['bettor_count'] for r in current_streak if r['bettor_count'] is not None],
                            'avg_multiplier': sum(r['multiplier'] for r in current_streak) / len(current_streak),
                            'max_multiplier': max(r['multiplier'] for r in current_streak),
                            'min_multiplier': min(r['multiplier'] for r in current_streak),
                            'type': 'hot'
                        })
                    current_streak = []
            
            # Don't forget last streak
            if len(current_streak) >= self.hot_min_length:
                all_streaks.append({
                    'session_id': session_id,
                    'length': len(current_streak),
                    'start_time': current_streak[0]['timestamp'],
                    'end_time': current_streak[-1]['timestamp'],
                    'start_round_id': current_streak[0]['round_id'],
                    'end_round_id': current_streak[-1]['round_id'],
                    'multipliers': [r['multiplier'] for r in current_streak],
                    'bettor_counts': [r['bettor_count'] for r in current_streak if r['bettor_count'] is not None],
                    'avg_multiplier': sum(r['multiplier'] for r in current_streak) / len(current_streak),
                    'max_multiplier': max(r['multiplier'] for r in current_streak),
                    'min_multiplier': min(r['multiplier'] for r in current_streak),
                    'type': 'hot',
                    'incomplete': True
                })
        
        return all_streaks
    
    def find_losing_streaks(self, sessions: Dict[int, List[Tuple]], min_length: int = 8) -> List[Dict]:
        """
        Find losing streaks: consecutive rounds under 2.0x
        Returns: List of losing streak dictionaries
        """
        all_streaks = []
        
        for session_id, rounds in sessions.items():
            current_streak = []
            
            for timestamp, multiplier, bettor_count, round_id in rounds:
                if multiplier < self.cold_threshold:
                    current_streak.append({
                        'timestamp': timestamp,
                        'multiplier': multiplier,
                        'bettor_count': bettor_count,
                        'round_id': round_id
                    })
                else:
                    # Save if meets minimum length
                    if len(current_streak) >= min_length:
                        all_streaks.append({
                            'session_id': session_id,
                            'length': len(current_streak),
                            'start_time': current_streak[0]['timestamp'],
                            'end_time': current_streak[-1]['timestamp'],
                            'start_round_id': current_streak[0]['round_id'],
                            'end_round_id': current_streak[-1]['round_id'],
                            'multipliers': [r['multiplier'] for r in current_streak],
                            'bettor_counts': [r['bettor_count'] for r in current_streak if r['bettor_count'] is not None],
                            'avg_multiplier': sum(r['multiplier'] for r in current_streak) / len(current_streak),
                            'max_multiplier': max(r['multiplier'] for r in current_streak),
                            'min_multiplier': min(r['multiplier'] for r in current_streak),
                            'type': 'losing'
                        })
                    current_streak = []
            
            # Don't forget last streak
            if len(current_streak) >= min_length:
                all_streaks.append({
                    'session_id': session_id,
                    'length': len(current_streak),
                    'start_time': current_streak[0]['timestamp'],
                    'end_time': current_streak[-1]['timestamp'],
                    'start_round_id': current_streak[0]['round_id'],
                    'end_round_id': current_streak[-1]['round_id'],
                    'multipliers': [r['multiplier'] for r in current_streak],
                    'bettor_counts': [r['bettor_count'] for r in current_streak if r['bettor_count'] is not None],
                    'avg_multiplier': sum(r['multiplier'] for r in current_streak) / len(current_streak),
                    'max_multiplier': max(r['multiplier'] for r in current_streak),
                    'min_multiplier': min(r['multiplier'] for r in current_streak),
                    'type': 'losing',
                    'incomplete': True
                })
        
        return all_streaks
    
    def analyze_hourly_frequency_per_day(
        self, 
        streaks: List[Dict]
    ) -> Dict[str, Dict[int, int]]:
        """
        Analyze streak frequency per hour, grouped by day
        Returns: {date_str: {hour: count}}
        """
        daily_hourly_freq = defaultdict(lambda: defaultdict(int))
        
        for streak in streaks:
            date_str = streak['start_time'].strftime('%Y-%m-%d')
            hour = streak['start_time'].hour
            daily_hourly_freq[date_str][hour] += 1
        
        return dict(daily_hourly_freq)
    
    def get_overall_hourly_stats(self, streaks: List[Dict]) -> Dict[int, Dict]:
        """
        Get statistics per hour across all days
        Returns: {hour: {count, avg_per_day, days_active}}
        """
        hourly_counts = defaultdict(int)
        hourly_days = defaultdict(set)
        
        for streak in streaks:
            hour = streak['start_time'].hour
            date = streak['start_time'].date()
            hourly_counts[hour] += 1
            hourly_days[hour].add(date)
        
        # Calculate stats
        stats = {}
        for hour in range(24):
            count = hourly_counts.get(hour, 0)
            days_active = len(hourly_days.get(hour, set()))
            avg_per_day = count / days_active if days_active > 0 else 0
            
            stats[hour] = {
                'total_count': count,
                'days_active': days_active,
                'avg_per_day': avg_per_day
            }
        
        return stats
    
    def analyze_all(self) -> Dict:
        """Analyze both hot and losing streaks"""
        print("Loading data by session...")
        sessions = self.load_data_by_session()
        
        if not sessions:
            return {}
        
        total_rounds = sum(len(rounds) for rounds in sessions.values())
        print(f"Loaded {total_rounds:,} rounds across {len(sessions)} sessions")
        
        # Get date range
        all_dates = set()
        for rounds in sessions.values():
            for timestamp, _, _, _ in rounds:
                all_dates.add(timestamp.date())
        
        min_date = min(all_dates)
        max_date = max(all_dates)
        total_days = (max_date - min_date).days + 1
        
        print(f"Date range: {min_date} to {max_date} ({total_days} days)")
        
        results = {}
        
        # Hot streaks
        print(f"\nAnalyzing Hot Streaks (8+ consecutive ≥ {self.hot_threshold}x)...")
        hot_streaks = self.find_hot_streaks(sessions)
        hot_streaks.sort(key=lambda x: x['length'], reverse=True)
        results['hot_streaks'] = hot_streaks
        results['hot_daily_hourly'] = self.analyze_hourly_frequency_per_day(hot_streaks)
        results['hot_hourly_stats'] = self.get_overall_hourly_stats(hot_streaks)
        
        print(f"  Found {len(hot_streaks)} hot streaks")
        if hot_streaks:
            print(f"  Longest: {hot_streaks[0]['length']} rounds")
            print(f"  Total hot streak occurrences across all days: {len(hot_streaks)}")
        
        # Losing streaks
        print(f"\nAnalyzing Losing Streaks (8+ consecutive < {self.cold_threshold}x)...")
        losing_streaks = self.find_losing_streaks(sessions, min_length=8)
        losing_streaks.sort(key=lambda x: x['length'], reverse=True)
        results['losing_streaks'] = losing_streaks
        results['losing_daily_hourly'] = self.analyze_hourly_frequency_per_day(losing_streaks)
        results['losing_hourly_stats'] = self.get_overall_hourly_stats(losing_streaks)
        
        print(f"  Found {len(losing_streaks)} losing streaks")
        if losing_streaks:
            print(f"  Longest: {losing_streaks[0]['length']} rounds")
            print(f"  Total losing streak occurrences across all days: {len(losing_streaks)}")
        
        results['date_range'] = {'min': min_date, 'max': max_date, 'total_days': total_days}
        
        return results
    
    def generate_report(self, results: Dict, output_path: str):
        """Generate detailed time-based report"""
        
        hot_streaks = results['hot_streaks']
        losing_streaks = results['losing_streaks']
        hot_daily_hourly = results['hot_daily_hourly']
        losing_daily_hourly = results['losing_daily_hourly']
        hot_hourly_stats = results['hot_hourly_stats']
        losing_hourly_stats = results['losing_hourly_stats']
        date_range = results['date_range']
        
        lines = []
        lines.append("=" * 120)
        lines.append("TIME-BASED STREAK ANALYSIS FOR MARTINGALE STRATEGY")
        lines.append("=" * 120)
        
        lines.append(f"\nData Period: {date_range['min']} to {date_range['max']} ({date_range['total_days']} days)")
        lines.append(f"Hot Streak Definition: 8+ consecutive rounds ≥ 2.0x")
        lines.append(f"Losing Streak Definition: 8+ consecutive rounds < 2.0x")
        
        # Overall summary
        lines.append("\n" + "=" * 120)
        lines.append("OVERALL SUMMARY")
        lines.append("=" * 120)
        lines.append(f"Total Hot Streaks: {len(hot_streaks)}")
        lines.append(f"Total Losing Streaks: {len(losing_streaks)}")
        lines.append(f"Hot Streaks per Day: {len(hot_streaks) / date_range['total_days']:.2f}")
        lines.append(f"Losing Streaks per Day: {len(losing_streaks) / date_range['total_days']:.2f}")
        
        # Hourly frequency summary
        lines.append("\n" + "=" * 120)
        lines.append("HOURLY FREQUENCY ANALYSIS (Average per day)")
        lines.append("=" * 120)
        lines.append(f"{'Hour':<6} {'Hot Streaks':<25} {'Losing Streaks':<25} {'Recommendation':<30}")
        lines.append("-" * 120)
        
        for hour in range(24):
            hot_stats = hot_hourly_stats[hour]
            losing_stats = losing_hourly_stats[hour]
            
            hot_avg = hot_stats['avg_per_day']
            losing_avg = losing_stats['avg_per_day']
            
            # Recommendation logic
            if hot_avg >= 1.0 and losing_avg < 0.5:
                recommendation = "🔥 EXCELLENT for martingale"
            elif hot_avg >= 0.5 and losing_avg < 1.0:
                recommendation = "✓ Good for martingale"
            elif hot_avg < 0.3 and losing_avg >= 1.0:
                recommendation = "⚠️  AVOID - High risk"
            elif hot_avg < 0.5 and losing_avg >= 0.5:
                recommendation = "⚠️  Risky"
            else:
                recommendation = "~ Neutral"
            
            hot_info = f"{hot_stats['total_count']:3d} total ({hot_avg:.2f}/day)"
            losing_info = f"{losing_stats['total_count']:3d} total ({losing_avg:.2f}/day)"
            
            lines.append(f"{hour:02d}:00  {hot_info:<25} {losing_info:<25} {recommendation:<30}")
        
        # Daily breakdown
        lines.append("\n" + "=" * 120)
        lines.append("DAILY HOURLY BREAKDOWN")
        lines.append("=" * 120)
        
        # Sort dates
        all_dates = sorted(set(list(hot_daily_hourly.keys()) + list(losing_daily_hourly.keys())))
        
        for date_str in all_dates:
            lines.append(f"\n{date_str} ({datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')})")
            lines.append("-" * 120)
            
            hot_hours = hot_daily_hourly.get(date_str, {})
            losing_hours = losing_daily_hourly.get(date_str, {})
            
            # Combine all hours that had activity
            all_hours = sorted(set(list(hot_hours.keys()) + list(losing_hours.keys())))
            
            if not all_hours:
                lines.append("  No streaks recorded this day")
                continue
            
            lines.append(f"  {'Hour':<6} {'Hot Streaks':<15} {'Losing Streaks':<15} {'Status':<20}")
            lines.append("  " + "-" * 70)
            
            for hour in all_hours:
                hot_count = hot_hours.get(hour, 0)
                losing_count = losing_hours.get(hour, 0)
                
                if hot_count > 0 and losing_count == 0:
                    status = "🔥 Hot hour!"
                elif hot_count > losing_count:
                    status = "✓ More hot"
                elif losing_count > hot_count:
                    status = "⚠️  More cold"
                else:
                    status = "~ Mixed"
                
                lines.append(f"  {hour:02d}:00  {hot_count:<15} {losing_count:<15} {status:<20}")
        
        # Top hot streaks
        lines.append("\n\n" + "=" * 120)
        lines.append("TOP 20 HOT STREAKS (8+ consecutive ≥ 2.0x)")
        lines.append("=" * 120)
        
        for rank, streak in enumerate(hot_streaks[:20], 1):
            lines.append(f"\n#{rank} - {streak['length']} consecutive rounds")
            lines.append(f"  Time: {streak['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {streak['end_time'].strftime('%H:%M:%S')}")
            lines.append(f"  Day: {streak['start_time'].strftime('%A')}, Hour: {streak['start_time'].hour:02d}:00")
            lines.append(f"  Average: {streak['avg_multiplier']:.2f}x | Range: {streak['min_multiplier']:.2f}x - {streak['max_multiplier']:.2f}x")
            
            # Show multipliers
            if len(streak['multipliers']) <= 20:
                mults_str = ', '.join(f"{m:.2f}" for m in streak['multipliers'])
            else:
                first_10 = ', '.join(f"{m:.2f}" for m in streak['multipliers'][:10])
                last_10 = ', '.join(f"{m:.2f}" for m in streak['multipliers'][-10:])
                mults_str = f"{first_10} ... {last_10}"
            
            lines.append(f"  Multipliers: [{mults_str}]")
        
        # Top losing streaks
        lines.append("\n\n" + "=" * 120)
        lines.append("TOP 20 LOSING STREAKS (8+ consecutive < 2.0x)")
        lines.append("=" * 120)
        
        for rank, streak in enumerate(losing_streaks[:20], 1):
            lines.append(f"\n#{rank} - {streak['length']} consecutive rounds")
            lines.append(f"  Time: {streak['start_time'].strftime('%Y-%m-%d %H:%M:%S')} → {streak['end_time'].strftime('%H:%M:%S')}")
            lines.append(f"  Day: {streak['start_time'].strftime('%A')}, Hour: {streak['start_time'].hour:02d}:00")
            lines.append(f"  Average: {streak['avg_multiplier']:.2f}x | Range: {streak['min_multiplier']:.2f}x - {streak['max_multiplier']:.2f}x")
            
            # Show multipliers
            if len(streak['multipliers']) <= 20:
                mults_str = ', '.join(f"{m:.2f}" for m in streak['multipliers'])
            else:
                first_10 = ', '.join(f"{m:.2f}" for m in streak['multipliers'][:10])
                last_10 = ', '.join(f"{m:.2f}" for m in streak['multipliers'][-10:])
                mults_str = f"{first_10} ... {last_10}"
            
            lines.append(f"  Multipliers: [{mults_str}]")
        
        lines.append("\n" + "=" * 120)
        lines.append("MARTINGALE STRATEGY RECOMMENDATIONS")
        lines.append("=" * 120)
        
        # Find best hours
        best_hours = []
        for hour in range(24):
            hot_avg = hot_hourly_stats[hour]['avg_per_day']
            losing_avg = losing_hourly_stats[hour]['avg_per_day']
            score = hot_avg - losing_avg
            best_hours.append((hour, hot_avg, losing_avg, score))
        
        best_hours.sort(key=lambda x: x[3], reverse=True)
        
        lines.append("\nTOP 10 BEST HOURS FOR MARTINGALE (High hot streak, low losing streak frequency):")
        lines.append("-" * 120)
        lines.append(f"{'Rank':<6} {'Hour':<8} {'Hot/Day':<12} {'Losing/Day':<12} {'Score':<10} {'Recommendation'}")
        lines.append("-" * 120)
        
        for rank, (hour, hot_avg, losing_avg, score) in enumerate(best_hours[:10], 1):
            if score > 0.5:
                rec = "🔥 Highly Recommended"
            elif score > 0:
                rec = "✓ Recommended"
            else:
                rec = "~ Neutral"
            
            lines.append(f"{rank:<6} {hour:02d}:00  {hot_avg:<12.2f} {losing_avg:<12.2f} {score:<10.2f} {rec}")
        
        lines.append("\nWORST 10 HOURS FOR MARTINGALE (Low hot streak, high losing streak frequency):")
        lines.append("-" * 120)
        lines.append(f"{'Rank':<6} {'Hour':<8} {'Hot/Day':<12} {'Losing/Day':<12} {'Score':<10} {'Recommendation'}")
        lines.append("-" * 120)
        
        for rank, (hour, hot_avg, losing_avg, score) in enumerate(reversed(best_hours[-10:]), 1):
            if score < -0.5:
                rec = "⚠️  AVOID"
            elif score < 0:
                rec = "⚠️  Not Recommended"
            else:
                rec = "~ Neutral"
            
            lines.append(f"{rank:<6} {hour:02d}:00  {hot_avg:<12.2f} {losing_avg:<12.2f} {score:<10.2f} {rec}")
        
        lines.append("\n" + "=" * 120)
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"\n✓ Report saved to: {output_path}")
    
    def create_visualizations(self, results: Dict, output_dir: str):
        """Create comprehensive time-based visualizations"""
        
        print("\nGenerating visualizations...")
        
        # 1. Heatmap: Hour x Day for hot streaks
        self.plot_daily_hourly_heatmap(
            results, 
            'hot', 
            f"{output_dir}/hot_streak_hourly_heatmap.png"
        )
        
        # 2. Heatmap: Hour x Day for losing streaks
        self.plot_daily_hourly_heatmap(
            results, 
            'losing', 
            f"{output_dir}/losing_streak_hourly_heatmap.png"
        )
        
        # 3. Combined comparison
        self.plot_hourly_comparison(
            results, 
            f"{output_dir}/streak_hourly_comparison.png"
        )
        
        # 4. Best hours ranking
        self.plot_best_hours(
            results, 
            f"{output_dir}/best_hours_for_martingale.png"
        )
        
        # 5. Daily overview
        self.plot_daily_overview(
            results, 
            f"{output_dir}/daily_streak_overview.png"
        )
        
        # 6. Streak characteristics
        self.plot_streak_characteristics(
            results, 
            f"{output_dir}/streak_characteristics.png"
        )
        
        print("✓ All visualizations generated!")
    
    def plot_daily_hourly_heatmap(self, results: Dict, streak_type: str, output_path: str):
        """Create heatmap showing frequency per hour per day"""
        
        if streak_type == 'hot':
            daily_hourly = results['hot_daily_hourly']
            title = 'Hot Streaks (8+ consecutive ≥ 2.0x) - Hourly Frequency per Day'
            cmap = 'YlOrRd'
        else:
            daily_hourly = results['losing_daily_hourly']
            title = 'Losing Streaks (8+ consecutive < 2.0x) - Hourly Frequency per Day'
            cmap = 'YlGnBu'
        
        # Prepare data matrix
        dates = sorted(daily_hourly.keys())
        hours = list(range(24))
        
        # Create matrix
        data = np.zeros((len(dates), 24))
        
        for i, date in enumerate(dates):
            hour_data = daily_hourly[date]
            for hour, count in hour_data.items():
                data[i, hour] = count
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, max(6, len(dates) * 0.5)))
        
        # Plot heatmap
        im = ax.imshow(data, cmap=cmap, aspect='auto', interpolation='nearest')
        
        # Set ticks
        ax.set_xticks(np.arange(24))
        ax.set_yticks(np.arange(len(dates)))
        ax.set_xticklabels([f'{h:02d}:00' for h in hours])
        ax.set_yticklabels([f"{d} ({datetime.strptime(d, '%Y-%m-%d').strftime('%a')})" for d in dates])
        
        # Rotate x labels
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Number of Streaks', rotation=270, labelpad=20)
        
        # Add text annotations
        for i in range(len(dates)):
            for j in range(24):
                if data[i, j] > 0:
                    text = ax.text(j, i, int(data[i, j]),
                                 ha="center", va="center", color="black" if data[i, j] < data.max()/2 else "white",
                                 fontsize=8, fontweight='bold')
        
        ax.set_xlabel('Hour of Day', fontsize=12, fontweight='bold')
        ax.set_ylabel('Date (Day of Week)', fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✓ Saved: {output_path}")
    
    def plot_hourly_comparison(self, results: Dict, output_path: str):
        """Compare hot vs losing streaks by hour"""
        
        hot_stats = results['hot_hourly_stats']
        losing_stats = results['losing_hourly_stats']
        
        hours = list(range(24))
        hot_avgs = [hot_stats[h]['avg_per_day'] for h in hours]
        losing_avgs = [losing_stats[h]['avg_per_day'] for h in hours]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))
        
        # Plot 1: Average per day comparison
        x = np.arange(24)
        width = 0.35
        
        bars1 = ax1.bar(x - width/2, hot_avgs, width, label='Hot Streaks (≥2.0x)', 
                       color='#FF6B6B', alpha=0.8, edgecolor='black', linewidth=0.5)
        bars2 = ax1.bar(x + width/2, losing_avgs, width, label='Losing Streaks (<2.0x)', 
                       color='#4ECDC4', alpha=0.8, edgecolor='black', linewidth=0.5)
        
        ax1.set_xlabel('Hour of Day', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Average Occurrences per Day', fontsize=12, fontweight='bold')
        ax1.set_title('Hot vs Losing Streaks - Average Frequency per Hour', fontsize=14, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels([f'{h:02d}:00' for h in hours])
        ax1.legend(fontsize=11)
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax1.text(bar.get_x() + bar.get_width()/2., height,
                           f'{height:.1f}', ha='center', va='bottom', fontsize=7)
        
        # Plot 2: Net advantage (hot - losing)
        net_advantage = [hot_avgs[i] - losing_avgs[i] for i in range(24)]
        colors = ['#90EE90' if x > 0 else '#FFB6C1' for x in net_advantage]
        
        bars3 = ax2.bar(x, net_advantage, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
        
        ax2.set_xlabel('Hour of Day', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Net Advantage (Hot - Losing)', fontsize=12, fontweight='bold')
        ax2.set_title('Martingale Strategy Advantage by Hour (Positive = Good, Negative = Bad)', 
                     fontsize=14, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels([f'{h:02d}:00' for h in hours])
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Highlight best/worst hours
        best_idx = net_advantage.index(max(net_advantage))
        worst_idx = net_advantage.index(min(net_advantage))
        
        ax2.text(best_idx, net_advantage[best_idx], '  🔥 BEST', 
                ha='left', va='bottom', fontsize=10, fontweight='bold', color='darkgreen')
        ax2.text(worst_idx, net_advantage[worst_idx], '  ⚠️ WORST', 
                ha='left', va='top', fontsize=10, fontweight='bold', color='darkred')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✓ Saved: {output_path}")
    
    def plot_best_hours(self, results: Dict, output_path: str):
        """Rank hours by martingale suitability"""
        
        hot_stats = results['hot_hourly_stats']
        losing_stats = results['losing_hourly_stats']
        
        # Calculate scores
        hours_data = []
        for hour in range(24):
            hot_avg = hot_stats[hour]['avg_per_day']
            losing_avg = losing_stats[hour]['avg_per_day']
            score = hot_avg - losing_avg
            
            hours_data.append({
                'hour': hour,
                'hot_avg': hot_avg,
                'losing_avg': losing_avg,
                'score': score
            })
        
        # Sort by score
        hours_data.sort(key=lambda x: x['score'], reverse=True)
        
        # Create figure
        fig, ax = plt.subplots(figsize=(14, 10))
        
        y_pos = np.arange(24)
        scores = [h['score'] for h in hours_data]
        colors = ['#90EE90' if s > 0 else '#FFB6C1' for s in scores]
        
        bars = ax.barh(y_pos, scores, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
        
        # Add vertical line at 0
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1)
        
        # Labels
        hour_labels = [f"{h['hour']:02d}:00 (H:{h['hot_avg']:.1f} L:{h['losing_avg']:.1f})" 
                      for h in hours_data]
        ax.set_yticks(y_pos)
        ax.set_yticklabels(hour_labels, fontsize=9)
        
        ax.set_xlabel('Martingale Advantage Score (Hot/day - Losing/day)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Hour (with Hot/Losing averages)', fontsize=12, fontweight='bold')
        ax.set_title('Best Hours for Martingale Strategy\n(Top = Best, Bottom = Worst)', 
                    fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')
        
        # Add score labels
        for i, (bar, score) in enumerate(zip(bars, scores)):
            width = bar.get_width()
            label_x = width + (0.05 if width > 0 else -0.05)
            ha = 'left' if width > 0 else 'right'
            
            ax.text(label_x, bar.get_y() + bar.get_height()/2, f'{score:.2f}',
                   ha=ha, va='center', fontsize=8, fontweight='bold')
        
        # Add zones
        ax.axhspan(0, 7.5, alpha=0.1, color='green', zorder=0)
        ax.text(ax.get_xlim()[1] * 0.95, 4, '🔥 BEST HOURS', 
               ha='right', va='center', fontsize=11, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7))
        
        ax.axhspan(16.5, 24, alpha=0.1, color='red', zorder=0)
        ax.text(ax.get_xlim()[1] * 0.95, 20, '⚠️ WORST HOURS', 
               ha='right', va='center', fontsize=11, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.7))
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✓ Saved: {output_path}")
    
    def plot_daily_overview(self, results: Dict, output_path: str):
        """Overview of streaks per day"""
        
        hot_daily = results['hot_daily_hourly']
        losing_daily = results['losing_daily_hourly']
        
        # Calculate daily totals
        all_dates = sorted(set(list(hot_daily.keys()) + list(losing_daily.keys())))
        
        hot_daily_totals = []
        losing_daily_totals = []
        
        for date in all_dates:
            hot_total = sum(hot_daily.get(date, {}).values())
            losing_total = sum(losing_daily.get(date, {}).values())
            hot_daily_totals.append(hot_total)
            losing_daily_totals.append(losing_total)
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
        
        x = np.arange(len(all_dates))
        width = 0.35
        
        # Plot 1: Daily totals
        bars1 = ax1.bar(x - width/2, hot_daily_totals, width, label='Hot Streaks', 
                       color='#FF6B6B', alpha=0.8, edgecolor='black', linewidth=0.5)
        bars2 = ax1.bar(x + width/2, losing_daily_totals, width, label='Losing Streaks', 
                       color='#4ECDC4', alpha=0.8, edgecolor='black', linewidth=0.5)
        
        ax1.set_xlabel('Date', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Number of Streaks', fontsize=11, fontweight='bold')
        ax1.set_title('Daily Streak Count Overview', fontsize=13, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels([f"{d}\n({datetime.strptime(d, '%Y-%m-%d').strftime('%a')})" 
                            for d in all_dates], rotation=0, fontsize=9)
        ax1.legend(fontsize=10)
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Add value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax1.text(bar.get_x() + bar.get_width()/2., height,
                           f'{int(height)}', ha='center', va='bottom', fontsize=8)
        
        # Plot 2: Daily ratio (hot/losing)
        ratios = []
        for hot, losing in zip(hot_daily_totals, losing_daily_totals):
            if losing > 0:
                ratios.append(hot / losing)
            elif hot > 0:
                ratios.append(hot)  # If no losing streaks, show hot count
            else:
                ratios.append(0)
        
        colors = ['#90EE90' if r >= 1 else '#FFB6C1' for r in ratios]
        bars3 = ax2.bar(x, ratios, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
        ax2.axhline(y=1, color='black', linestyle='--', linewidth=1.5, label='Equal (1:1)')
        
        ax2.set_xlabel('Date', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Hot/Losing Ratio', fontsize=11, fontweight='bold')
        ax2.set_title('Daily Hot/Losing Ratio (>1 = More Hot, <1 = More Losing)', fontsize=13, fontweight='bold')
        ax2.set_xticks(x)
        ax2.set_xticklabels([f"{d}\n({datetime.strptime(d, '%Y-%m-%d').strftime('%a')})" 
                            for d in all_dates], rotation=0, fontsize=9)
        ax2.legend(fontsize=10)
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Add value labels
        for bar, ratio in zip(bars3, ratios):
            height = bar.get_height()
            if height > 0:
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                       f'{ratio:.2f}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✓ Saved: {output_path}")
    
    def plot_streak_characteristics(self, results: Dict, output_path: str):
        """Plot characteristics of hot and losing streaks"""
        
        hot_streaks = results['hot_streaks']
        losing_streaks = results['losing_streaks']
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Streak Characteristics Comparison', fontsize=16, fontweight='bold')
        
        # Plot 1: Length distribution
        ax1 = axes[0, 0]
        
        hot_lengths = [s['length'] for s in hot_streaks]
        losing_lengths = [s['length'] for s in losing_streaks]
        
        ax1.hist(hot_lengths, bins=30, alpha=0.6, color='#FF6B6B', label='Hot Streaks', edgecolor='black', linewidth=0.5)
        ax1.hist(losing_lengths, bins=30, alpha=0.6, color='#4ECDC4', label='Losing Streaks', edgecolor='black', linewidth=0.5)
        
        ax1.set_xlabel('Streak Length (rounds)', fontsize=10)
        ax1.set_ylabel('Frequency', fontsize=10)
        ax1.set_title('Streak Length Distribution', fontsize=11, fontweight='bold')
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)
        
        # Plot 2: Average multiplier
        ax2 = axes[0, 1]
        
        hot_avgs = [s['avg_multiplier'] for s in hot_streaks]
        losing_avgs = [s['avg_multiplier'] for s in losing_streaks]
        
        bp = ax2.boxplot([hot_avgs, losing_avgs], labels=['Hot Streaks', 'Losing Streaks'],
                         patch_artist=True)
        
        bp['boxes'][0].set_facecolor('#FF6B6B')
        bp['boxes'][1].set_facecolor('#4ECDC4')
        
        ax2.set_ylabel('Average Multiplier', fontsize=10)
        ax2.set_title('Average Multiplier in Streaks', fontsize=11, fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Plot 3: Duration
        ax3 = axes[1, 0]
        
        hot_durations = [(s['end_time'] - s['start_time']).total_seconds() / 60 for s in hot_streaks]
        losing_durations = [(s['end_time'] - s['start_time']).total_seconds() / 60 for s in losing_streaks]
        
        ax3.hist(hot_durations, bins=30, alpha=0.6, color='#FF6B6B', label='Hot Streaks', edgecolor='black', linewidth=0.5)
        ax3.hist(losing_durations, bins=30, alpha=0.6, color='#4ECDC4', label='Losing Streaks', edgecolor='black', linewidth=0.5)
        
        ax3.set_xlabel('Duration (minutes)', fontsize=10)
        ax3.set_ylabel('Frequency', fontsize=10)
        ax3.set_title('Streak Duration', fontsize=11, fontweight='bold')
        ax3.legend(fontsize=9)
        ax3.grid(True, alpha=0.3)
        
        # Plot 4: Summary stats table
        ax4 = axes[1, 1]
        ax4.axis('off')
        
        hot_stats_text = f"""
HOT STREAKS (8+ consecutive ≥ 2.0x)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Count:        {len(hot_streaks)}
Avg Length:         {np.mean(hot_lengths):.1f} rounds
Longest:            {max(hot_lengths) if hot_lengths else 0} rounds
Avg Multiplier:     {np.mean(hot_avgs):.2f}x
Avg Duration:       {np.mean(hot_durations):.1f} min

LOSING STREAKS (8+ consecutive < 2.0x)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Count:        {len(losing_streaks)}
Avg Length:         {np.mean(losing_lengths):.1f} rounds
Longest:            {max(losing_lengths) if losing_lengths else 0} rounds
Avg Multiplier:     {np.mean(losing_avgs):.2f}x
Avg Duration:       {np.mean(losing_durations):.1f} min

COMPARISON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hot/Losing Ratio:   {len(hot_streaks) / len(losing_streaks) if losing_streaks else 0:.2f}
        """
        
        ax4.text(0.1, 0.9, hot_stats_text, transform=ax4.transAxes,
                fontsize=10, verticalalignment='top', family='monospace',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.5))
        
        ax4.set_title('Summary Statistics', fontsize=11, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✓ Saved: {output_path}")
    
    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Time-based streak analysis for martingale strategy optimization'
    )
    parser.add_argument(
        '--db', 
        default='./crasher_data.db',
        help='Path to database file (default: ./crasher_data.db)'
    )
    parser.add_argument(
        '--output-dir',
        default='data-analyze/outputs',
        help='Output directory (default: data-analyze/outputs)'
    )
    
    args = parser.parse_args()
    
    # Check for required packages
    try:
        import matplotlib
        import seaborn
        import numpy
    except ImportError:
        print("❌ Missing required packages!")
        print("\nInstall with:")
        print("  pip install matplotlib seaborn numpy --break-system-packages")
        sys.exit(1)
    
    print("=" * 100)
    print("TIME-BASED STREAK ANALYZER FOR MARTINGALE STRATEGY")
    print("=" * 100)
    print(f"\nDatabase: {args.db}")
    print(f"Output Directory: {args.output_dir}")
    print("\nAnalyzing:")
    print("  • Hot Streaks: 8+ consecutive rounds ≥ 2.0x")
    print("  • Losing Streaks: 8+ consecutive rounds < 2.0x")
    print("  • Hourly frequency per day")
    print("  • Best hours for martingale strategy")
    print("\n" + "=" * 100)
    
    analyzer = TimeBasedStreakAnalyzer(args.db)
    
    try:
        import os
        os.makedirs(args.output_dir, exist_ok=True)
        
        # Analyze
        results = analyzer.analyze_all()
        
        if not results:
            print("\n❌ No results generated. Check if your database has session assignments.")
            sys.exit(1)
        
        # Generate report
        report_path = f"{args.output_dir}/martingale_time_analysis.txt"
        analyzer.generate_report(results, report_path)
        
        # Create visualizations
        analyzer.create_visualizations(results, args.output_dir)
        
        print("\n" + "=" * 100)
        print("GENERATED FILES:")
        print("=" * 100)
        print(f"  Report: {report_path}")
        print(f"  Visualizations:")
        print(f"    - {args.output_dir}/hot_streak_hourly_heatmap.png")
        print(f"    - {args.output_dir}/losing_streak_hourly_heatmap.png")
        print(f"    - {args.output_dir}/streak_hourly_comparison.png")
        print(f"    - {args.output_dir}/best_hours_for_martingale.png")
        print(f"    - {args.output_dir}/daily_streak_overview.png")
        print(f"    - {args.output_dir}/streak_characteristics.png")
        print("=" * 100)
        
        print("\n✓ Analysis complete!")
        print("\n💡 Check 'martingale_time_analysis.txt' for hour-by-hour recommendations!")
        
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
