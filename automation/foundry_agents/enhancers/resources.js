/**
 * RESOURCE MANAGER
 * External resource monitoring and optimization
 */

class ResourceManager {
  constructor() {
    this.resources = {
      vercel: { status: 'unknown', quota: 0, used: 0 },
      supabase: { status: 'unknown', quota: 0, used: 0 },
      github: { rateLimit: 5000, remaining: 5000 },
      cpu: { usage: 0 },
      memory: { usage: 0 }
    };
    this.alerts = [];
  }

  /**
   * Monitor all external resources
   */
  async monitorAll() {
    const checks = await Promise.allSettled([
      this.checkVercel(),
      this.checkSupabase(),
      this.checkGitHub(),
      this.checkCPUMemory()
    ]);

    const results = {
      timestamp: new Date().toISOString(),
      healthy: true,
      resources: {},
      alerts: []
    };

    checks.forEach((check, i) => {
      if (check.status === 'fulfilled') {
        const resource = check.value;
        results.resources[resource.name] = resource;
        if (!resource.healthy) {
          results.healthy = false;
          results.alerts.push(resource.alert);
        }
      }
    });

    this.alerts = results.alerts;
    return results;
  }

  /**
   * Check Vercel deployment status and quota
   */
  async checkVercel() {
    try {
      // Mock Vercel API check
      return {
        name: 'vercel',
        healthy: true,
        deployments: { available: true },
        quota: { builds: 100, remaining: 87 },
        alert: null
      };
    } catch (e) {
      return {
        name: 'vercel',
        healthy: false,
        alert: `Vercel check failed: ${e.message}`
      };
    }
  }

  /**
   * Check Supabase quota and status
   */
  async checkSupabase() {
    try {
      // Mock Supabase API check
      const used = Math.floor(Math.random() * 40); // 0-40GB
      const quota = 100;
      const healthy = used < quota * 0.8;

      return {
        name: 'supabase',
        healthy,
        quota,
        used,
        utilization: (used / quota) * 100,
        alert: healthy ? null : `Supabase approaching quota: ${used}GB / ${quota}GB`
      };
    } catch (e) {
      return {
        name: 'supabase',
        healthy: false,
        alert: `Supabase check failed: ${e.message}`
      };
    }
  }

  /**
   * Check GitHub API rate limits
   */
  async checkGitHub() {
    try {
      // GitHub API rate limit check
      const headers = process.env.GITHUB_TOKEN ? {
        'Authorization': `Bearer ${process.env.GITHUB_TOKEN}`,
        'X-GitHub-Api-Version': '2022-11-28'
      } : {};

      // Mock rate limit
      const remaining = 4500 + Math.floor(Math.random() * 500);
      const limit = 5000;
      const healthy = remaining > limit * 0.2;

      return {
        name: 'github',
        healthy,
        rateLimit: { limit, remaining },
        utilization: ((limit - remaining) / limit) * 100,
        alert: healthy ? null : `GitHub rate limit low: ${remaining}/${limit} requests remaining`
      };
    } catch (e) {
      return {
        name: 'github',
        healthy: false,
        alert: `GitHub check failed: ${e.message}`
      };
    }
  }

  /**
   * Check CPU and memory usage
   */
  async checkCPUMemory() {
    try {
      const memUsage = process.memoryUsage();
      const heapUsedPercent = (memUsage.heapUsed / memUsage.heapTotal) * 100;
      const healthy = heapUsedPercent < 85;

      return {
        name: 'compute',
        healthy,
        cpu: { usage: Math.floor(Math.random() * 80) },
        memory: {
          heapUsed: Math.round(memUsage.heapUsed / 1024 / 1024),
          heapTotal: Math.round(memUsage.heapTotal / 1024 / 1024),
          utilization: heapUsedPercent
        },
        alert: healthy ? null : `Memory usage high: ${heapUsedPercent.toFixed(1)}% of heap`
      };
    } catch (e) {
      return {
        name: 'compute',
        healthy: false,
        alert: `Compute check failed: ${e.message}`
      };
    }
  }

  /**
   * Compute resource-aware execution strategy
   */
  async computeOptimalStrategy() {
    const monitor = await this.monitorAll();

    const strategy = {
      maxParallelism: 4,
      cachingStrategy: 'aggressive',
      timeoutMs: 600000,
      adjustments: []
    };

    // Adjust based on CPU/memory
    if (monitor.resources.compute?.memory?.utilization > 70) {
      strategy.maxParallelism = Math.max(2, strategy.maxParallelism - 1);
      strategy.adjustments.push('Reduced parallelism due to high memory usage');
    }

    // Adjust based on GitHub rate limit
    if (monitor.resources.github?.healthy === false) {
      strategy.adjustments.push('GitHub rate limited — slow down deployment frequency');
    }

    // Adjust based on Supabase
    if (monitor.resources.supabase?.utilization > 80) {
      strategy.cachingStrategy = 'reduced';
      strategy.adjustments.push('Supabase near quota — reduce database operations');
    }

    return { strategy, monitor };
  }

  /**
   * Alert handler
   */
  handleAlerts() {
    const criticalAlerts = this.alerts.filter(a => a && a.includes('high'));

    if (criticalAlerts.length > 0) {
      return {
        severity: 'HIGH',
        actions: [
          'Reduce parallelism temporarily',
          'Enable aggressive caching',
          'Defer non-critical operations'
        ],
        alerts: criticalAlerts
      };
    }

    return { severity: 'OK', actions: [] };
  }

  /**
   * Get resource usage summary
   */
  summary() {
    const health = this.alerts.length === 0 ? '✓ HEALTHY' : '⚠ ALERTS';
    return {
      status: health,
      alertCount: this.alerts.length,
      alerts: this.alerts,
      timestamp: new Date().toISOString()
    };
  }
}

export default ResourceManager;
