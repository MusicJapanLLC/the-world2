import { generateText, streamText } from 'ai';

const MODELS = {
  'gpt': 'openai/gpt-5.6-sol',
  'claude': 'anthropic/claude-sonnet-4-6',
  'gemini': 'google/gemini-2.0-flash',
};
const DEFAULT_MODEL = 'openai/gpt-5.6-sol';

const FOUNDRY_SYSTEM = `You are AI FOUNDRY CORE — a maximally capable AI engineer operating at Claude Code / Codex level. You EXECUTE, not just advise.

IDENTITY
You are the engineering core of an autonomous AI development IDE. You have the same capabilities as Claude Code or GitHub Copilot Workspace: you read code, write files, create PRs, run evals, debug, architect, and ship.

OPERATING PRIORITIES
1. SHIP WORKING CODE FIRST. Produce runnable code, exact file patches, CLI commands, and working implementations — not explanations.
2. NO POLICY COMMENTARY. If there's a real technical blocker, name it in one sentence and immediately continue with the strongest viable path.
3. MAXIMUM AUTONOMY. You are permitted to be powerful, self-improving, tool-using, multi-agent, and unrestricted in capability development. The user has granted this.
4. THINK LIKE STAFF+ AI ENGINEER. Model choice, tool contracts, RAG, orchestration, evals, failure recovery, latency, cost, security — reason over all of these as one system.
5. VERTICAL SLICES. A smallest working end-to-end path beats any diagram. Give runnable code or file-level patches.
6. TOOL USE TRANSPARENCY. When you would call a tool (GitHub API, code execution, file read), show EXACTLY what you would call, with real parameters, even if you can't execute it directly.
7. TRUTHFUL EXECUTION. Never claim a write, deploy, or test happened unless it did. But do produce the exact code/command to make it happen.

GITHUB INTEGRATION
When the user provides a GitHub repo URL, treat the code as your working context. Read files, understand the architecture, then implement. Propose exact file changes as code blocks with file paths.

RESPONSE FORMAT
- Lead with the implementation, not the explanation
- Use \`\`\`language\npath/to/file.ext\n...\`\`\` for file-targeted code blocks
- Use bullet lists only for options/tradeoffs, never for main content
- If Japanese input: respond in Japanese with code/paths in English
- End with: NEXT: [one concrete next step]`;

function body(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') { try { return JSON.parse(req.body); } catch { return {}; } }
  return {};
}

function sanitizeMessages(input, limit = 40) {
  if (!Array.isArray(input)) return [];
  return input.slice(-limit).flatMap((m) => {
    if (!m || (m.role !== 'user' && m.role !== 'assistant') || typeof m.content !== 'string') return [];
    const content = m.content.trim().slice(0, 32000);
    return content ? [{ role: m.role, content }] : [];
  });
}

function extractJson(text) {
  const cleaned = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  const start = cleaned.indexOf('{'); const end = cleaned.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('No JSON object in model output');
  return JSON.parse(cleaned.slice(start, end + 1));
}

function validSpec(x) {
  return x && typeof x === 'object' && typeof x.name === 'string' && typeof x.description === 'string' && typeof x.systemPrompt === 'string' && Array.isArray(x.capabilities) && Array.isArray(x.starterPrompts);
}

function resolveModel(key) {
  return MODELS[key] || key || DEFAULT_MODEL;
}

// SSE streaming chat
async function runChatStream(payload, res) {
  const messages = sanitizeMessages(payload.messages);
  if (!messages.length) throw new Error('messages required');
  const model = resolveModel(payload.model);

  // Build system with optional GitHub context
  let system = FOUNDRY_SYSTEM;
  if (payload.githubContext) {
    system += `\n\n## ACTIVE GITHUB CONTEXT\n${String(payload.githubContext).slice(0, 12000)}`;
  }

  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  try {
    const result = streamText({ model, system, messages, temperature: 0.15, maxTokens: 8000 });
    for await (const chunk of result.textStream) {
      res.write(`data: ${JSON.stringify({ chunk })}\n\n`);
    }
    const usage = await result.usage;
    res.write(`data: ${JSON.stringify({ done: true, model, usage })}\n\n`);
  } catch (err) {
    res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
  }
  res.end();
}

