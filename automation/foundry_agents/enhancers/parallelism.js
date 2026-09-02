/**
 * DYNAMIC PARALLELISM
 * Real-time parallelism adjustment based on resources
 */

class DynamicParallelism {
  constructor(initialMax = 4) {
    this.maxParallelism = initialMax;
    this.minParallelism = 1;
    this.currentUtilization = 0;
    this.history = [];
  }

  /**
   * Dynamically adjust parallelism based on current load
   */
  async adjustParallelism(cpuUsage, memUsage, throughput) {
    const before = this.maxParallelism;

    // Calculate ideal parallelism
    const ideal = this.calculateIdealParallelism(cpuUsage, memUsage, throughput);

    // Smooth adjustment (don't jump too much)
    const adjustment = Math.max(
      this.minParallelism,
      Math.min(ideal, 8) // cap at 8
    );

    // Apply with damping factor
    const damping = 0.3; // Conservative adjustment
    this.maxParallelism = Math.round(
      this.maxParallelism * (1 - damping) + adjustment * damping
    );

    // Record history
    this.history.push({
      timestamp: Date.now(),
      before,
      after: this.maxParallelism,
      cpuUsage,
      memUsage,
      throughput
    });

    // Keep only recent history
    if (this.history.length > 100) {
      this.history.shift();
    }

    return {
      changed: before !== this.maxParallelism,
      before,
      after: this.maxParallelism,
      reason: this.getReason(cpuUsage, memUsage, throughput)
    };
  }

  /**
   * Calculate ideal parallelism based on resource metrics
   */
  calculateIdealParallelism(cpuUsage, memUsage, throughput) {
    let ideal = 4; // baseline

    // CPU-based adjustment
    if (cpuUsage > 80) {
      ideal = Math.max(1, ideal - 2);
    } else if (cpuUsage > 60) {
      ideal = Math.max(1, ideal - 1);
    } else if (cpuUsage < 30) {
      ideal = Math.min(8, ideal + 1);
    }

    // Memory-based adjustment
    if (memUsage > 85) {
      ideal = Math.max(1, ideal - 2);
    } else if (memUsage > 70) {
      ideal = Math.max(1, ideal - 1);
    } else if (memUsage < 40) {
      ideal = Math.min(8, ideal + 1);
    }

    // Throughput-based adjustment
    if (throughput < 2) { // slow throughput
      ideal = Math.max(1, ideal - 1);
    } else if (throughput > 10) { // high throughput
      ideal = Math.min(8, ideal + 1);
    }

    return ideal;
  }

  /**
   * Get reason for adjustment
   */
  getReason(cpu, mem, throughput) {
    const reasons = [];

    if (cpu > 80) reasons.push('High CPU usage');
    if (mem > 85) reasons.push('High memory usage');
    if (throughput < 2) reasons.push('Low throughput');
    if (throughput > 10) reasons.push('High throughput');

    return reasons.length > 0 ? reasons.join(', ') : 'Optimal utilization';
  }

  /**
   * Get current effective parallelism (considering throttling)
   */
  getEffectiveParallelism() {
    return Math.round(this.maxParallelism);
  }

  /**
   * Get adjustment history
   */
  getHistory(limit = 20) {
    return this.history.slice(-limit);
  }

  /**
   * Analyze parallelism efficiency
   */
  analyzeEfficiency() {
    if (this.history.length < 5) {
      return { efficiency: 0, trend: 'insufficient_data' };
    }

    const recent = this.history.slice(-20);
    const efficiencies = recent.map(entry => {
      const utilizationScore = (100 - entry.cpuUsage) / 100;
      const memoryScore = (100 - entry.memUsage) / 100;
      const throughputScore = Math.min(entry.throughput / 15, 1);
      return (utilizationScore + memoryScore + throughputScore) / 3;
    });

    const avgEfficiency = efficiencies.reduce((a, b) => a + b, 0) / efficiencies.length;
    const trend = efficiencies[efficiencies.length - 1] > efficiencies[0]
      ? 'improving'
      : 'degrading';

    return {
      efficiency: Math.round(avgEfficiency * 100),
      trend,
      currentParallelism: this.getEffectiveParallelism(),
      recommendation: this.getRecommendation(avgEfficiency, trend)
    };
  }

  /**
   * Get optimization recommendation
   */
  getRecommendation(efficiency, trend) {
    if (efficiency > 0.85 && trend === 'improving') {
      return 'System performing optimally — no changes needed';
    }
    if (efficiency < 0.6) {
      return 'Consider reducing parallelism or investigating bottlenecks';
    }
    if (trend === 'degrading') {
      return 'Performance degrading — investigate resource leaks';
    }
    return 'Monitor and adjust if needed';
  }
}

export default DynamicParallelism;
