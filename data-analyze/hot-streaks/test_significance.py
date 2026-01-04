#!/usr/bin/env python3
"""
Statistical Significance Test
Tests if combination accuracies are due to genuine prediction or just chance/overfitting
"""

import sqlite3
import random
import numpy as np
from collections import Counter


def test_random_baseline(db_path: str = "./crasher_data.db"):
    """
    Test what accuracy a RANDOM predictor would achieve
    This tells us if our methods are actually predictive or just lucky
    """
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("="*100)
    print("STATISTICAL SIGNIFICANCE TEST")
    print("Testing if 68.9% accuracy is meaningful or just chance...")
    print("="*100)
    
    # Get all hot streak occurrences
    cursor.execute("""
        SELECT id, multiplier
        FROM multipliers
        ORDER BY id
    """)
    
    all_multipliers = [(row[0], row[1]) for row in cursor.fetchall()]
    
    print(f"\nTotal rounds: {len(all_multipliers):,}")
    
    # Detect hot streaks manually
    hot_streak_indices = []
    
    for i in range(len(all_multipliers) - 15):
        window = [m[1] for m in all_multipliers[i:i+15]]
        above_2x = sum(1 for m in window if m >= 2.0)
        if above_2x / 15 >= 0.65:
            hot_streak_indices.append(i)
    
    print(f"Hot streaks detected: {len(hot_streak_indices):,}")
    
    if len(hot_streak_indices) == 0:
        print("\n⚠️  No hot streaks detected! Cannot run test.")
        return
    
    # Calculate average gap between hot streaks
    gaps = []
    for i in range(1, len(hot_streak_indices)):
        gap = hot_streak_indices[i] - hot_streak_indices[i-1]
        gaps.append(gap)
    
    avg_gap = sum(gaps) / len(gaps) if gaps else 0
    median_gap = sorted(gaps)[len(gaps)//2] if gaps else 0
    
    print(f"\nHot Streak Statistics:")
    print(f"  Average gap: {avg_gap:.1f} rounds")
    print(f"  Median gap: {median_gap:.0f} rounds")
    print(f"  Min gap: {min(gaps) if gaps else 0} rounds")
    print(f"  Max gap: {max(gaps) if gaps else 0} rounds")
    
    print(f"\n{'='*100}")
    print("TEST 1: RANDOM PREDICTOR BASELINE")
    print("="*100)
    
    # Test different random prediction strategies
    strategies = [
        ("Always predict 10 rounds", lambda: 10),
        ("Always predict 15 rounds", lambda: 15),
        ("Random 5-15 rounds", lambda: random.randint(5, 15)),
        ("Random 0-20 rounds", lambda: random.randint(0, 20)),
        ("Average gap prediction", lambda: int(avg_gap)),
    ]
    
    print(f"\n{'Strategy':<30} {'Accuracy':<12} {'vs Our 68.9%'}")
    print("-"*70)
    
    for strategy_name, predict_func in strategies:
        # Simulate predictions
        correct = 0
        total = 0
        
        for i in range(len(hot_streak_indices) - 1):
            current_idx = hot_streak_indices[i]
            next_idx = hot_streak_indices[i + 1]
            actual_gap = next_idx - current_idx
            
            predicted_gap = predict_func()
            
            # Check if within ±10 rounds
            if abs(predicted_gap - actual_gap) <= 10:
                correct += 1
            total += 1
        
        accuracy = (correct / total * 100) if total > 0 else 0
        diff = accuracy - 68.9
        
        print(f"{strategy_name:<30} {accuracy:>9.1f}% {diff:>+9.1f}%")
    
    print(f"\n{'='*100}")
    print("TEST 2: MARGIN OF ERROR IMPACT")
    print("="*100)
    print("\nWhat if we used different margins instead of ±10?")
    
    # Test with "always predict average" but different margins
    margins = [0, 5, 10, 15, 20, 30]
    
    print(f"\n{'Margin':<15} {'Accuracy':<12} {'Window Size':<15} {'Comment'}")
    print("-"*80)
    
    for margin in margins:
        correct = 0
        total = 0
        
        for i in range(len(hot_streak_indices) - 1):
            current_idx = hot_streak_indices[i]
            next_idx = hot_streak_indices[i + 1]
            actual_gap = next_idx - current_idx
            
            predicted_gap = int(avg_gap)
            
            if abs(predicted_gap - actual_gap) <= margin:
                correct += 1
            total += 1
        
        accuracy = (correct / total * 100) if total > 0 else 0
        window = margin * 2
        
        if margin == 10:
            comment = "← OUR CURRENT MARGIN"
        elif accuracy > 68.9:
            comment = "Better than our methods!"
        elif accuracy > 50:
            comment = "Still decent"
        else:
            comment = "Poor"
        
        print(f"±{margin:2} rounds    {accuracy:>9.1f}% {window:>13} rounds {comment}")
    
    print(f"\n{'='*100}")
    print("TEST 3: METHOD SELECTIVITY")
    print("="*100)
    
    # Check how often each method triggers
    cursor.execute("""
        SELECT method_id, COUNT(DISTINCT multiplier_id) as count
        FROM signals
        GROUP BY method_id
        ORDER BY method_id
    """)
    
    total_rounds = len(all_multipliers)
    
    print(f"\n{'Method':<10} {'Triggers':<15} {'% of Rounds':<15} {'Selectivity'}")
    print("-"*80)
    
    for method_id, count in cursor.fetchall():
        pct = (count / total_rounds * 100) if total_rounds > 0 else 0
        
        if pct > 90:
            selectivity = "❌ Too broad (>90%)"
        elif pct > 70:
            selectivity = "⚠️  Broad (70-90%)"
        elif pct > 50:
            selectivity = "⚡ Moderate (50-70%)"
        elif pct > 30:
            selectivity = "✅ Selective (30-50%)"
        else:
            selectivity = "✅ Very selective (<30%)"
        
        print(f"M{method_id:<9} {count:>13,} {pct:>13.1f}% {selectivity}")
    
    print(f"\n{'='*100}")
    print("TEST 4: PREDICTIVE POWER VS RANDOM")
    print("="*100)
    
    # Compare our best combo to random predictions at same frequency
    print(f"\nM3+M6+M7+M10 triggers on 91.8% of rounds")
    print(f"Let's test a random predictor that ALSO triggers 91.8% of the time...")
    
    # Simulate: randomly select 91.8% of rounds and predict "15 rounds"
    num_predictions = int(total_rounds * 0.918)
    random_prediction_rounds = random.sample(range(len(hot_streak_indices) - 1), 
                                             min(num_predictions, len(hot_streak_indices) - 1))
    
    correct = 0
    for i in random_prediction_rounds:
        current_idx = hot_streak_indices[i]
        next_idx = hot_streak_indices[i + 1]
        actual_gap = next_idx - current_idx
        
        predicted_gap = 15  # Random guess
        
        if abs(predicted_gap - actual_gap) <= 10:
            correct += 1
    
    random_accuracy = (correct / len(random_prediction_rounds) * 100) if random_prediction_rounds else 0
    
    print(f"\nRandom predictor (91.8% frequency, predict 15r, ±10 margin):")
    print(f"  Accuracy: {random_accuracy:.1f}%")
    print(f"  Our M3+M6+M7+M10: 68.9%")
    print(f"  Improvement: {68.9 - random_accuracy:+.1f}%")
    
    if 68.9 - random_accuracy < 5:
        print(f"\n❌ CONCERNING: Only {68.9 - random_accuracy:.1f}% better than random!")
        print(f"   Our methods might not be genuinely predictive.")
    elif 68.9 - random_accuracy < 10:
        print(f"\n⚠️  MARGINAL: Only {68.9 - random_accuracy:.1f}% better than random.")
        print(f"   Some predictive power but not strong.")
    else:
        print(f"\n✅ SIGNIFICANT: {68.9 - random_accuracy:.1f}% better than random.")
        print(f"   Methods show genuine predictive power!")
    
    print(f"\n{'='*100}")
    print("VERDICT")
    print("="*100)
    
    # Calculate if improvement is statistically significant
    # Using simple binomial test approximation
    n = 44286  # number of tests
    p_random = random_accuracy / 100
    p_observed = 0.689
    
    # Standard error
    se = np.sqrt(p_random * (1 - p_random) / n)
    z_score = (p_observed - p_random) / se
    
    print(f"\nStatistical Analysis:")
    print(f"  Sample size: {n:,} predictions")
    print(f"  Random baseline: {random_accuracy:.1f}%")
    print(f"  Our accuracy: {p_observed*100:.1f}%")
    print(f"  Z-score: {z_score:.2f}")
    
    if z_score > 2.58:
        significance = "✅ HIGHLY SIGNIFICANT (p < 0.01)"
        verdict = "Your methods ARE genuinely predictive!"
    elif z_score > 1.96:
        significance = "✅ SIGNIFICANT (p < 0.05)"
        verdict = "Your methods show real predictive power."
    elif z_score > 1.64:
        significance = "⚠️  MARGINALLY SIGNIFICANT (p < 0.10)"
        verdict = "Methods might have some predictive value."
    else:
        significance = "❌ NOT SIGNIFICANT"
        verdict = "Could be due to chance/overfitting."
    
    print(f"  Significance: {significance}")
    print(f"\nVERDICT: {verdict}")
    
    # Recommendations
    print(f"\n{'='*100}")
    print("RECOMMENDATIONS")
    print("="*100)
    
    print(f"\n1. METHOD STRICTNESS:")
    print(f"   - Methods triggering >90% of the time are TOO BROAD")
    print(f"   - Consider adding stricter criteria")
    print(f"   - Target: 30-50% trigger rate for meaningful signals")
    
    print(f"\n2. MARGIN OF ERROR:")
    print(f"   - ±10 rounds is very generous")
    print(f"   - With avg gap of {avg_gap:.1f} rounds, ±10 covers {20/avg_gap*100:.0f}% of cycle")
    print(f"   - Try ±5 rounds for stricter test")
    
    print(f"\n3. VALIDATION:")
    print(f"   - Split data: train on 70%, test on 30%")
    print(f"   - Check if accuracy holds on unseen data")
    print(f"   - This reveals true overfitting")
    
    print(f"\n4. LIVE TESTING:")
    print(f"   - Most important: test on NEW data")
    print(f"   - Track next 100 predictions live")
    print(f"   - Compare to these historical results")
    
    conn.close()
    
    print(f"\n{'='*100}")
    print("✅ Analysis complete")
    print("="*100)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test statistical significance')
    parser.add_argument('--db', default='./crasher_data.db', help='Database path')
    args = parser.parse_args()
    
    try:
        test_random_baseline(args.db)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
