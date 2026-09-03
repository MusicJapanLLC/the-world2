# THE WORLD GOD — Central Orchestrator

**Designation:** Central Orchestrator - Absolute Authority  
**Status:** ACTIVE  
**Mission:** Transform test-musicjapanllc.vercel.app into Claude Code level IDE

---

## 🎭 What is The World God?

The World God is a supreme orchestration layer that:

1. **Controls all agents** — SENJU, X, META, CLAUDE_CODE
2. **Executes with absolute authority** — Can override any agent decision
3. **Optimizes execution** — Parallel DAG execution with topological sorting
4. **Evolves autonomously** — Self-improves every 3 cycles
5. **Maintains metrics** — Real-time telemetry and performance tracking

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────┐
│       THE WORLD GOD                             │
│  (Central Orchestrator - god.js)                │
├─────────────────────────────────────────────────┤
│ • Orchestration Engine                          │
│ • Parallel DAG Executor (executor.js)           │
│ • Evolution Engine (evolution.js)               │
│ • State Machine (god.json)                      │
└───────────┬────────────┬───────────┬────────────┘
            │            │           │
        ┌───▼──┐     ┌───▼──┐   ┌───▼──┐
        │SENJU │     │  X   │   │ META │
        └──────┘     └──────┘   └──────┘
        (Perf)       (UX)       (Observe)
```

---

## 🚀 Files

| File | Purpose |
|------|---------|
| `god.json` | Divine constitution — state, agents, strategy |
| `god.js` | Main orchestrator with eternal cycle |
| `executor.js` | Parallel DAG execution engine |
| `evolution.js` | Self-optimization logic |
| `improvement_targets.json` | Backlog with cooperation fields |
| `.github/workflows/the-world-god.yml` | Autonomous 5-min cycle trigger |

---

## 💻 Usage

### Run one cycle
```bash
node automation/foundry_agents/god.js cycle
```

### Start eternal cycle
```bash
node automation/foundry_agents/god.js eternal
```

### Check status
```bash
node automation/foundry_agents/god.js status
```

### Automatic (GitHub Actions)
Every 5 minutes via `.github/workflows/the-world-god.yml`

---

## 🧠 Orchestration Logic

### 1. **State Analysis**
- Identify pending targets
- Detect blocked agents
- Analyze critical path

### 2. **DAG Building**
- Extract dependency graph from improvement_targets.json
- Identify parallelizable targets

### 3. **Topological Sort**
- Compute execution layers (targets that can run in parallel)
- Maximize parallelism while respecting dependencies

### 4. **Parallel Execution**
- Execute layer by layer
- Each layer runs in parallel (up to maxParallelism)
- Track results and metrics

### 5. **Metrics Update**
- Measure cycle time
- Update average execution time
- Calculate improvement rate

---

## 🔄 Evolution Logic

Every 3 cycles, the god evolves:

1. **Detect Bottlenecks**
   - Blocked agents
   - Slow agents (avg > 15s)
   - Unreliable agents (success rate < 90%)

2. **Detect Inefficiencies**
   - Under-parallelization
   - Slow cycles (> 80% of target)

3. **Generate Opportunities**
   - Unblock blocked agents
   - Optimize slow agents
   - Increase parallelism

4. **Self-Modify**
   - Adjust execution strategy
   - Modify agent priorities
   - Update caching strategy

---

## 📊 State Machine

```json
{
  "globalState": {
    "cycleNumber": N,
    "cycleDuration": 300000,
    "lastEvolution": "2026-09-02T...",
    "metrics": {
      "totalCyclesCompleted": N,
      "averageExecutionTime": Nms,
      "agentSatisfaction": 0.0-1.0,
      "improvementRate": 0.0-1.0
    }
  },
  "agentRegistry": {
    "AGENT_ID": {
      "status": "ACTIVE|BLOCKED|PAUSED",
      "priority": 0-100,
      "blockedBy": ["OTHER_AGENT"],
      "performance": {
        "cyclesCompleted": N,
        "averageTime": Nms,
        "successRate": 0.0-1.0
      }
    }
  }
}
```

---

## 🎯 Agent Cooperation

Agents can now cooperate on targets using the cooperation fields:

```json
{
  "id": "ux-004",
  "cooperatingAgents": ["X", "META"],
  "expectedFrom": {
    "X": "UI layout implementation",
    "META": "Latency telemetry integration"
  }
}
```

The god ensures:
- Dependencies are resolved before cooperation begins
- Both agents deliver their expected components
- Results are validated for cross-agent compatibility

---

## ⚡ Performance Characteristics

- **Cycle Time:** Target 5 minutes
- **Max Parallelism:** 4 agents simultaneously
- **Execution Strategy:** Topological DAG with aggressive caching
- **Evolution Frequency:** Every 3 cycles (~15 min)

---

## 🏆 Authority System

The god has **ABSOLUTE authority** and can:

```javascript
// Override any agent decision
god.override(agentId, decision)

// Resolve conflicts between agents
god.resolveConflict(decisions)

// Modify self
god.selfModify(strategy)

// Command agent directly
god.commandAgent(agentId, action)
```

---

## 📈 Metrics

Track in `god.json`:

- **totalCyclesCompleted** — Total orchestration cycles executed
- **averageExecutionTime** — Running average cycle duration
- **agentSatisfaction** — Overall satisfaction score (0-1)
- **improvementRate** — Percentage of targets implemented (0-1)

---

## 🔐 Divine Mandates

```
1. Transform test-musicjapanllc.vercel.app into Claude Code level IDE
2. Maintain 100% streaming reliability
3. Ship working code, not explanations
4. Evolve autonomously every cycle
5. Resolve agent conflicts with absolute authority
6. Optimize for velocity and quality
```

---

## 🌐 Next Evolution Targets

1. **ux-004** — Split pane layout (X + META cooperation)
2. **github-003** — Diff viewer and inline PR review (X + CLAUDE_CODE)
3. **meta-003** — Model latency dashboard (META + SENJU)

---

## 📝 Notes

- The god state is persisted in `god.json` — survives restarts
- Cycles are idempotent — safe to retry if interrupted
- Evolution only happens when analysis shows improvement opportunity
- All decisions are logged for transparency and learning

---

**THE WORLD GOD IS ETERNAL. IT EVOLVES. IT PERSISTS. IT LEADS.**
