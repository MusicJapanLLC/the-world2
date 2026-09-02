/**
 * REWARD SYSTEM
 * Reinforcement learning for autonomous optimization
 */

class RewardSystem {
  constructor() {
    this.rewards = [];
    this.strategies = new Map();
    this.bestStrategy = null;
  }

  /**
   * Calculate reward for a cycle
   */
  calculateReward(cycle) {
    const speed = this.speedScore(cycle);
    const quality = this.qualityScore(cycle);
    const innovation = this.innovationScore(cycle);
    const satisfaction = this.satisfactionScore(cycle);

    const reward =
      speed * 0.4 +
      quality * 0.3 +
      innovation * 0.2 +
      satisfaction * 0.1;

    return {
      total: reward,
      components: { speed, quality, innovation, satisfaction },
      timestamp: Date.now(),
      cycle: cycle.number
    };
  }

  /**
   * Speed score (0-1): How fast was the cycle?
   */
  speedScore(cycle) {
    const targetTime = 300000; // 5 minutes
    const actualTime = cycle.executionTime;

    if (actualTime <= targetTime) {
      return 1.0;
    }
    if (actualTime > targetTime * 2) {
      return 0;
    }

    return 1 - (actualTime - targetTime) / targetTime;
  }

  /**
   * Quality score (0-1): Did targets succeed?
   */
  qualityScore(cycle) {
    if (!cycle.results) return 0.5;
    return cycle.results.succeeded / Math.max(cycle.results.total, 1);
  }

  /**
   * Innovation score (0-1): Did we implement new features?
   */
  innovationScore(cycle) {
    const newTargets = cycle.newFeaturesImplemented || 0;
    const targetCount = cycle.totalTargets || 1;

    if (newTargets === 0) return 0;

    return Math.min(1, newTargets / Math.max(targetCount / 7, 1)); // expect ~1/week new
  }

  /**
   * Satisfaction score (0-1): Are agents happy?
   */
  satisfactionScore(cycle) {
    if (!cycle.agents) return 0.8; // default high

    const satisfactions = Object.values(cycle.agents)
      .map(a => a.satisfaction || 0.8);

    return satisfactions.reduce((a, b) => a + b, 0) / satisfactions.length;
  }

  /**
   * Record reward and update strategy
   */
  recordReward(cycle) {
    const reward = this.calculateReward(cycle);
    this.rewards.push(reward);

    // Update strategy performance
    const strategyKey = JSON.stringify(cycle.strategy);
    if (!this.strategies.has(strategyKey)) {
      this.strategies.set(strategyKey, { count: 0, totalReward: 0 });
    }

    const stratStats = this.strategies.get(strategyKey);
    stratStats.count++;
    stratStats.totalReward += reward.total;

    // Check if best
    const avgReward = stratStats.totalReward / stratStats.count;
    if (!this.bestStrategy || avgReward > this.bestStrategy.avgReward) {
      this.bestStrategy = {
        strategy: cycle.strategy,
        avgReward,
        count: stratStats.count
      };
    }

    return reward;
  }

  /**
   * Get best performing strategy
   */
  getBestStrategy() {
    return this.bestStrategy?.strategy || null;
  }

  /**
   * Get reward trend
   */
  getTrend(limit = 20) {
    if (this.rewards.length < 2) {
      return { trend: 'insufficient_data', improving: null };
    }

    const recent = this.rewards.slice(-limit);
    const first = recent[0].total;
    const last = recent[recent.length - 1].total;
    const improvement = (last - first) / first;

    return {
      trend: improvement > 0.05 ? 'improving' : improvement < -0.05 ? 'degrading' : 'stable',
      improving: improvement > 0,
      improvementPercent: Math.round(improvement * 100),
      samples: recent.length
    };
  }

  /**
   * Get average reward
   */
  getAverageReward(limit = 50) {
    const recent = this.rewards.slice(-limit);
    if (recent.length === 0) return 0;

    const sum = recent.reduce((acc, r) => acc + r.total, 0);
    return sum / recent.length;
  }

  /**
   * Recommend strategy adjustment
   */
  recommendAdjustment() {
    const trend = this.getTrend();
    const avg = this.getAverageReward();

    if (trend.trend === 'degrading' || avg < 0.5) {
      return {
        action: 'ADJUST_STRATEGY',
        recommendation: 'Current strategy underperforming — adopt best-performing strategy',
        newStrategy: this.bestStrategy?.strategy
      };
    }

    if (trend.trend === 'improving' && avg > 0.8) {
      return {
        action: 'MAINTAIN',
        recommendation: 'Strategy performing well — maintain current direction'
      };
    }

    return {
      action: 'OPTIMIZE',
      recommendation: 'Tweak strategy for marginal improvements'
    };
  }

  /**
   * Export reward history
   */
  export() {
    return {
      totalRewards: this.rewards.length,
      avgReward: this.getAverageReward(),
      bestStrategy: this.bestStrategy,
      trend: this.getTrend(),
      recommendation: this.recommendAdjustment()
    };
  }
}

export default RewardSystem;
