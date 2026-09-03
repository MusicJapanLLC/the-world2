// automation/foundry_agents/knowledge-bridge.js
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KNOWLEDGE_PATH = path.join(__dirname, '../../automation/shared_knowledge.json');

export default class KnowledgeBridge {
  constructor() {
    this.db = this._load();
  }

  _load() {
    try {
      return JSON.parse(fs.readFileSync(KNOWLEDGE_PATH, 'utf8'));
    } catch {
      return {
        repositories: { 'the-world2': { discoveries: [] } },
        unified_targets: { metrics: { shared_discoveries: 0 } }
      };
    }
  }

  _save() {
    fs.writeFileSync(KNOWLEDGE_PATH, JSON.stringify(this.db, null, 2));
  }

  // サイクル開始時: 高成功率パターンを取得してGODの戦略選択に使う
  getApplicablePatterns(minSuccessRate = 0.7) {
    const discoveries = this.db.repositories?.['the-world2']?.discoveries || [];
    return discoveries
      .filter(d => d.effectiveness?.success_rate >= minSuccessRate)
      .sort((a, b) => (b.effectiveness?.success_rate || 0) - (a.effectiveness?.success_rate || 0))
      .slice(0, 5);
  }

  // 最も成功率の高い戦略名を返す（なければ null）
  getBestStrategy() {
    const patterns = this.getApplicablePatterns(0.8);
    const strategyPattern = patterns.find(p => p.content?.strategy);
    return strategyPattern?.content?.strategy || null;
  }

  // サイクル終了後: 結果を知識DBに記録
  recordCycleLearning({ cycleNumber, reward, strategy, executionTimeMs, pendingTargets, implementedTargets, topTarget }) {
    if (!this.db.repositories['the-world2']) {
      this.db.repositories['the-world2'] = { discoveries: [] };
    }
    const discoveries = this.db.repositories['the-world2'].discoveries;

    const fingerprint = `god_cycle_${strategy}_${Math.round(reward * 100)}`;
    const existing = discoveries.findIndex(d => d.fingerprint === fingerprint);

    const entry = {
      knowledge_id: `kn_${crypto.randomBytes(4).toString('hex')}`,
      fingerprint,
      category: reward >= 0.8 ? 'capability' : reward >= 0.6 ? 'research_finding' : 'failure_pattern',
      source_repos: ['the-world2'],
      recorded_at: new Date().toISOString(),
      content: {
        title: `GOD Cycle ${cycleNumber}: ${strategy} strategy (reward ${reward.toFixed(2)})`,
        description: `Cycle ${cycleNumber} completed in ${executionTimeMs}ms using ${strategy} strategy`,
        strategy,
        top_target: topTarget || 'none',
      },
      effectiveness: {
        success_rate: reward,
        test_count: 1,
        last_verified: new Date().toISOString(),
      },
      meta: {
        pending_targets: pendingTargets,
        implemented_targets: implementedTargets,
        execution_time_ms: executionTimeMs,
      },
    };

    if (existing >= 0) {
      // 既存パターン: 成功率を移動平均で更新
      const prev = discoveries[existing];
      const n = (prev.effectiveness.test_count || 1);
      prev.effectiveness.success_rate = (prev.effectiveness.success_rate * n + reward) / (n + 1);
      prev.effectiveness.test_count = n + 1;
      prev.effectiveness.last_verified = new Date().toISOString();
      prev.content.title = entry.content.title;
    } else {
      discoveries.push(entry);
    }

    // メトリクス更新
    if (!this.db.unified_targets) this.db.unified_targets = { metrics: {} };
    if (!this.db.unified_targets.metrics) this.db.unified_targets.metrics = {};
    this.db.unified_targets.metrics.shared_discoveries = discoveries.length;
    this.db.unified_targets.metrics.agent_cooperation_level = Math.min(100, discoveries.length * 5);
    this.db.unified_targets.status = 'stage-2-active';

    this._save();
    return entry;
  }

  // 知識DBサマリーをログ出力
  logSummary() {
    const discoveries = this.db.repositories?.['the-world2']?.discoveries || [];
    const avgSuccess = discoveries.length > 0
      ? (discoveries.reduce((s, d) => s + (d.effectiveness?.success_rate || 0), 0) / discoveries.length).toFixed(2)
      : 'N/A';
    console.log(`[KNOWLEDGE] 📚 DB: ${discoveries.length} entries | avg success: ${avgSuccess} | cooperation: ${this.db.unified_targets?.metrics?.agent_cooperation_level || 0}%`);
    const best = this.getBestStrategy();
    if (best) console.log(`[KNOWLEDGE] 🏆 Best strategy: ${best}`);
  }
}
