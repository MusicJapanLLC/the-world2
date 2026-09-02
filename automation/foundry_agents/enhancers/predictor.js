/**
 * PREDICTIVE OPTIMIZATION
 * Forecast bottlenecks and proactively resolve them
 */

class PredictiveOptimization {
  constructor() {
    this.timeSeries = [];
    this.predictions = [];
    this.maxSamples = 100;
  }

  /**
   * Add metric sample to time series
   */
  addSample(agentId, metric) {
    this.timeSeries.push({
      timestamp: Date.now(),
      agentId,
      executionTime: metric.executionTime,
      queueLength: metric.queueLength || 0,
      errorRate: metric.errorRate || 0
    });

    if (this.timeSeries.length > this.maxSamples) {
      this.timeSeries.shift();
    }
  }

  /**
   * Predict next bottleneck using simple linear regression
   */
  predictNextBottleneck() {
    const predictions = [];

    // Group by agent
    const byAgent = new Map();
    this.timeSeries.forEach(sample => {
      if (!byAgent.has(sample.agentId)) {
        byAgent.set(sample.agentId, []);
      }
      byAgent.get(sample.agentId).push(sample);
    });

    // Predict for each agent
    byAgent.forEach((samples, agentId) => {
      if (samples.length < 3) return;

      const times = samples.map(s => s.executionTime);
      const trend = this.linearRegression(times);

      // If slope is positive and high, bottleneck incoming
      if (trend.slope > 100 && trend.r2 > 0.7) {
        const nextPredictedTime = trend.intercept + trend.slope * (times.length + 1);

        predictions.push({
          agentId,
          currentTime: times[times.length - 1],
          predictedTime: nextPredictedTime,
          confidence: trend.r2,
          severity: this.calculateSeverity(nextPredictedTime),
          recommendation: this.getRecommendation(agentId, nextPredictedTime)
        });
      }
    });

    return predictions.sort((a, b) => b.confidence - a.confidence);
  }

  /**
   * Linear regression to find trend
   */
  linearRegression(values) {
    const n = values.length;
    const x = Array.from({ length: n }, (_, i) => i);
    const y = values;

    const sumX = x.reduce((a, b) => a + b, 0);
    const sumY = y.reduce((a, b) => a + b, 0);
    const sumXY = x.reduce((sum, xi, i) => sum + xi * y[i], 0);
    const sumX2 = x.reduce((sum, xi) => sum + xi * xi, 0);

    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    // Calculate R-squared
    const yMean = sumY / n;
    const ssRes = y.reduce((sum, yi, i) => sum + Math.pow(yi - (intercept + slope * x[i]), 2), 0);
    const ssTot = y.reduce((sum, yi) => sum + Math.pow(yi - yMean, 2), 0);
    const r2 = 1 - (ssRes / ssTot);

    return { slope, intercept, r2 };
  }

  /**
   * Calculate severity of predicted bottleneck
   */
  calculateSeverity(predictedTime) {
    if (predictedTime > 30000) return 'CRITICAL';
    if (predictedTime > 15000) return 'HIGH';
    if (predictedTime > 5000) return 'MEDIUM';
    return 'LOW';
  }

  /**
   * Get proactive recommendation
   */
  getRecommendation(agentId, predictedTime) {
    if (predictedTime > 30000) {
      return `[URGENT] ${agentId} will bottle-neck — consider pre-optimizing or load-balancing`;
    }
    if (predictedTime > 15000) {
      return `${agentId} trending slow — prepare optimization strategy`;
    }
    return `Monitor ${agentId} for performance degradation`;
  }

  /**
   * Forecast cycles ahead for resource planning
   */
  forecastResourceNeeds(cycles = 5) {
    const predictions = this.predictNextBottleneck();

    const forecast = {
      cycles,
      predictions,
      recommendations: predictions
        .filter(p => p.severity === 'CRITICAL' || p.severity === 'HIGH')
        .map(p => ({
          action: 'PROACTIVE_OPTIMIZATION',
          target: p.agentId,
          reason: p.recommendation
        }))
    };

    return forecast;
  }

  /**
   * Get prediction accuracy metrics
   */
  getAccuracy() {
    if (this.predictions.length < 10) {
      return { accuracy: 0, samples: this.predictions.length };
    }

    const correct = this.predictions.filter(p => p.actual && Math.abs(p.actual - p.predicted) < p.predicted * 0.2).length;
    const accuracy = correct / this.predictions.length;

    return {
      accuracy: Math.round(accuracy * 100),
      samples: this.predictions.length,
      trend: accuracy > 0.7 ? 'improving' : 'needs_calibration'
    };
  }
}

export default PredictiveOptimization;
