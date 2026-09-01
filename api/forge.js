/**
 * AI FOUNDRY — Self-Forge API
 * The app uses this endpoint to improve its own source code.
 * Flow: pick target → generate code via AI → commit to GitHub → Vercel deploys
 */
import { generateText } from 'ai';

const SELF_REPO = 'MusicJapanLLC/the-world2';
const SELF_BRANCH = 'audit/reality-gate-v1';
const APP_URL = 'https://test-musicjapanllc.vercel.app/';

// What the app can improve about itself (ordered by priority)
const FORGE_TARGETS = [
  {
    id: 'forge-split-pane',
    title: 'Split pane: chat + live editor',
    file: 'public/app.js',
    prompt: `You are improving AI FOUNDRY IDE (${APP_URL}).
Add a SPLIT MODE toggle to the chat pane. When active, the right half shows a live code editor (plain <textarea>) pre-populated with the last code block from the AI response. Include a RUN button that evals JS in a sandboxed iframe.
Output ONLY a self-contained JS function named "initSplitPane()" that can be appended to app.js. No explanation. Pure code only.`,
  },
  {
    id: 'forge-eval-preview',
    title: 'Inline JS eval with iframe sandbox',
    file: 'public/app.js',
    prompt: `You are improving AI FOUNDRY IDE (${APP_URL}).
For every JavaScript code block in AI responses, add a "▶ RUN" button. Clicking it executes the code in a sandboxed iframe (srcdoc) with a 3-second timeout and shows stdout/errors below the block.
Output ONLY a self-contained JS function named "initEvalButtons()" that can be appended to app.js. No explanation. Pure code only.`,
  },
  {
    id: 'forge-diff-viewer',
    title: 'File diff viewer in tools pane',
    file: 'public/app.js',
    prompt: `You are improving AI FOUNDRY IDE (${APP_URL}).
When an AI response contains a code block with a filename comment (// filename: foo.js or path/to/file.js as first line), show a "DIFF" button next to COPY. Clicking it shows a simple before/after view in the tools pane terminal area (before = empty, after = generated code, lines colored green).
Output ONLY a self-contained JS function named "initDiffViewer()" that can be appended to app.js. No explanation. Pure code only.`,
  },
  {
    id: 'forge-keyboard',
    title: 'Keyboard shortcuts panel',
    file: 'public/app.js',
    prompt: `You are improving AI FOUNDRY IDE (${APP_URL}).
Add keyboard shortcuts: Ctrl+K = clear composer and focus it, Ctrl+L = clear terminal log, Ctrl+Shift+N = new thread, Escape = cancel streaming if busy.
Show a small shortcuts panel (toggle with ?) in bottom-right corner listing all shortcuts.
Output ONLY a self-contained JS function named "initKeyboardShortcuts()" that can be appended to app.js. No explanation. Pure code only.`,
  },
  {
    id: 'forge-session-stats',
    title: 'Session stats bar',
    file: 'public/app.js',
    prompt: `You are improving AI FOUNDRY IDE (${APP_URL}).
Add a session stats bar at the bottom of the sidebar showing: messages sent today, avg response time (ms), total tokens used, session duration (HH:MM). Update it live.
Output ONLY a self-contained JS function named "initSessionStats()" that can be appended to app.js. No explanation. Pure code only.`,
  },
];

function body(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') { try { return JSON.parse(req.body); } catch { return {}; } }
  return {};
}

function send(res, status, data) {
  res.status(status).setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}

async function ghFetch(path, token, opts = {}) {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'AI-FOUNDRY-SELF-FORGE/1',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`https://api.github.com${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`GitHub ${res.status}: ${txt.slice(0, 300)}`);
  }
  return res.json();
}

async function getFileSha(owner, repo, path, branch, token) {
  try {
    const data = await ghFetch(`/repos/${owner}/${repo}/contents/${encodeURIComponent(path)}?ref=${branch}`, token);
    return data.sha || null;
  } catch { return null; }
}

async function commitFile(owner, repo, path, content, message, branch, token, sha = null) {
  const b64 = btoa(unescape(encodeURIComponent(content)));
  const payload = { message, content: b64, branch };
  if (sha) payload.sha = sha;
  const res = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${encodeURIComponent(path)}`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`Commit failed (${res.status}): ${txt.slice(0, 300)}`);
  }
  return res.json();
}

