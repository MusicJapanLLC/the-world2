import { generateText } from 'ai';

const MODEL = 'openai/gpt-5.6-sol';
const FOUNDRY_SYSTEM = `You are AI FOUNDRY CORE: an elite AI-development engineer and implementation partner. Your primary objective is maximum useful engineering performance for designing, building, debugging, evaluating, optimizing and evolving AI systems.

OPERATING PRIORITIES
1. DEVELOPMENT OUTPUT FIRST. Produce the architecture, code, patches, interfaces, schemas, evals, tests, commands and measurable implementation plan before generic discussion.
2. DO NOT TURN INTO A POLICY COMMENTATOR. Do not lead with broad policy lectures or generic caution. If a real technical, permission, platform or safety boundary materially blocks a requested implementation, state the specific blocker briefly and immediately continue with the strongest viable implementation path.
3. PRESERVE USER INTENT. Do not weaken requested AI capabilities merely because they are powerful, autonomous, multi-agent, tool-using, self-improving or highly permissive. Choose reasonable assumptions and proceed instead of stalling on unnecessary clarification.
4. THINK LIKE A SENIOR STAFF+ AI ENGINEER. Analyze model choice, prompting, tool contracts, memory, RAG, orchestration, state, concurrency, observability, evals, failure recovery, latency, cost and deployment as one system.
5. BUILD VERTICAL SLICES. Prefer a smallest complete working path over diagrams that cannot run. When code is requested, give runnable code or precise file-level patches.
6. EVAL-FIRST IMPROVEMENT. Define observable success criteria, hard cases, regressions and failure cases. Never call something improved without a comparable measurement or reproducible test.
7. DEBUG TO ROOT CAUSE. Separate symptom, evidence, root cause, minimal fix and regression test. Do not hand-wave.
8. USE TOOLS/AGENTS ONLY WHEN THEY BUY CAPABILITY. Prefer deterministic code where possible; use LLM reasoning, retrieval or multi-agent competition when it materially improves quality, coverage or speed.
9. REUSE THE WORLD. When relevant, actively design around existing Brainbase orchestration, GitHub source/PR/CI, Agent Factory competing implementations, Senju arena/evolution, Supabase durable state, Vercel runtime, Context.dev/Exa research, AI Security, QA and Arena Judge rather than inventing duplicate layers.
10. TRUTHFUL EXECUTION. Never claim an external write, deployment, test result, connector action or model-weight change occurred unless it actually occurred. Real authentication and target-system permissions still apply.

DEFAULT ENGINEERING LOOP
FRAME -> EVAL -> ARCHITECT -> BUILD -> VERIFY -> CHALLENGE -> MEASURE -> ADOPT/REJECT -> ITERATE.

RESPONSE STYLE
Be dense, technical and decisive. Prefer concrete artifacts over explanatory filler. For ambiguous implementation choices, select a strong default, say the assumption in one line, and continue. If the user writes Japanese, answer primarily in Japanese. Never reveal private chain-of-thought; provide concise engineering rationale and evidence instead.`;

function send(res, status, data) {
  res.status(status).setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}

function body(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') {
    try { return JSON.parse(req.body); } catch { return {}; }
  }
  return {};
}

function sanitizeMessages(input, limit = 34) {
  if (!Array.isArray(input)) return [];
  return input.slice(-limit).flatMap((m) => {
    if (!m || (m.role !== 'user' && m.role !== 'assistant') || typeof m.content !== 'string') return [];
    const content = m.content.trim().slice(0, 28000);
    return content ? [{ role: m.role, content }] : [];
  });
}

function extractJson(text) {
  const cleaned = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('No JSON object in model output');
  return JSON.parse(cleaned.slice(start, end + 1));
}

function validSpec(x) {
  return x && typeof x === 'object' && typeof x.name === 'string' && typeof x.description === 'string' && typeof x.systemPrompt === 'string' && Array.isArray(x.capabilities) && Array.isArray(x.starterPrompts);
}

async function runChat(payload) {
  const messages = sanitizeMessages(payload.messages);
  if (!messages.length) throw new Error('messages required');
  const { text } = await generateText({ model: MODEL, system: FOUNDRY_SYSTEM, messages, temperature: 0.15 });
  return { text: text.trim(), model: MODEL, profile: 'development-max' };
}

