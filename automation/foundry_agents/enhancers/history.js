/**
 * HISTORICAL LEARNING
 * 過去のサイクル履歴から最適戦略を導出
 */

class HistoricalLearning {
  constructor(godState) {
    this.state = godState;
    this.history = [];
    this.maxHistory = 1000;
  }

  /**
   * Record cycle history
   */
  recordCycle(cycle) {
    const record = {
      cycleNumber: this.state.globalState.cycleNumber,
      timestamp: new Date().toISOString(),
      executionTime: cycle.executionTime,
      strategy: { ...this.state.executionStrategy },
      results: cycle.results,
      metrics: { ...this.state.globalState.metrics },
      agents: Object.entries(this.state.agentRegistry).map(([id, agent]) => ({
        id,
        performance: { ...agent.performance }
      }))
    };

    this.history.push(record);
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }

    return record;
  }

  /**
   * Analyze patterns in historical data
   */
  analyzePatterns() {
    if (this.history.length < 10) {
      return { patterns: [], confidence: 0 };
    }

    const patterns = {
      bestTimeOfDay: this.findBestTimeOfDay(),
      bestStrategyConfig: this.findBestStrategyConfig(),
      bottleneckPatterns: this.findBottleneckPatterns(),
      agentPerformanceTrends: this.findAgentTrends(),
      cycleDurationTrend: this.analyzeCycleDuration()
    };

    return patterns;
  }

  /**
   * Find best time of day for deployments
   */
  findBestTimeOfDay() {
    const hourSuccess = new Map();

    this.history.forEach(record => {
      const hour = new Date(record.timestamp).getHours();
      if (!hourSuccess.has(hour)) {
        hourSuccess.set(hour, { success: 0, total: 0 });
      }
      const stat = hourSuccess.get(hour);
      stat.total++;
      if (record.results.succeeded === record.results.total) {
        stat.success++;
      }
    });

    let bestHour = 0;
    let bestRate = 0;
    hourSuccess.forEach((stat, hour) => {
      const rate = stat.success / stat.total;
      if (rate > bestRate) {
        bestRate = rate;
        bestHour = hour;
      }
    });

    return { bestHour, successRate: bestRate };
  }

  /**
   * Find best execution strategy configuration
   */
  findBestStrategyConfig() {
    const strategyScores = new Map();

    this.history.forEach(record => {
      const key = JSON.stringify({
        mode: record.strategy.mode,
        maxParallelism: record.strategy.maxParallelism,
        caching: record.strategy.cachingStrategy
      });

      if (!strategyScores.has(key)) {
        strategyScores.set(key, { score: 0, count: 0 });
      }

      const stat = strategyScores.get(key);
      stat.count++;
      stat.score += (1 - (record.executionTime / 10000)) +
                   (record.metrics.improvementRate * 0.5);
    });

    let bestConfig = null;
    let bestScore = -Infinity;

    strategyScores.forEach((stat, configStr) => {
      const avgScore = stat.score / stat.count;
      if (avgScore > bestScore) {
        bestScore = avgScore;
        bestConfig = JSON.parse(configStr);
      }
    });

    return { config: bestConfig, score: bestScore };
  }

  /**
   * Find recurring bottleneck patterns
   */
  findBottleneckPatterns() {
    const agentBottlenecks = new Map();

    this.history.forEach(record => {
      record.agents.forEach(agent => {
        if (agent.performance.averageTime > 5000) {
          const key = agent.id;
          if (!agentBottlenecks.has(key)) {
            agentBottlenecks.set(key, 0);
          }
          agentBottlenecks.set(key, agentBottlenecks.get(key) + 1);
        }
      });
    });

    const patterns = Array.from(agentBottlenecks.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([agent, count]) => ({
        agent,
        occurrences: count,
        frequency: count / this.history.length
      }));

    return patterns;
  }

  /**
   * Analyze agent performance trends
   */
  findAgentTrends() {
    const agentTrends = new Map();

    this.state.agentRegistry && Object.keys(this.state.agentRegistry).forEach(agentId => {
      const times = this.history
        .flatMap(r => r.agents.filter(a => a.id === agentId))
        .map(a => a.performance.averageTime);

      if (times.length > 0) {
        const trend = {
          agent: agentId,
          current: times[times.length - 1],
          average: times.reduce((a, b) => a + b, 0) / times.length,
          trend: this.calculateTrend(times)
        };
        agentTrends.set(agentId, trend);
      }
    });

    return Array.from(agentTrends.values());
  }

  /**
   * Analyze cycle duration trend (improving/degrading)
   */
  analyzeCycleDuration() {
    if (this.history.length < 5) {
      return { trend: 'insufficient_data', averageTime: 0 };
    }

    const recent = this.history.slice(-20);
    const times = recent.map(r => r.executionTime);
    const average = times.reduce((a, b) => a + b, 0) / times.length;
    const trend = this.calculateTrend(times);

    return {
      averageTime: average,
      trend,
      improvement: trend === 'improving'
    };
  }

  /**
   * Calculate trend from time series (improving/stable/degrading)
   */
  calculateTrend(values) {
    if (values.length < 3) return 'insufficient_data';

    const first = values.slice(0, Math.floor(values.length / 2));
    const last = values.slice(Math.floor(values.length / 2));

    const firstAvg = first.reduce((a, b) => a + b, 0) / first.length;
    const lastAvg = last.reduce((a, b) => a + b, 0) / last.length;

    const improvement = (firstAvg - lastAvg) / firstAvg;

    if (improvement > 0.05) return 'improving';
    if (improvement < -0.05) return 'degrading';
    return 'stable';
  }

  /**
   * Select best strategy based on history
   */
  selectBestStrategy() {
    const patterns = this.analyzePatterns();

    if (!patterns.bestStrategyConfig || !patterns.bestStrategyConfig.config) {
      return this.state.executionStrategy;
    }

    return {
      ...this.state.executionStrategy,
      ...patterns.bestStrategyConfig.config
    };
  }

  /**
   * Get recommendations based on history
   */
  getRecommendations() {
    const patterns = this.analyzePatterns();
    const recommendations = [];

    // Recommend best time for deployments
    if (patterns.bestTimeOfDay.successRate > 0.9) {
      recommendations.push({
        type: 'SCHEDULE',
        action: `Schedule deployments around ${patterns.bestTimeOfDay.bestHour}:00 (${Math.round(patterns.bestTimeOfDay.successRate * 100)}% success rate)`
      });
    }

    // Recommend strategy optimization
    if (patterns.bestStrategyConfig.score > 0) {
      recommendations.push({
        type: 'STRATEGY',
        action: `Apply best-performing strategy config: ${JSON.stringify(patterns.bestStrategyConfig.config)}`
      });
    }

    // Recommend agent optimization
    patterns.bottleneckPatterns.forEach(pattern => {
      if (pattern.frequency > 0.5) {
        recommendations.push({
          type: 'AGENT_OPTIMIZATION',
          action: `${pattern.agent} is a bottleneck in ${Math.round(pattern.frequency * 100)}% of cycles — priority optimization needed`
        });
      }
    });

    // Recommend parallelism adjustment
    const cycleTrend = patterns.cycleDurationTrend;
    if (cycleTrend.trend === 'degrading') {
      recommendations.push({
        type: 'PARALLELISM',
        action: 'Cycle duration degrading — increase parallelism or investigate agent performance'
      });
    }

    return recommendations;
  }

  /**
   * Export history for analysis
   */
  export() {
    return {
      entries: this.history.length,
      samples: this.history,
      patterns: this.analyzePatterns(),
      recommendations: this.getRecommendations()
    };
  }
}

export default HistoricalLearning;