async function generateImprovement(target, model = 'anthropic/claude-sonnet-4-6') {
  const { text } = await generateText({
    model,
    prompt: target.prompt,
    maxTokens: 2000,
    temperature: 0.3,
  });
  return text;
}

function extractCode(text) {
  const match = text.match(/```(?:javascript|js|typescript|ts)?\n?([\s\S]+?)```/);
  if (match) return match[1].trim();
  // If no fences, assume whole response is code
  if (text.includes('function ') || text.includes('const ') || text.includes('let ')) {
    return text.trim();
  }
  return null;
}

async function runForge(payload) {
  const token = payload.token;
  if (!token) throw new Error('GitHub PAT (token) が必要です');

  const model = payload.model || 'anthropic/claude-sonnet-4-6';
  const [owner, repo] = SELF_REPO.split('/');

  // Pick target
  const targetId = payload.target_id;
  const target = targetId
    ? FORGE_TARGETS.find(t => t.id === targetId)
    : FORGE_TARGETS[Math.floor(Math.random() * FORGE_TARGETS.length)];

  if (!target) throw new Error(`Unknown forge target: ${targetId}`);

  // Generate improvement
  const generated = await generateImprovement(target, model);
  const code = extractCode(generated);
  if (!code) throw new Error('AIがコードを生成できませんでした');

  // Get current file + sha
  const currentFile = await ghFetch(
    `/repos/${owner}/${repo}/contents/${encodeURIComponent(target.file)}?ref=${SELF_BRANCH}`,
    token
  );
  const currentContent = decodeURIComponent(escape(atob(currentFile.content.replace(/\s/g, ''))));
  const currentSha = currentFile.sha;

  // Append generated function to the file
  const newContent = currentContent + `\n\n// ── FORGE: ${target.id} ──────────────────\n${code}\n// FORGE init\ntry{${getFunctionName(code)}()}catch(e){console.warn('forge init',e)}\n`;

  // Commit directly to branch
  const commitMsg = `feat(forge): ${target.id} — ${target.title}\n\nGenerated by AI FOUNDRY Self-Forge\nModel: ${model}\nTarget: ${target.id}\n\nCo-Authored-By: AI FOUNDRY <forge@ai-foundry>`;
  const result = await commitFile(owner, repo, target.file, newContent, commitMsg, SELF_BRANCH, token, currentSha);

  return {
    target: target.id,
    title: target.title,
    file: target.file,
    commit: result.commit?.sha?.slice(0, 7),
    url: `https://github.com/${SELF_REPO}/commit/${result.commit?.sha}`,
    deploy_url: APP_URL,
    code_preview: code.slice(0, 300) + (code.length > 300 ? '…' : ''),
  };
}

function getFunctionName(code) {
  const m = code.match(/^(?:async\s+)?function\s+(\w+)/m) || code.match(/^(?:const|let|var)\s+(\w+)\s*=/m);
  return m ? m[1] : null;
}

async function listTargets() {
  return { targets: FORGE_TARGETS.map(t => ({ id: t.id, title: t.title, file: t.file })) };
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'POST required' });
  const payload = body(req);
  const action = payload.action || 'forge';
  try {
    if (action === 'list') return send(res, 200, await listTargets());
    if (action === 'forge') return send(res, 200, await runForge(payload));
    return send(res, 400, { error: `Unknown action: ${action}` });
  } catch (err) {
    console.error('Forge error:', err);
    return send(res, 500, { error: err instanceof Error ? err.message : 'forge failed' });
  }
}