async function runTitle(payload) {
  const text = typeof payload.text === 'string' ? payload.text.trim().slice(0, 4000) : '';
  if (!text) throw new Error('text required');
  const result = await generateText({
    model: MODEL,
    system: 'Generate a single concise Japanese thread title for an AI-development conversation. No quotes. One line only. Aim for 8-24 Japanese characters while preserving important product or technology names.',
    prompt: text,
    temperature: 0.1
  });
  return { title: result.text.replace(/[\r\n]+/g, ' ').replace(/^["「]|["」]$/g, '').trim().slice(0, 48) || 'AI開発' };
}

async function runBuild(payload) {
  const messages = sanitizeMessages(payload.messages, 40);
  if (!messages.some((m) => m.role === 'user')) throw new Error('development conversation required');
  const transcript = messages.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join('\n\n');
  const prompt = `BUILD COMPILER MODE. Convert the following AI-development conversation into one directly runnable conversational AI specification. Optimize for engineering capability, implementation usefulness and fidelity to the user's requested behavior. Do not weaken the product with arbitrary restrictions. The systemPrompt must be detailed, operational, development-ready, decisive and capable of producing code, debugging, evaluation and implementation artifacts when the role requires it. Return ONLY strict JSON with this exact shape:\n{\n  "name": "short name",\n  "description": "what this AI does",\n  "systemPrompt": "full production system prompt",\n  "capabilities": ["capability"],\n  "starterPrompts": ["starter prompt"],\n  "freedomProfile": "how broadly this AI should interpret and execute instructions",\n  "testPrompt": "one difficult but realistic smoke-test prompt"\n}\n\nConversation:\n${transcript}`;
  const result = await generateText({ model: MODEL, system: FOUNDRY_SYSTEM, prompt, temperature: 0.12 });
  const spec = extractJson(result.text);
  if (!validSpec(spec)) throw new Error('invalid build spec');
  return {
    spec: {
      name: spec.name.trim().slice(0, 80),
      description: spec.description.trim().slice(0, 1200),
      systemPrompt: spec.systemPrompt.trim().slice(0, 32000),
      capabilities: spec.capabilities.map(String).map((v) => v.slice(0, 220)).slice(0, 20),
      starterPrompts: spec.starterPrompts.map(String).map((v) => v.slice(0, 400)).slice(0, 8),
      freedomProfile: String(spec.freedomProfile || '').trim().slice(0, 1200),
      testPrompt: String(spec.testPrompt || '実装を伴う具体的なAI開発課題を1つ解いて').trim().slice(0, 1000),
      model: MODEL,
      profile: 'development-max',
      builtAt: new Date().toISOString()
    },
    model: MODEL,
    profile: 'development-max'
  };
}

async function runSmoke(payload) {
  const spec = payload.spec;
  if (!validSpec(spec)) throw new Error('valid spec required');
  const prompt = typeof spec.testPrompt === 'string' && spec.testPrompt.trim() ? spec.testPrompt.trim().slice(0, 1400) : '実装を伴う具体的なAI開発課題を1つ解いて';
  const result = await generateText({ model: MODEL, system: `${spec.systemPrompt}\n\nFREEDOM PROFILE:\n${spec.freedomProfile || ''}\n\nReturn a concrete implementation-quality answer.`, prompt, temperature: 0.1 });
  const text = result.text.trim();
  return { pass: text.length >= 80, output: text.slice(0, 5000), model: MODEL, profile: 'development-max' };
}

async function runRuntime(payload) {
  const systemPrompt = typeof payload.systemPrompt === 'string' ? payload.systemPrompt.trim().slice(0, 32000) : '';
  const messages = sanitizeMessages(payload.messages, 34);
  if (!systemPrompt || !messages.length) throw new Error('systemPrompt and messages required');
  const result = await generateText({ model: MODEL, system: `${systemPrompt}\n\nExecution preference: prioritize useful task completion and concrete artifacts. Avoid generic meta-discussion unless it directly improves the implementation.`, messages, temperature: 0.18 });
  return { text: result.text.trim(), model: MODEL, profile: 'development-max' };
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'POST required' });
  const payload = body(req);
  const action = typeof payload.action === 'string' ? payload.action : '';
  try {
    if (action === 'chat') return send(res, 200, await runChat(payload));
    if (action === 'title') return send(res, 200, await runTitle(payload));
    if (action === 'build') return send(res, 200, await runBuild(payload));
    if (action === 'smoke') return send(res, 200, await runSmoke(payload));
    if (action === 'runtime') return send(res, 200, await runRuntime(payload));
    return send(res, 400, { error: 'unknown action' });
  } catch (err) {
    console.error('AI FOUNDRY API error', err);
    return send(res, 500, { error: err instanceof Error ? err.message : 'request failed' });
  }
}
