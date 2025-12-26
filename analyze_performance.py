#!/usr/bin/env python3
"""
Performance Analysis Tool
Analyzes debug database to identify delay sources
"""

import sqlite3
import sys
from datetime import datetime
from typing import List, Tuple


class PerformanceAnalyzer:
    """Analyze performance metrics from debug database"""
    
    def __init__(self, db_path: str = "./crasher_data_debug.db"):
        self.conn = sqlite3.connect(db_path)
    
    def get_timing_summary(self) -> dict:
        """Get summary statistics on timing"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_rounds,
                AVG(total_delay_ms) as avg_delay,
                MIN(total_delay_ms) as min_delay,
                MAX(total_delay_ms) as max_delay,
                AVG(script_execution_ms) as avg_script,
                AVG(db_write_ms) as avg_db,
                AVG(detection_delay_ms) as avg_detection
            FROM performance_metrics
            WHERE total_delay_ms IS NOT NULL
        """)
        
        row = cursor.fetchone()
        
        return {
            'total_rounds': row[0],
            'avg_delay_ms': row[1],
            'min_delay_ms': row[2],
            'max_delay_ms': row[3],
            'avg_script_ms': row[4],
            'avg_db_ms': row[5],
            'avg_detection_ms': row[6]
        }
    
    def get_system_summary(self) -> dict:
        """Get system resource summary"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                AVG(cpu_percent) as avg_cpu,
                MAX(cpu_percent) as max_cpu,
                AVG(ram_percent) as avg_ram,
                MAX(ram_percent) as max_ram,
                AVG(ram_available_mb) as avg_ram_avail,
                MIN(ram_available_mb) as min_ram_avail
            FROM performance_metrics
        """)
        
        row = cursor.fetchone()
        
        return {
            'avg_cpu': row[0],
            'max_cpu': row[1],
            'avg_ram': row[2],
            'max_ram': row[3],
            'avg_ram_avail': row[4],
            'min_ram_avail': row[5]
        }
    
    def get_slow_rounds(self, threshold_ms: int = 5000) -> List[Tuple]:
        """Get rounds that were slower than threshold"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                p.id,
                p.multiplier,
                p.total_delay_ms,
                p.script_execution_ms,
                p.db_write_ms,
                p.cpu_percent,
                p.ram_percent,
                p.timestamp
            FROM performance_metrics p
            WHERE p.total_delay_ms > ?
            ORDER BY p.total_delay_ms DESC
        """, (threshold_ms,))
        
        return cursor.fetchall()
    
    def get_network_usage(self) -> dict:
        """Get network usage statistics"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                network_sent_mb,
                network_recv_mb,
                timestamp
            FROM system_snapshots
            ORDER BY timestamp
        """)
        
        rows = cursor.fetchall()
        
        if not rows:
            return {'available': False}
        
        first = rows[0]
        last = rows[-1]
        
        return {
            'available': True,
            'total_sent_mb': last[0],
            'total_recv_mb': last[1],
            'duration': (datetime.fromisoformat(last[2]) - datetime.fromisoformat(first[2])).total_seconds() / 60
        }
    
    def get_delay_distribution(self) -> dict:
        """Get distribution of delays"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN total_delay_ms < 1000 THEN 1 ELSE 0 END) as under_1s,
                SUM(CASE WHEN total_delay_ms BETWEEN 1000 AND 3000 THEN 1 ELSE 0 END) as between_1_3s,
                SUM(CASE WHEN total_delay_ms BETWEEN 3000 AND 5000 THEN 1 ELSE 0 END) as between_3_5s,
                SUM(CASE WHEN total_delay_ms BETWEEN 5000 AND 10000 THEN 1 ELSE 0 END) as between_5_10s,
                SUM(CASE WHEN total_delay_ms > 10000 THEN 1 ELSE 0 END) as over_10s
            FROM performance_metrics
            WHERE total_delay_ms IS NOT NULL
        """)
        
        row = cursor.fetchone()
        
        return {
            'under_1s': row[0] or 0,
            'between_1_3s': row[1] or 0,
            'between_3_5s': row[2] or 0,
            'between_5_10s': row[3] or 0,
            'over_10s': row[4] or 0
        }
    
    def analyze_correlation(self):
        """Analyze correlation between system resources and delays"""
        cursor = self.conn.cursor()
        
        # Get rounds with high CPU
        cursor.execute("""
            SELECT AVG(total_delay_ms)
            FROM performance_metrics
            WHERE cpu_percent > 70 AND total_delay_ms IS NOT NULL
        """)
        high_cpu_delay = cursor.fetchone()[0]
        
        # Get rounds with low CPU
        cursor.execute("""
            SELECT AVG(total_delay_ms)
            FROM performance_metrics
            WHERE cpu_percent < 30 AND total_delay_ms IS NOT NULL
        """)
        low_cpu_delay = cursor.fetchone()[0]
        
        # Get rounds with high RAM
        cursor.execute("""
            SELECT AVG(total_delay_ms)
            FROM performance_metrics
            WHERE ram_percent > 70 AND total_delay_ms IS NOT NULL
        """)
        high_ram_delay = cursor.fetchone()[0]
        
        # Get rounds with low RAM
        cursor.execute("""
            SELECT AVG(total_delay_ms)
            FROM performance_metrics
            WHERE ram_percent < 30 AND total_delay_ms IS NOT NULL
        """)
        low_ram_delay = cursor.fetchone()[0]
        
        return {
            'high_cpu_avg_delay': high_cpu_delay,
            'low_cpu_avg_delay': low_cpu_delay,
            'high_ram_avg_delay': high_ram_delay,
            'low_ram_avg_delay': low_ram_delay
        }
    
    def generate_report(self):
        """Generate comprehensive performance report"""
        print("=" * 80)
        print("CRASHER BOT PERFORMANCE ANALYSIS REPORT")
        print("=" * 80)
        
        # Timing Summary
        timing = self.get_timing_summary()
        
        if timing['total_rounds'] == 0:
            print("\n❌ No data found in database")
            print("Run the debug bot first: python crasher_bot_debug.py")
            return
        
        print(f"\n📊 TIMING ANALYSIS ({timing['total_rounds']} rounds)")
        print("─" * 80)
        print(f"  Average Total Delay:     {timing['avg_delay_ms']:.1f} ms ({timing['avg_delay_ms']/1000:.2f}s)")
        print(f"  Min/Max Delay:           {timing['min_delay_ms']:.0f} ms / {timing['max_delay_ms']:.0f} ms")
        print(f"  Average Script Exec:     {timing['avg_script_ms']:.1f} ms")
        print(f"  Average DB Write:        {timing['avg_db_ms']:.1f} ms")
        
        # Delay Assessment
        avg_delay_s = timing['avg_delay_ms'] / 1000
        print(f"\n  ASSESSMENT:", end=" ")
        
        if avg_delay_s > 10:
            print("⚠️  SEVERE DELAY (>10s)")
            print("  └─ This is abnormally high. Likely causes:")
            print("     • Slow network connection to game server")
            print("     • High network latency")
            print("     • Browser/Selenium performance issues")
        elif avg_delay_s > 5:
            print("⚠️  HIGH DELAY (5-10s)")
            print("  └─ This is higher than normal. Possible causes:")
            print("     • Network latency")
            print("     • Server location distance")
            print("     • System resource constraints")
        elif avg_delay_s > 2:
            print("⚠️  MODERATE DELAY (2-5s)")
            print("  └─ Slightly higher than ideal. May be normal for:")
            print("     • Remote server connections")
            print("     • Virtual/cloud environments")
        else:
            print("✓ NORMAL (<2s)")
        
        # Delay Distribution
        dist = self.get_delay_distribution()
        total = sum(dist.values())
        
        print(f"\n📈 DELAY DISTRIBUTION")
        print("─" * 80)
        print(f"  < 1s:       {dist['under_1s']:4d} rounds ({dist['under_1s']/total*100:5.1f}%)")
        print(f"  1-3s:       {dist['between_1_3s']:4d} rounds ({dist['between_1_3s']/total*100:5.1f}%)")
        print(f"  3-5s:       {dist['between_3_5s']:4d} rounds ({dist['between_3_5s']/total*100:5.1f}%)")
        print(f"  5-10s:      {dist['between_5_10s']:4d} rounds ({dist['between_5_10s']/total*100:5.1f}%)")
        print(f"  > 10s:      {dist['over_10s']:4d} rounds ({dist['over_10s']/total*100:5.1f}%)")
        
        # System Resources
        system = self.get_system_summary()
        
        print(f"\n💻 SYSTEM RESOURCES")
        print("─" * 80)
        print(f"  Average CPU Usage:       {system['avg_cpu']:.1f}% (max: {system['max_cpu']:.1f}%)")
        print(f"  Average RAM Usage:       {system['avg_ram']:.1f}% (max: {system['max_ram']:.1f}%)")
        print(f"  Average RAM Available:   {system['avg_ram_avail']:.0f} MB (min: {system['min_ram_avail']:.0f} MB)")
        
        # Resource Assessment
        issues = []
        if system['avg_cpu'] > 80:
            issues.append("HIGH CPU USAGE - May cause performance degradation")
        if system['max_cpu'] > 95:
            issues.append("CPU SATURATION - System is struggling")
        if system['avg_ram'] > 80:
            issues.append("HIGH RAM USAGE - May cause swapping")
        if system['min_ram_avail'] < 500:
            issues.append("LOW RAM AVAILABLE - Risk of out-of-memory")
        
        if issues:
            print(f"\n  ⚠️  RESOURCE ISSUES DETECTED:")
            for issue in issues:
                print(f"     • {issue}")
        else:
            print(f"\n  ✓ System resources healthy")
        
        # Network Usage
        network = self.get_network_usage()
        
        if network['available']:
            print(f"\n🌐 NETWORK USAGE")
            print("─" * 80)
            print(f"  Total Sent:     {network['total_sent_mb']:.2f} MB")
            print(f"  Total Received: {network['total_recv_mb']:.2f} MB")
            print(f"  Duration:       {network['duration']:.1f} minutes")
            
            if network['duration'] > 0:
                sent_rate = network['total_sent_mb'] / network['duration']
                recv_rate = network['total_recv_mb'] / network['duration']
                print(f"  Upload Rate:    {sent_rate:.2f} MB/min")
                print(f"  Download Rate:  {recv_rate:.2f} MB/min")
        
        # Correlation Analysis
        print(f"\n🔍 CORRELATION ANALYSIS")
        print("─" * 80)
        
        corr = self.analyze_correlation()
        
        if corr['high_cpu_avg_delay'] and corr['low_cpu_avg_delay']:
            cpu_impact = corr['high_cpu_avg_delay'] - corr['low_cpu_avg_delay']
            print(f"  CPU Impact on Delay:")
            print(f"    High CPU (>70%): {corr['high_cpu_avg_delay']:.0f} ms avg delay")
            print(f"    Low CPU (<30%):  {corr['low_cpu_avg_delay']:.0f} ms avg delay")
            print(f"    Difference:      {cpu_impact:+.0f} ms", end="")
            
            if abs(cpu_impact) > 1000:
                print(" ⚠️  SIGNIFICANT")
            else:
                print(" (minimal)")
        
        if corr['high_ram_avg_delay'] and corr['low_ram_avg_delay']:
            ram_impact = corr['high_ram_avg_delay'] - corr['low_ram_avg_delay']
            print(f"\n  RAM Impact on Delay:")
            print(f"    High RAM (>70%): {corr['high_ram_avg_delay']:.0f} ms avg delay")
            print(f"    Low RAM (<30%):  {corr['low_ram_avg_delay']:.0f} ms avg delay")
            print(f"    Difference:      {ram_impact:+.0f} ms", end="")
            
            if abs(ram_impact) > 1000:
                print(" ⚠️  SIGNIFICANT")
            else:
                print(" (minimal)")
        
        # Slowest Rounds
        slow_rounds = self.get_slow_rounds(threshold_ms=8000)
        
        if slow_rounds:
            print(f"\n🐌 SLOWEST ROUNDS (>{8000}ms)")
            print("─" * 80)
            
            for i, (rid, mult, delay, script, db, cpu, ram, ts) in enumerate(slow_rounds[:10], 1):
                print(f"  #{i}: {delay:.0f}ms - {mult}x @ {ts}")
                print(f"      Script: {script:.0f}ms | DB: {db:.0f}ms | CPU: {cpu:.0f}% | RAM: {ram:.0f}%")
            
            if len(slow_rounds) > 10:
                print(f"  ... and {len(slow_rounds) - 10} more slow rounds")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS")
        print("─" * 80)
        
        recommendations = []
        
        if avg_delay_s > 7:
            recommendations.append("CRITICAL: Average delay is very high (>7s)")
            recommendations.append("  Action: Check network connection to game server")
            recommendations.append("  Action: Run 'ping 1000bet.in' to check latency")
            recommendations.append("  Action: Use 'traceroute 1000bet.in' to identify slow hops")
        
        if timing['avg_script_ms'] > 500:
            recommendations.append("Script execution is slow (>500ms)")
            recommendations.append("  Action: This is likely a browser/Selenium issue")
            recommendations.append("  Action: Try using Chrome instead of Chromium")
            recommendations.append("  Action: Ensure Chrome driver version matches Chrome version")
        
        if system['avg_cpu'] > 70:
            recommendations.append("High CPU usage detected")
            recommendations.append("  Action: Close other applications")
            recommendations.append("  Action: Check for background processes")
        
        if system['avg_ram'] > 70:
            recommendations.append("High RAM usage detected")
            recommendations.append("  Action: Increase available RAM")
            recommendations.append("  Action: Close memory-intensive applications")
        
        if dist['over_10s'] / total > 0.1:  # More than 10% of rounds over 10s
            recommendations.append(f"{dist['over_10s']/total*100:.0f}% of rounds had >10s delay")
            recommendations.append("  Action: This suggests network or connectivity issues")
            recommendations.append("  Action: Consider running bot closer to game server location")
        
        if not recommendations:
            recommendations.append("✓ No major issues detected")
            recommendations.append("  The delay may be due to:")
            recommendations.append("  • Geographic distance to game server")
            recommendations.append("  • Normal game server response time")
            recommendations.append("  • Browser rendering overhead")
        
        for rec in recommendations:
            print(f"  {rec}")
        
        print("\n" + "=" * 80)
        print("For detailed data, query: crasher_data_debug.db")
        print("=" * 80)
    
    def export_csv(self, output_file: str = "performance_metrics.csv"):
        """Export performance metrics to CSV"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                p.id,
                p.multiplier,
                p.total_delay_ms,
                p.script_execution_ms,
                p.db_write_ms,
                p.cpu_percent,
                p.ram_percent,
                p.ram_available_mb,
                p.timestamp
            FROM performance_metrics p
            ORDER BY p.id
        """)
        
        import csv
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'id', 'multiplier', 'total_delay_ms', 'script_execution_ms',
                'db_write_ms', 'cpu_percent', 'ram_percent', 'ram_available_mb', 'timestamp'
            ])
            
            for row in cursor.fetchall():
                writer.writerow(row)
        
        print(f"✓ Exported to {output_file}")
    
    def close(self):
        self.conn.close()


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python analyze_performance.py [options]")
        print("\nOptions:")
        print("  --db <path>      Database path (default: ./crasher_data_debug.db)")
        print("  --export-csv     Export metrics to CSV file")
        print("  --csv <path>     CSV output path (default: performance_metrics.csv)")
        print("\nExamples:")
        print("  python analyze_performance.py")
        print("  python analyze_performance.py --db ./crasher_data_debug.db")
        print("  python analyze_performance.py --export-csv")
        return
    
    db_path = "./crasher_data_debug.db"
    export_csv = False
    csv_path = "performance_metrics.csv"
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--db" and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--export-csv":
            export_csv = True
            i += 1
        elif sys.argv[i] == "--csv" and i + 1 < len(sys.argv):
            csv_path = sys.argv[i + 1]
            export_csv = True
            i += 2
        else:
            i += 1
    
    try:
        analyzer = PerformanceAnalyzer(db_path)
        analyzer.generate_report()
        
        if export_csv:
            print()
            analyzer.export_csv(csv_path)
        
        analyzer.close()
        
    except sqlite3.OperationalError as e:
        print(f"❌ Database error: {e}")
        print(f"\nMake sure the database exists: {db_path}")
        print("Run the debug bot first: python crasher_bot_debug.py")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