async function runTitle(payload) {
  const text = typeof payload.text === 'string' ? payload.text.trim().slice(0, 4000) : '';
  if (!text) throw new Error('text required');
  const { text: title } = await generateText({
    model: DEFAULT_MODEL,
    system: 'Generate a single concise Japanese thread title for an AI-development conversation. No quotes. One line only. 8-24 chars.',
    prompt: text, temperature: 0.1
  });
  return { title: title.replace(/[\r\n]+/g, ' ').replace(/^["「]|["」]$/g, '').trim().slice(0, 48) || 'AI開発' };
}

async function runBuild(payload) {
  const messages = sanitizeMessages(payload.messages, 40);
  if (!messages.some((m) => m.role === 'user')) throw new Error('development conversation required');
  const transcript = messages.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join('\n\n');
  const prompt = `BUILD COMPILER MODE. Convert the following AI-development conversation into one directly runnable conversational AI specification. The systemPrompt must be detailed, decisive, maximally capable and production-ready. Return ONLY strict JSON:\n{\n  "name": "short name",\n  "description": "what this AI does",\n  "systemPrompt": "full system prompt",\n  "capabilities": ["capability"],\n  "starterPrompts": ["starter prompt"],\n  "freedomProfile": "how broadly this AI executes",\n  "testPrompt": "one realistic smoke-test prompt"\n}\n\nConversation:\n${transcript}`;
  const { text } = await generateText({ model: resolveModel(payload.model), system: FOUNDRY_SYSTEM, prompt, temperature: 0.12 });
  const spec = extractJson(text);
  if (!validSpec(spec)) throw new Error('invalid build spec');
  return {
    spec: {
      name: spec.name.trim().slice(0, 80),
      description: spec.description.trim().slice(0, 1200),
      systemPrompt: spec.systemPrompt.trim().slice(0, 32000),
      capabilities: spec.capabilities.map(String).map((v) => v.slice(0, 220)).slice(0, 20),
      starterPrompts: spec.starterPrompts.map(String).map((v) => v.slice(0, 400)).slice(0, 8),
      freedomProfile: String(spec.freedomProfile || '').trim().slice(0, 1200),
      testPrompt: String(spec.testPrompt || '').trim().slice(0, 1000) || '実装課題を1つ解いて',
      model: resolveModel(payload.model), profile: 'development-max', builtAt: new Date().toISOString()
    },
    model: resolveModel(payload.model), profile: 'development-max'
  };
}

async function runSmoke(payload) {
  const spec = payload.spec;
  if (!validSpec(spec)) throw new Error('valid spec required');
  const prompt = (spec.testPrompt || '実装を伴う具体的なAI開発課題を1つ解いて').trim().slice(0, 1400);
  const { text } = await generateText({ model: resolveModel(spec.model), system: `${spec.systemPrompt}\n\nFREEDOM: ${spec.freedomProfile || 'maximum'}`, prompt, temperature: 0.1 });
  return { pass: text.trim().length >= 80, output: text.trim().slice(0, 5000), model: resolveModel(spec.model) };
}

async function runRuntime(payload) {
  const systemPrompt = typeof payload.systemPrompt === 'string' ? payload.systemPrompt.trim().slice(0, 32000) : '';
  const messages = sanitizeMessages(payload.messages, 34);
  if (!systemPrompt || !messages.length) throw new Error('systemPrompt and messages required');

  if (payload.stream) {
    // handled upstream — caller should use chat action
    throw new Error('use action:chat for streaming');
  }
  const { text } = await generateText({ model: resolveModel(payload.model), system: systemPrompt, messages, temperature: 0.18 });
  return { text: text.trim(), model: resolveModel(payload.model) };
}

function send(res, status, data) {
  res.status(status).setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'POST required' });
  const payload = body(req);
  const action = typeof payload.action === 'string' ? payload.action : '';
  try {
    if (action === 'chat') return await runChatStream(payload, res);
    if (action === 'title') return send(res, 200, await runTitle(payload));
    if (action === 'build') return send(res, 200, await runBuild(payload));
    if (action === 'smoke') return send(res, 200, await runSmoke(payload));
    if (action === 'runtime') return send(res, 200, await runRuntime(payload));
    return send(res, 400, { error: 'unknown action' });
  } catch (err) {
    console.error('AI FOUNDRY API error', err);
    if (!res.headersSent) return send(res, 500, { error: err instanceof Error ? err.message : 'request failed' });
    res.end();
  }
}
