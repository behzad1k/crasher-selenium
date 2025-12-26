#!/usr/bin/env python3
"""
Network Diagnostic Tool
Tests connection speed and latency to game server
"""

import time
import subprocess
import platform
import socket
import requests
from datetime import datetime


def ping_test(host: str, count: int = 10) -> dict:
    """Test ping latency to host"""
    print(f"\n🌐 Testing ping to {host}...")
    print("─" * 60)
    
    # Determine ping command based on OS
    param = "-n" if platform.system().lower() == "windows" else "-c"
    
    try:
        # Run ping command
        result = subprocess.run(
            ["ping", param, str(count), host],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        output = result.stdout
        print(output)
        
        # Parse results
        if platform.system().lower() == "windows":
            # Windows format
            if "Average = " in output:
                avg_line = [line for line in output.split('\n') if "Average = " in line][0]
                avg_ms = float(avg_line.split("Average = ")[1].replace("ms", "").strip())
                return {"success": True, "avg_ms": avg_ms}
        else:
            # Linux/Mac format
            if "avg" in output.lower():
                # Look for line like: rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms
                for line in output.split('\n'):
                    if 'min/avg/max' in line.lower() or 'rtt' in line.lower():
                        parts = line.split('=')[1].strip().split('/')
                        avg_ms = float(parts[1])
                        return {"success": True, "avg_ms": avg_ms}
        
        return {"success": False, "error": "Could not parse ping results"}
        
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Ping timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def dns_test(host: str) -> dict:
    """Test DNS resolution time"""
    print(f"\n🔍 Testing DNS resolution for {host}...")
    print("─" * 60)
    
    try:
        start = time.time()
        ip = socket.gethostbyname(host)
        duration = (time.time() - start) * 1000
        
        print(f"  Resolved to: {ip}")
        print(f"  Time taken: {duration:.1f}ms")
        
        return {"success": True, "ip": ip, "time_ms": duration}
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return {"success": False, "error": str(e)}


def http_test(url: str, count: int = 5) -> dict:
    """Test HTTP request latency"""
    print(f"\n📡 Testing HTTP requests to {url}...")
    print("─" * 60)
    
    timings = []
    
    for i in range(count):
        try:
            start = time.time()
            response = requests.get(url, timeout=10)
            duration = (time.time() - start) * 1000
            
            timings.append(duration)
            print(f"  Request {i+1}: {duration:.0f}ms (status: {response.status_code})")
            
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  Request {i+1}: Failed - {e}")
    
    if timings:
        avg = sum(timings) / len(timings)
        min_time = min(timings)
        max_time = max(timings)
        
        print(f"\n  Average: {avg:.0f}ms")
        print(f"  Min/Max: {min_time:.0f}ms / {max_time:.0f}ms")
        
        return {
            "success": True,
            "avg_ms": avg,
            "min_ms": min_time,
            "max_ms": max_time,
            "count": len(timings)
        }
    else:
        return {"success": False, "error": "All requests failed"}


def traceroute_test(host: str):
    """Run traceroute to show network path"""
    print(f"\n🗺️  Network path to {host}...")
    print("─" * 60)
    
    # Determine traceroute command based on OS
    if platform.system().lower() == "windows":
        cmd = ["tracert", "-d", "-h", "15", host]
    else:
        cmd = ["traceroute", "-m", "15", "-n", host]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print(result.stdout)
    except subprocess.TimeoutExpired:
        print("  ⚠️  Traceroute timeout (some routes may be slow)")
    except FileNotFoundError:
        print("  ⚠️  Traceroute not available on this system")
    except Exception as e:
        print(f"  ❌ Error: {e}")


def bandwidth_test(url: str):
    """Simple download speed test"""
    print(f"\n⚡ Testing download speed from {url}...")
    print("─" * 60)
    
    try:
        start = time.time()
        response = requests.get(url, timeout=30, stream=True)
        
        total_bytes = 0
        chunk_count = 0
        
        for chunk in response.iter_content(chunk_size=8192):
            total_bytes += len(chunk)
            chunk_count += 1
            
            # Stop after ~1MB or 100 chunks to keep test quick
            if chunk_count >= 100:
                break
        
        duration = time.time() - start
        
        if duration > 0:
            speed_mbps = (total_bytes * 8) / (duration * 1_000_000)
            print(f"  Downloaded: {total_bytes / 1024:.1f} KB in {duration:.2f}s")
            print(f"  Speed: {speed_mbps:.2f} Mbps")
            
            return {"success": True, "mbps": speed_mbps}
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return {"success": False, "error": str(e)}


def main():
    print("=" * 60)
    print("CRASHER BOT - NETWORK DIAGNOSTIC TOOL")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    game_host = "1000bet.in"
    game_url = "https://1000bet.in"
    
    # System info
    print(f"\n💻 SYSTEM INFO")
    print("─" * 60)
    print(f"  OS: {platform.system()} {platform.release()}")
    print(f"  Python: {platform.python_version()}")
    
    # DNS Test
    dns_result = dns_test(game_host)
    
    # Ping Test
    ping_result = ping_test(game_host, count=10)
    
    # HTTP Test
    http_result = http_test(game_url, count=5)
    
    # Traceroute (optional, can be slow)
    import sys
    if "--traceroute" in sys.argv or "-t" in sys.argv:
        traceroute_test(game_host)
    
    # Bandwidth test (optional)
    if "--bandwidth" in sys.argv or "-b" in sys.argv:
        bandwidth_test(game_url)
    
    # Summary
    print("\n" + "=" * 60)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 60)
    
    issues = []
    
    if dns_result["success"]:
        print(f"✓ DNS Resolution: {dns_result['time_ms']:.1f}ms")
        if dns_result['time_ms'] > 100:
            issues.append("Slow DNS resolution (>100ms)")
    else:
        print(f"✗ DNS Resolution: Failed")
        issues.append("DNS resolution failed")
    
    if ping_result["success"]:
        print(f"✓ Average Ping: {ping_result['avg_ms']:.1f}ms")
        
        if ping_result['avg_ms'] > 200:
            issues.append(f"High ping latency ({ping_result['avg_ms']:.0f}ms)")
            print("  ⚠️  High latency detected")
        elif ping_result['avg_ms'] > 100:
            issues.append(f"Moderate ping latency ({ping_result['avg_ms']:.0f}ms)")
    else:
        print(f"✗ Ping: Failed")
        issues.append("Ping test failed")
    
    if http_result["success"]:
        print(f"✓ HTTP Requests: {http_result['avg_ms']:.0f}ms average")
        
        if http_result['avg_ms'] > 1000:
            issues.append(f"Slow HTTP responses ({http_result['avg_ms']:.0f}ms)")
            print("  ⚠️  Slow HTTP responses")
    else:
        print(f"✗ HTTP Requests: Failed")
        issues.append("HTTP requests failed")
    
    # Assessment
    print("\n" + "=" * 60)
    print("ASSESSMENT")
    print("=" * 60)
    
    if not issues:
        print("✓ Network connection appears healthy")
        print("\nIf you're experiencing 7-13 second delays, the issue is likely:")
        print("  • Browser/Selenium rendering delay")
        print("  • System resource constraints")
        print("  • Game server response time")
        print("\nRun the debug bot to identify: python crasher_bot_debug.py")
    else:
        print("⚠️  Network issues detected:\n")
        for issue in issues:
            print(f"  • {issue}")
        
        print("\nRecommendations:")
        
        if any("ping" in i.lower() or "latency" in i.lower() for i in issues):
            print("  • Check your internet connection")
            print("  • Try connecting from a server closer to the game")
            print("  • Consider using a VPN with better routing")
        
        if any("dns" in i.lower() for i in issues):
            print("  • Try using Google DNS (8.8.8.8) or Cloudflare DNS (1.1.1.1)")
        
        if any("http" in i.lower() for i in issues):
            print("  • Game server may be experiencing issues")
            print("  • Check server status")
    
    print("\n" + "=" * 60)
    print("For detailed performance analysis, run:")
    print("  1. python crasher_bot_debug.py 50")
    print("  2. python analyze_performance.py")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python network_test.py [options]")
        print("\nOptions:")
        print("  -t, --traceroute    Include traceroute test (slower)")
        print("  -b, --bandwidth     Include bandwidth test")
        print("\nExamples:")
        print("  python network_test.py")
        print("  python network_test.py --traceroute")
        print("  python network_test.py -t -b")
        sys.exit(0)
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
