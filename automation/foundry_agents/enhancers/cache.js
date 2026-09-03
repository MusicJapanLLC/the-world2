/**
 * SMART CACHING
 * Intelligent result caching based on reuse probability
 */

class SmartCaching {
  constructor() {
    this.cache = new Map();
    this.stats = new Map();
    this.maxCacheSize = 500; // entries
  }

  /**
   * Cache result with intelligent TTL based on reuse probability
   */
  async cacheResult(targetId, result, metadata = {}) {
    const reuseProbability = this.predictReuseProbability(targetId, metadata);

    let ttl;
    if (reuseProbability > 0.8) {
      ttl = 7 * 24 * 60 * 60 * 1000; // 1 week
    } else if (reuseProbability > 0.6) {
      ttl = 24 * 60 * 60 * 1000; // 1 day
    } else if (reuseProbability > 0.4) {
      ttl = 6 * 60 * 60 * 1000; // 6 hours
    } else {
      ttl = 60 * 60 * 1000; // 1 hour
    }

    const entry = {
      targetId,
      result,
      metadata,
      timestamp: Date.now(),
      expiresAt: Date.now() + ttl,
      ttl,
      reuseProbability,
      hits: 0
    };

    this.cache.set(targetId, entry);

    // Enforce size limit
    if (this.cache.size > this.maxCacheSize) {
      this.evictLRU();
    }

    return { cached: true, ttl, reuseProbability };
  }

  /**
   * Retrieve cached result if valid
   */
  getResult(targetId) {
    const entry = this.cache.get(targetId);

    if (!entry) {
      return { hit: false };
    }

    // Check expiration
    if (Date.now() > entry.expiresAt) {
      this.cache.delete(targetId);
      return { hit: false };
    }

    // Record hit
    entry.hits++;
    this.recordHit(targetId);

    return {
      hit: true,
      result: entry.result,
      metadata: entry.metadata,
      age: Date.now() - entry.timestamp,
      hitCount: entry.hits
    };
  }

  /**
   * Predict reuse probability for a target
   */
  predictReuseProbability(targetId, metadata = {}) {
    const stats = this.stats.get(targetId);

    if (!stats) {
      // Default estimate based on metadata
      if (metadata.category === 'stable') return 0.8;
      if (metadata.category === 'volatile') return 0.2;
      return 0.5; // neutral
    }

    // Calculate based on historical data
    const reuseRate = stats.hits / Math.max(stats.accesses, 1);
    const recency = (Date.now() - stats.lastAccess) / (24 * 60 * 60 * 1000);

    // Recency factor (more recent = higher prob)
    const recencyFactor = Math.max(0, 1 - recency / 7); // decay over 7 days

    return Math.min(1, reuseRate * 0.7 + recencyFactor * 0.3);
  }

  /**
   * Record cache hit
   */
  recordHit(targetId) {
    if (!this.stats.has(targetId)) {
      this.stats.set(targetId, { hits: 0, accesses: 0, lastAccess: Date.now() });
    }

    const stat = this.stats.get(targetId);
    stat.hits++;
    stat.accesses++;
    stat.lastAccess = Date.now();
  }

  /**
   * Evict least recently used entry
   */
  evictLRU() {
    let lru = null;
    let lruTime = Date.now();

    this.cache.forEach((entry, key) => {
      if (entry.timestamp < lruTime) {
        lruTime = entry.timestamp;
        lru = key;
      }
    });

    if (lru) {
      this.cache.delete(lru);
    }
  }

  /**
   * Get cache statistics
   */
  getStats() {
    let totalHits = 0;
    let totalAccesses = 0;

    this.stats.forEach(stat => {
      totalHits += stat.hits;
      totalAccesses += stat.accesses;
    });

    const hitRate = totalAccesses > 0 ? totalHits / totalAccesses : 0;

    return {
      cacheSize: this.cache.size,
      maxSize: this.maxCacheSize,
      utilization: (this.cache.size / this.maxCacheSize) * 100,
      totalHits,
      totalAccesses,
      hitRate: Math.round(hitRate * 100),
      trackedTargets: this.stats.size
    };
  }

  /**
   * Clear expired entries
   */
  purgeExpired() {
    let purged = 0;
    const now = Date.now();

    for (const [key, entry] of this.cache.entries()) {
      if (now > entry.expiresAt) {
        this.cache.delete(key);
        purged++;
      }
    }

    return purged;
  }

  /**
   * Clear entire cache
   */
  clear() {
    const size = this.cache.size;
    this.cache.clear();
    return { cleared: size };
  }

  /**
   * Get high-value entries (frequent reuse)
   */
  getHighValueEntries(limit = 10) {
    const entries = Array.from(this.cache.entries())
      .map(([key, entry]) => ({
        targetId: key,
        hits: entry.hits,
        reuseProbability: entry.reuseProbability,
        age: Date.now() - entry.timestamp
      }))
      .sort((a, b) => b.hits - a.hits)
      .slice(0, limit);

    return entries;
  }
}

export default SmartCaching;
