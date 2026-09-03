/**
 * EXECUTOR
 * Parallel DAG execution engine with optimization
 */

class ExecutionDAG {
  constructor(targets) {
    this.targets = targets;
    this.graph = new Map();
    this.inDegree = new Map();
    this.buildGraph();
  }

  buildGraph() {
    // Initialize nodes
    this.targets.forEach(t => {
      this.graph.set(t.id, {
        target: t,
        deps: [],
        dependents: []
      });
      this.inDegree.set(t.id, 0);
    });

    // Build edges
    this.targets.forEach(t => {
      (t.dependsOn || []).forEach(depId => {
        if (this.graph.has(depId)) {
          this.graph.get(depId).dependents.push(t.id);
          this.graph.get(t.id).deps.push(depId);
          this.inDegree.set(t.id, (this.inDegree.get(t.id) || 0) + 1);
        }
      });
    });
  }

  /**
   * Topological sort returning layers (nodes that can execute in parallel)
   */
  computeLayers() {
    const inDegree = new Map(this.inDegree);
    const layers = [];

    while (true) {
      // Find all nodes with no dependencies
      const ready = Array.from(this.graph.keys()).filter(
        id => inDegree.get(id) === 0 && !layers.flat().includes(id)
      );

      if (ready.length === 0) break;

      layers.push(ready);

      // Decrement in-degree of dependents
      ready.forEach(id => {
        this.graph.get(id).dependents.forEach(depId => {
          inDegree.set(depId, inDegree.get(depId) - 1);
        });
      });
    }

    return layers;
  }

  /**
   * Calculate critical path (longest dependency chain)
   */
  criticalPath() {
    const depth = new Map();

    const calcDepth = (id, visited = new Set()) => {
      if (visited.has(id)) return 0;
      if (depth.has(id)) return depth.get(id);

      visited.add(id);
      const node = this.graph.get(id);
      const maxDepDeps = node.deps.length > 0
        ? Math.max(...node.deps.map(d => calcDepth(d, new Set(visited))))
        : 0;

      const d = 1 + maxDepDeps;
      depth.set(id, d);
      return d;
    };

    Array.from(this.graph.keys()).forEach(id => calcDepth(id));
    return Math.max(...Array.from(depth.values()));
  }

  /**
   * Find bottleneck targets (dependencies with high downstream impact)
   */
  bottlenecks() {
    const impact = new Map();

    this.graph.forEach((node, id) => {
      impact.set(id, node.dependents.length);
    });

    return Array.from(impact.entries())
      .filter(([_, count]) => count > 1)
      .sort((a, b) => b[1] - a[1])
      .map(([id]) => id);
  }

  /**
   * Estimate total execution time (critical path × estimate per node)
   */
  estimatedTime(timePerNode = 5000) {
    return this.criticalPath() * timePerNode;
  }

  /**
   * Get execution recommendations
   */
  recommendations() {
    const path = this.criticalPath();
    const bottleneck = this.bottlenecks()[0];
    const layers = this.computeLayers();

    return {
      criticalPathLength: path,
      estimatedTime: this.estimatedTime(),
      bottleneckTarget: bottleneck,
      maxParallelism: Math.max(...layers.map(l => l.length)),
      parallizableLayers: layers.length,
      recommendations: [
        path > 5 ? 'Critical path is long — consider breaking targets into smaller tasks' : null,
        bottleneck ? `Focus optimization on "${bottleneck}" (blocks ${this.graph.get(bottleneck).dependents.length} targets)` : null,
        Math.max(...layers.map(l => l.length)) === 1 ? 'Targets are highly sequential — limited parallelism opportunity' : null,
      ].filter(Boolean)
    };
  }
}

/**
 * Parallel executor with queue management
 */
class ParallelExecutor {
  constructor(maxConcurrency = 4) {
    this.maxConcurrency = maxConcurrency;
    this.running = new Map();
    this.completed = new Set();
    this.failed = new Map();
  }

  async executeDAG(dag, executeTargetFn) {
    const layers = dag.computeLayers();
    const results = [];

    console.log(`[Executor] Executing ${dag.targets.length} targets across ${layers.length} layers`);
    console.log(`[Executor] Max parallelism: ${Math.max(...layers.map(l => l.length))}`);

    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i];
      console.log(`\n[Layer ${i + 1}] ${layer.length} targets`);

      const layerResults = await Promise.allSettled(
        layer.map(targetId => this.executeWithTimeout(targetId, executeTargetFn, 600000))
      );

      layerResults.forEach((result, idx) => {
        const targetId = layer[idx];
        if (result.status === 'fulfilled') {
          this.completed.add(targetId);
          console.log(`  ✓ ${targetId}`);
          results.push({ targetId, status: 'success', result: result.value });
        } else {
          this.failed.set(targetId, result.reason);
          console.log(`  ✗ ${targetId} — ${result.reason?.message || 'unknown error'}`);
          results.push({ targetId, status: 'failed', error: result.reason?.message });
        }
      });
    }

    return {
      total: dag.targets.length,
      succeeded: this.completed.size,
      failed: this.failed.size,
      results
    };
  }

  async executeWithTimeout(targetId, executeFn, timeoutMs) {
    return Promise.race([
      executeFn(targetId),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`Timeout after ${timeoutMs}ms`)), timeoutMs)
      )
    ]);
  }

  getStats() {
    return {
      completed: this.completed.size,
      failed: this.failed.size,
      failedTargets: Array.from(this.failed.keys())
    };
  }
}

export { ExecutionDAG, ParallelExecutor };
