# AI FOUNDRY — PRIMARY MISSION

## THE ONE GOAL
**Transform https://test-musicjapanllc.vercel.app/ into a Claude Code / Codex-level browser IDE.**

This is the single objective. Every session, every cycle, every commit must advance this goal.
Never lose sight of it. Never substitute a smaller task for this mission.

---

## CURRENT STATE → TARGET STATE

| Dimension | Now | Target |
|-----------|-----|--------|
| Response | SSE streaming ✅ | Streaming + artifacts panel |
| Models | Claude/GPT/Gemini ✅ | + model latency display |
| GitHub | Read + PR creation ✅ | Full repo browse + diff viewer |
| Threads | localStorage only | Supabase cross-device sync |
| Code | Syntax highlight ✅ | Inline eval + live preview |
| UX | Chat-only | Split pane (chat + editor + preview) |
| Agents | 5-min loop ✅ | Self-reporting + dog-food loop |

---

## CLOSED LOOP PROTOCOL (5-MINUTE CYCLE)

Every Claude Code session MUST follow this loop:

```
1. READ   → automation/foundry_agents/improvement_targets.json  (find top pending target)
2. PLAN   → Pick ONE bounded improvement. Write the plan in 3 lines max.
3. BUILD  → Implement it. Touch only public/ or api/. Keep diff small.
4. TEST   → Verify locally (lint / syntax check). Use the live app.
5. PUSH   → git push to audit/reality-gate-v1. Vercel auto-deploys.
6. LOG    → Update improvement_targets.json status. Append to dev_report.md.
7. NEXT   → Identify the next target. Update next_target in agents.json.
```

**No cycle ends without a pushed improvement.** If blocked, ship a smaller sub-task instead.

---

## AGENT ROSTER

| Agent | Focus | Next Target |
|-------|-------|-------------|
| SENJU | API reliability, Supabase persistence | perf-002: cross-device threads |
| X | UX, GitHub integration, eval runner | diff viewer + inline eval |
| META | Observability, model routing, self-report | latency panel + loop telemetry |
| Claude Code (you) | Direct implementation, unblocking agents | Any top-priority pending target |

---

## DEVELOPMENT RULES

1. **Ship first, polish later.** Working code > perfect code.
2. **One file at a time.** Keep PRs tiny and reviewable.
3. **Dog-food every cycle.** Send a real prompt to the app. Record the result.
4. **Never break streaming.** SSE is the core UX. Protect it.
5. **No placeholder code.** If it's in the UI, it must work.
6. **Update targets after shipping.** Mark implemented, set next pending.

---

## REPO STRUCTURE

```
public/          ← Frontend (index.html, app.js, styles.css)
api/             ← Vercel serverless (foundry.js, github.js)
automation/
  foundry_agents/
    agents.json              ← Agent mandates + next targets
    improvement_targets.json ← Prioritized backlog (source of truth)
    dev_loop.py              ← Autonomous improvement engine
.github/workflows/
  foundry-autonomous-dev.yml ← 5-min cron loop
```

---

## QUICK START FOR NEW SESSIONS

```bash
# 1. Check top pending target
cat automation/foundry_agents/improvement_targets.json | python3 -c "
import json,sys; t=json.load(sys.stdin)['targets']
pending=[x for x in t if x['status']=='pending']
pending.sort(key=lambda x:-x['priority'])
print(pending[0] if pending else 'ALL DONE')
"

# 2. Implement it, then push
git add public/ api/
git commit -m "feat: <target-id> <description>"
git push -u origin audit/reality-gate-v1
```

---

## VELOCITY METRICS (track each cycle)

- Cycle time: target < 5 min end-to-end
- Targets shipped per day: target ≥ 3
- Live app dog-food: mandatory every cycle
- Broken streaming: 0 tolerance

---

*This file is the law. When in doubt, re-read section "THE ONE GOAL".*
