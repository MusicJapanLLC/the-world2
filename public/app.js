// AI FOUNDRY IDE v2 — app.js
const $=(s)=>document.querySelector(s);
const STORE='ai-foundry-threads-v3';
const GATEWAY='https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-runtime';
let threads=loadThreads();
let activeId=threads[0]?.id||null;
let busy=false;
let githubContext='';
let githubToken=localStorage.getItem('foundry-gh-token')||'';
let githubRepo=localStorage.getItem('foundry-gh-repo')||'';
let currentModel='gpt';
const executionTimers=new Map();

// Perf tracking
const MODEL_COSTS={claude:{input:3.0,output:15.0},gemini:{input:0.075,output:0.30},gpt:{input:2.50,output:10.0}};
let _sessionInputTokens=0,_sessionOutputTokens=0,_sessionMessages=0;

function updatePerfPanel(latencyMs,usage,model){
  const el=document.getElementById('latencyDisplay');if(el)el.textContent=latencyMs>0?latencyMs+'ms':'—';
  if(usage){_sessionInputTokens+=usage.promptTokens||0;_sessionOutputTokens+=usage.completionTokens||0}
  const costs=MODEL_COSTS[model]||MODEL_COSTS.gpt;
  const est=(_sessionInputTokens/1e6*costs.input)+(_sessionOutputTokens/1e6*costs.output);
  const ce=document.getElementById('costDisplay');if(ce)ce.textContent='$'+est.toFixed(4);
  const tt=document.getElementById('tokenTotal');if(tt)tt.textContent=(_sessionInputTokens+_sessionOutputTokens).toLocaleString();
}

function loadThreads(){try{return JSON.parse(localStorage.getItem(STORE)||'[]')}catch{return[]}}
function saveThreads(){localStorage.setItem(STORE,JSON.stringify(threads));syncThreadsToSupabase().catch(()=>{})}
async function syncThreadsToSupabase(){
  try{
    const payload={action:'sync_threads',threads:threads,userEmail:'music.japan.llc@gmail.com'};
    const r=await fetch(GATEWAY,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'omit',redirect:'follow'});
    if(r.ok)return await r.json();
    return null;
  }catch(e){return null}
}
function uid(){return crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random()}`}
function active(){return threads.find(t=>t.id===activeId)}
function stamp(){return new Date().toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}

function formatText(text){
  const parts=String(text).split(/(```[\s\S]*?```)/g);
  return parts.map((p)=>{
    if(p.startsWith('```')){
      const nl=p.indexOf('\n');
      const lang=nl>3?p.slice(3,nl).trim():'';
      const code=nl>0?p.slice(nl+1,-3):p.slice(3,-3);
      const escaped=escapeHtml(code);
      const copyId='copy-'+uid();
      let highlighted=escaped;
      try{
        if(lang&&window.hljs&&window.hljs.getLanguage(lang)){
          highlighted=window.hljs.highlight(code,{language:lang,ignoreIllegals:true}).value;
        }
      }catch{}
      return `<div class="code-wrap"><div class="code-header"><span class="code-lang">${escapeHtml(lang)||'code'}</span><button class="copy-btn" data-id="${copyId}" onclick="copyCode(this)">COPY</button><button class="copy-btn" onclick="sendToEditor('${copyId}')">→ EDITOR</button></div><pre><code id="${copyId}" class="hljs${lang?' language-'+escapeHtml(lang):''}">${highlighted}</code></pre></div>`;
    }
    return escapeHtml(p).replace(/\n/g,'<br>');
  }).join('');
}

window.copyCode=function(btn){
  const id=btn.dataset.id;
  const el=document.getElementById(id);
  if(!el)return;
  navigator.clipboard.writeText(el.innerText||el.textContent||'').then(()=>{
    btn.textContent='COPIED';btn.classList.add('copied');
    setTimeout(()=>{btn.textContent='COPY';btn.classList.remove('copied')},1800);
  }).catch(()=>{btn.textContent='ERR'});
};

function newThread(){
  const t={id:uid(),title:'New Session',createdAt:Date.now(),updatedAt:Date.now(),messages:[]};
  threads.unshift(t);activeId=t.id;saveThreads();renderAll(true);return t;
}
function log(line,type='ok'){
  const el=$('#terminal');
  const tag=type==='err'?'ERR':type==='warn'?'WRN':'RUN';
  el.textContent+=`[${stamp()}] ${tag}  ${line}\n`;
  el.scrollTop=el.scrollHeight;
}
function state(sel,value,pass=false){const el=$(sel);if(!el)return;el.textContent=value;el.style.color=pass?'#65ff9b':''}
function scrollToBottom(){requestAnimationFrame(()=>{const box=$('#messages');if(box)box.scrollTop=box.scrollHeight})}
function modelName(key){return key==='claude'?'anthropic/claude-sonnet-4-6':key==='gemini'?'google/gemini-2.0-flash':'openai/gpt-5.6-sol'}

async function streamChat(payload){
  const res=await fetch('/api/foundry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'chat',...payload})});
  if(!res.ok){const e=await res.json().catch(()=>({}));throw new Error(e.error||`HTTP ${res.status}`)}
  return res.body.getReader();
}
async function postJson(url,payload){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const ct=r.headers.get('content-type')||'';
  if(!ct.includes('application/json'))throw new Error(`non-json response (${r.status})`);
  const data=await r.json();
  if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}
async function direct(action,payload){return postJson('/api/foundry',{action,...payload})}
async function gateway(action,payload){
  const r=await fetch(GATEWAY,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...payload}),credentials:'omit',redirect:'follow'});
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}

// ── Thread rendering ──────────────────────────────────────────────────────────

function renderThreads(){
  const el=$('#threadList');el.innerHTML='';
  threads.forEach(t=>{
    const row=document.createElement('div');row.className=`thread ${t.id===activeId?'active':''}`;
    const timeStr=new Date(t.updatedAt).toLocaleString('ja-JP',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
    row.innerHTML=`<div><div class="thread-title">${escapeHtml(t.title)}</div><div class="thread-time">${timeStr}</div></div><button class="thread-delete">×</button>`;
    row.addEventListener('click',e=>{if(e.target.classList.contains('thread-delete'))return;activeId=t.id;renderAll(true);resumeExecution(t)});
    row.querySelector('.thread-delete').addEventListener('click',e=>{
      e.stopPropagation();threads=threads.filter(x=>x.id!==t.id);
      if(activeId===t.id)activeId=threads[0]?.id||null;
      saveThreads();renderAll(true);
    });
    el.appendChild(row);
  });
}

function renderMessages(follow=false){
  const t=active();
  $('#threadTitle').textContent=t?.title||'New Session';
  const box=$('#messages');
  if(!t||!t.messages.length){
    box.innerHTML=`<div class="welcome">
      <h3>AI FOUNDRY IDE v2</h3>
      <p>GitHub URLを左パネルで接続してコンテキスト付きで開発。リアルタイムSSEストリーミング対応。<br>
      <code>/pr owner/repo branch "タイトル"</code> でPR直接作成。<br>
      右の <strong>⚙ SELF-FORGE</strong> でAIがこのアプリ自身を改良します。</p>
      <div class="quick-actions">
        <button class="qa-btn" onclick="setComposer('Next.js App RouterでSupabase RLSを使ったCRUD実装 — 完全なコードを出力して')">Next.js + Supabase</button>
        <button class="qa-btn" onclick="setComposer('Python FastAPIでSSEストリーミングエンドポイントを実装して')">FastAPI SSE</button>
        <button class="qa-btn" onclick="setComposer('このTypeScriptファイルのanyを全部型付きに修正して')">TypeScript strict</button>
        <button class="qa-btn" onclick="setComposer('このアプリに追加できる機能を5つ提案して、それぞれ実装コードを出力して')">機能追加提案</button>
      </div>
    </div>`;
    if(follow)scrollToBottom();return;
  }
  box.innerHTML=t.messages.map(m=>`
    <article class="message ${m.role} ${m.error?'error':''}">
      <div class="role">${m.role==='user'?'YOU':'FOUNDRY'}</div>
      <div class="content">${formatText(m.content)}</div>
      ${m.usage?`<div class="usage-bar">↑${m.usage.promptTokens||0} ↓${m.usage.completionTokens||0} tok · ${m.model||''} · ${m.latencyMs||0}ms</div>`:''}
    </article>`).join('');
  if(follow)scrollToBottom();
}
function renderAll(follow=false){renderThreads();renderMessages(follow);renderExecution(active())}
function resizeComposer(){const c=$('#composer');c.style.height='auto';c.style.height=Math.min(c.scrollHeight,200)+'px'}
window.setComposer=function(text){const c=$('#composer');c.value=text;resizeComposer();c.focus()}

// ── GitHub Panel ──────────────────────────────────────────────────────────────

function updateGhPanel(){
  const connected=!!(githubContext&&githubRepo);
  const label=document.getElementById('ghConnectedLabel');
  const panel=document.getElementById('ghConnected');
  const ghState=$('#ghState');
  if(connected){
    if(label)label.textContent=`✓ ${githubRepo}`;
    if(panel)panel.classList.remove('hidden');
    if(ghState){ghState.textContent=githubRepo.split('/')[1]||'CONNECTED';ghState.style.color='#65ff9b'}
  } else {
    if(panel)panel.classList.add('hidden');
    if(ghState){ghState.textContent='DISCONNECTED';ghState.style.color=''}
  }
}

async function loadGithubRepo(){
  const urlInput=$('#githubUrl');
  const tokenInput=$('#githubToken');
  const urlRaw=urlInput.value.trim()||githubRepo;
  if(!urlRaw){log('GitHub: URLまたはowner/repoを入力してください','warn');return}
  const tok=tokenInput.value.trim()||githubToken;
  if(tok){githubToken=tok;localStorage.setItem('foundry-gh-token',tok)}

  // Normalize: accept "owner/repo" or full URL
  const url=urlRaw.includes('github.com')?urlRaw:`https://github.com/${urlRaw}`;
  $('#githubLoad').disabled=true;$('#githubLoad').textContent='LOADING…';
  $('#githubStatus').textContent='';
  log(`GitHub: loading ${url}…`);
  try{
    const r=await postJson('/api/github',{action:'read_repo',url,token:githubToken||undefined});
    githubContext=r.context||'';
    githubRepo=`${r.owner}/${r.repo}`;
    localStorage.setItem('foundry-gh-repo',githubRepo);
    urlInput.value=githubRepo;
    $('#githubStatus').textContent=`✓ ${r.fileCount} files`;
    log(`GitHub: loaded ${githubRepo} · ${r.fileCount} files`,'ok');
    updateGhPanel();
    // Show in chat
    const t=active()||newThread();
    t.messages.push({role:'assistant',content:`✓ GitHubリポジトリを接続しました\n\n**${githubRepo}** (${r.fileCount} files)\n\nこのリポジトリのコードを文脈として会話できます。何を改善しますか？`});
    t.updatedAt=Date.now();saveThreads();renderMessages(true);
  }catch(e){
    githubContext='';$('#githubStatus').textContent=`✗ ${e.message.slice(0,40)}`;
    log(`GitHub: ${e.message}`,'err');
  }finally{$('#githubLoad').disabled=false;$('#githubLoad').textContent='CONNECT REPO'}
}

// ── Execution ─────────────────────────────────────────────────────────────────

function showArtifact(spec,url){
  $('#artifact').classList.remove('hidden');
  $('#artifactName').textContent=spec.name||'Generated';
  $('#artifactDescription').textContent=spec.description||'';
  $('#artifactCaps').innerHTML=(spec.capabilities||[]).slice(0,6).map(x=>`<span class="cap">${escapeHtml(x)}</span>`).join('');
  $('#artifactUrl').href=url;$('#copyUrl').dataset.url=url;
}
function renderExecution(t){
  const ex=t?.execution;
  if(!ex){state('#buildState','IDLE');$('#artifact').classList.add('hidden');return}
  const s=ex.status||'queued';
  if(s==='ready'){state('#buildState','READY',true);if(ex.public_url)showArtifact({name:ex.result?.name||ex.title,description:ex.result?.description||'',capabilities:ex.result?.capabilities||[]},ex.public_url)}
  else if(s==='failed'){state('#buildState','FAIL');log(`BUILD FAILED · ${ex.error||'unknown'}`,'err')}
  else state('#buildState',s.toUpperCase());
}
function trackExecution(t,execution){
  const jobId=execution.jobId||execution.id;t.execution={...execution,jobId,status:execution.status||'queued'};
  t.updatedAt=Date.now();saveThreads();renderExecution(t);log(`EXECUTION QUEUED · ${jobId}`);scheduleExecutionPoll(t,1200);
}
function scheduleExecutionPoll(t,delay=7000){
  const jobId=t?.execution?.jobId;if(!jobId||['ready','failed'].includes(t.execution.status))return;
  if(executionTimers.has(jobId))clearTimeout(executionTimers.get(jobId));
  executionTimers.set(jobId,setTimeout(()=>pollExecution(t.id),delay));
}
async function pollExecution(threadId){
  const t=threads.find(x=>x.id===threadId);const jobId=t?.execution?.jobId;if(!t||!jobId)return;
  try{
    const r=await gateway('execution_status',{jobId});const ex=r.execution||{};
    t.execution={...t.execution,...ex,jobId:ex.id||jobId};t.updatedAt=Date.now();saveThreads();
    if(activeId===threadId)renderExecution(t);
    if(['ready','failed'].includes(t.execution.status))return;
  }catch(e){log(`execution poll · ${e.message}`,'warn')}
  scheduleExecutionPoll(t,7000);
}
function resumeExecution(t){if(t?.execution&&!['ready','failed'].includes(t.execution.status))scheduleExecutionPoll(t,500)}

async function titleThread(t,first){
  if(t.messages.filter(m=>m.role==='user').length!==1)return;
  try{const r=await direct('title',{text:first});t.title=r.title||t.title;t.updatedAt=Date.now();saveThreads();renderThreads();$('#threadTitle').textContent=t.title}
  catch{}
}

// ── Stream bubble ──────────────────────────────────────────────────────────────

function appendStreamingBubble(){
  const id='stream-'+uid();
  const box=$('#messages');
  const el=document.createElement('article');el.className='message assistant';el.id=id;
  el.innerHTML=`<div class="role">FOUNDRY</div><div class="content" id="${id}-c"><span class="cursor"></span></div>`;
  box.appendChild(el);scrollToBottom();
  return {id,contentId:`${id}-c`};
}

// ── /pr slash command ─────────────────────────────────────────────────────────

async function handlePrCommand(text){
  const m=text.match(/^\/pr\s+([\w.-]+\/[\w.-]+)\s+(\S+)\s+"([^"]+)"/);
  if(!m){log('/pr フォーマット: /pr owner/repo branch "タイトル"','warn');return}
  const [,repoSlug,head,title]=m;
  const tok=githubToken||$('#githubToken').value.trim();
  if(!tok){log('GitHub PATが必要です','err');return}

  // Show diff preview if diffs were added
  if(Object.keys(window.diffCache||{}).length>0){
    log(`PR作成: ${Object.keys(window.diffCache).length}個ファイル変更予定`);
    window.showDiffPreview();
  }

  log(`PR作成中: ${repoSlug} → ${head}`);
  try{
    const r=await postJson('/api/github',{action:'create_pr',url:`https://github.com/${repoSlug}`,token:tok,title,head,base:'main'});
    log(`PR作成完了: ${r.url}`,'ok');
    const t=active()||newThread();
    t.messages.push({role:'assistant',content:`✓ PR作成完了\n\nURL: ${r.url}\nNumber: #${r.number}\nTitle: ${r.title}`});
    t.updatedAt=Date.now();saveThreads();renderMessages(true);
    window.diffCache={}; // Clear diffs after PR created
  }catch(e){log(`PR作成失敗: ${e.message}`,'err')}
}

// ── Send ──────────────────────────────────────────────────────────────────────

async function send(){
  if(busy)return;
  const c=$('#composer');const text=c.value.trim();if(!text)return;
  if(text.startsWith('/pr ')){c.value='';resizeComposer();await handlePrCommand(text);return}
  const t=active()||newThread();
  t.messages.push({role:'user',content:text});t.updatedAt=Date.now();saveThreads();
  c.value='';resizeComposer();renderMessages(true);
  busy=true;$('#sendBtn').disabled=true;
  log(`→ ${modelName(currentModel)}`);
  titleThread(t,text);
  const model=currentModel;
  const {contentId}=appendStreamingBubble();
  let accumulated='';let lastUsage=null;let lastModel=model;
  const _t0=Date.now();
  try{
    const reader=await streamChat({messages:t.messages,model,githubContext:githubContext||undefined});
    const decoder=new TextDecoder();let buf='';
    while(true){
      const{done,value}=await reader.read();if(done)break;
      buf+=decoder.decode(value,{stream:true});
      const lines=buf.split('\n');buf=lines.pop()||'';
      for(const line of lines){
        if(!line.startsWith('data:'))continue;
        try{
          const evt=JSON.parse(line.slice(5).trim());
          if(evt.chunk){accumulated+=evt.chunk;const el=document.getElementById(contentId);if(el){el.innerHTML=formatText(accumulated)+'<span class="cursor"></span>';scrollToBottom()}}
          if(evt.done){
            lastUsage=evt.usage||null;lastModel=evt.model||modelName(model);
            const lat=Date.now()-_t0;
            updatePerfPanel(lat,lastUsage,model);
            log(`← ${lastModel} · ${lat}ms${lastUsage?` · ${(lastUsage.promptTokens||0)+(lastUsage.completionTokens||0)}tok`:''}`)
          }
          if(evt.error)throw new Error(evt.error);
        }catch(parseErr){if(!parseErr.message?.includes('JSON')&&!parseErr.message?.includes('Unexpected'))throw parseErr}
      }
    }
    const el=document.getElementById(contentId);if(el)el.innerHTML=formatText(accumulated||'(empty response)');
    const latFinal=Date.now()-_t0;
    t.messages.push({role:'assistant',content:accumulated||'(empty response)',usage:lastUsage,model:lastModel,latencyMs:latFinal});
    t.updatedAt=Date.now();saveThreads();renderThreads();renderMessages(false);scrollToBottom();
    _sessionMessages++;
  }catch(e){
    const el=document.getElementById(contentId);if(el)el.innerHTML=`<span class="error-text">ERROR: ${escapeHtml(e.message)}</span>`;
    t.messages.push({role:'assistant',content:`ERROR: ${e.message}`,error:true});t.updatedAt=Date.now();saveThreads();renderThreads();
    log(e.message,'err');
  }finally{busy=false;$('#sendBtn').disabled=false;c.focus();scrollToBottom()}
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

async function pipeline(){
  if(busy)return;const t=active();if(!t||!t.messages.some(m=>m.role==='user')){log('no conversation to build','warn');return}
  if(t.execution&&!['ready','failed'].includes(t.execution.status)){log(`execution active · ${t.execution.jobId}`,'warn');resumeExecution(t);return}
  busy=true;$('#runPipeline').disabled=true;state('#buildState','QUEUED');log('EXECUTE → queue build');
  try{const r=await gateway('execute',{messages:t.messages});if(!r.execution)throw new Error('no execution created');trackExecution(t,r.execution)}
  catch(e){state('#buildState','FAIL');log(`build failed: ${e.message}`,'err')}
  finally{busy=false;$('#runPipeline').disabled=false}
}

// ── SELF-FORGE ────────────────────────────────────────────────────────────────

let forgeAutoInterval=null;

function forgeStatusShow(msg,color='#65ff9b'){
  const el=$('#forgeStatus');if(!el)return;
  el.classList.remove('hidden');el.style.color=color;el.textContent=msg;
}

async function runSelfForge(targetId){
  const tok=githubToken||$('#githubToken').value.trim();
  if(!tok){
    forgeStatusShow('⚠ SELF-FORGEにはGitHub PATが必要です (左パネルで入力)','#ff8e8e');
    log('SELF-FORGE: GitHub PAT required','err');return;
  }
  const btn=$('#selfForgeBtn');btn.disabled=true;btn.textContent='⚙ FORGING…';
  forgeStatusShow('⚙ AI FOUNDRY — コード生成中…');
  log('SELF-FORGE: generating improvement…');
  try{
    const r=await postJson('/api/forge',{action:'forge',token:tok,model:modelName(currentModel),target_id:targetId});
    forgeStatusShow(`✓ ${r.title} → commit ${r.commit}`);
    log(`SELF-FORGE: ${r.target} · ${r.title} → ${r.commit}`,'ok');
    const t=active()||newThread();
    t.messages.push({role:'assistant',content:`⚙ SELF-FORGE 完了\n\n**${r.title}**\ncommit: \`${r.commit}\`\nfile: \`${r.file}\`\n\n\`\`\`javascript\n${r.code_preview}\n\`\`\`\n\nVercel自動デプロイ中 → ${r.deploy_url}`});
    t.updatedAt=Date.now();saveThreads();renderMessages(true);
  }catch(e){
    forgeStatusShow(`✗ FORGE FAILED: ${e.message}`,'#ff8e8e');
    log(`SELF-FORGE failed: ${e.message}`,'err');
  }finally{btn.disabled=false;btn.textContent='⚙ SELF-FORGE'}
}

// ── Model picker ───────────────────────────────────────────────────────────────

$('#modelPicker').addEventListener('change',e=>{
  currentModel=e.target.value;
  const name=modelName(currentModel);
  $('#modelDisplay').textContent=name;
  $('#modelLabel').textContent=`${name.split('/')[1]||name} · VERCEL AI`;
  log(`model → ${name}`);
});

// ── Event listeners ───────────────────────────────────────────────────────────

$('#newThread').addEventListener('click',newThread);
$('#sendBtn').addEventListener('click',send);
$('#composer').addEventListener('input',resizeComposer);
$('#composer').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
$('#runPipeline').addEventListener('click',pipeline);
$('#clearLog').addEventListener('click',()=>{$('#terminal').textContent=''});
$('#copyUrl').addEventListener('click',async e=>{const url=e.currentTarget.dataset.url;if(url){await navigator.clipboard.writeText(url);log('URL copied')}});
$('#githubLoad').addEventListener('click',loadGithubRepo);
$('#githubUrl').addEventListener('keydown',e=>{if(e.key==='Enter')loadGithubRepo()});
$('#githubToken').addEventListener('keydown',e=>{if(e.key==='Enter')loadGithubRepo()});

// Hint buttons
document.querySelectorAll('.hint').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const c=$('#composer');c.value=btn.dataset.text;resizeComposer();c.focus();
  });
});

// SELF-FORGE button
$('#selfForgeBtn').addEventListener('click',()=>runSelfForge());

// Auto-forge toggle
$('#autoImproveBtn').addEventListener('click',()=>{
  if(forgeAutoInterval){
    clearInterval(forgeAutoInterval);forgeAutoInterval=null;
    $('#autoImproveBtn').textContent='AUTO FORGE (5m)';
    log('auto-forge: stopped');return;
  }
  forgeAutoInterval=setInterval(()=>runSelfForge(),5*60*1000);
  $('#autoImproveBtn').textContent='■ STOP AUTO';
  log('auto-forge: started — every 5 minutes');
  runSelfForge();
});

// Diff viewer button (github-003)
const diffBtn=document.createElement('button');
diffBtn.id='diffViewerBtn';
diffBtn.className='secondary';
diffBtn.textContent='📊 SHOW DIFF';
diffBtn.style.marginTop='4px';
diffBtn.addEventListener('click',()=>{
  if(Object.keys(window.diffCache||{}).length===0){log('diffs: 変更がありません','warn');return}
  window.showDiffPreview();
});
const pipeline=$('.pipeline');
if(pipeline)pipeline.appendChild(diffBtn);

// ─── Keyboard shortcuts help overlay (ux-003) ────────────────────────────
(function initShortcutsOverlay(){
  const helpHTML=`<div id="helpOverlay" style="display:none;position:fixed;bottom:20px;right:20px;width:280px;background:#1a1a1a;border:1px solid #444;border-radius:8px;padding:16px;font-size:12px;color:#aaa;z-index:10000;box-shadow:0 4px 16px rgba(0,0,0,0.5)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <b style="color:#fff">KEYBOARD SHORTCUTS</b>
      <button id="closeHelp" style="background:none;border:none;color:#aaa;cursor:pointer;font-size:16px;padding:0;width:20px;height:20px">×</button>
    </div>
    <div style="line-height:1.8">
      <div><kbd style="background:#333;padding:2px 6px;border-radius:3px;font-family:monospace">Ctrl+K</kbd> Clear input</div>
      <div><kbd style="background:#333;padding:2px 6px;border-radius:3px;font-family:monospace">Ctrl+L</kbd> Clear log</div>
      <div><kbd style="background:#333;padding:2px 6px;border-radius:3px;font-family:monospace">Escape</kbd> Cancel stream</div>
      <div><kbd style="background:#333;padding:2px 6px;border-radius:3px;font-family:monospace">?</kbd> Toggle help</div>
      <div style="margin-top:8px;border-top:1px solid #333;padding-top:8px;color:#666">
        <div><span style="color:#888">/pr owner/repo branch "title"</span></div>
        <div style="font-size:11px">Create GitHub PR</div>
      </div>
    </div>
  </div>`;

  const body=document.body;if(body){body.insertAdjacentHTML('beforeend',helpHTML)}

  const helpOv=document.getElementById('helpOverlay');
  const closeBtn=document.getElementById('closeHelp');
  if(closeBtn)closeBtn.addEventListener('click',()=>{if(helpOv)helpOv.style.display='none'});
})();

// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&busy){busy=false;$('#sendBtn').disabled=false;log('stream cancelled','warn')}
  if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();const c=$('#composer');c.value='';resizeComposer();c.focus()}
  if((e.ctrlKey||e.metaKey)&&e.key==='l'){e.preventDefault();$('#terminal').textContent=''}
  if(e.key==='?'||e.key==='/'){if(e.key==='/')e.preventDefault();const h=document.getElementById('helpOverlay');if(h)h.style.display=h.style.display==='none'?'block':'none'}
});

// Clock
setInterval(()=>{$('#clock').textContent=stamp()},1000);

// ─── Session stats bar (ux-002) ───────────────────────────────────
(function initStatsBar(){
  const statsBarHTML=`<div id="statsBar" style="padding:8px;font-size:11px;text-align:center;border-top:1px solid #333;color:#888;line-height:1.4">
    <div>MESSAGES: <b id="msgCount">0</b></div>
    <div>LATENCY: <b id="avgLatency">—</b> ms</div>
    <div>TOKENS: <b id="tokenCount">0</b></div>
  </div>`;
  const modelLabel=document.getElementById('modelLabel');
  if(modelLabel&&modelLabel.parentNode){
    modelLabel.insertAdjacentHTML('afterend',statsBarHTML);
  }

  setInterval(()=>{
    const t=active();if(!t)return;
    document.getElementById('msgCount').textContent=(t.messages||[]).length;
    const latencies=(t.messages||[]).filter(m=>m.latencyMs).map(m=>m.latencyMs);
    const avgLat=latencies.length>0?Math.round(latencies.reduce((a,b)=>a+b,0)/latencies.length):0;
    document.getElementById('avgLatency').textContent=avgLat||'—';
    document.getElementById('tokenCount').textContent=(_sessionInputTokens+_sessionOutputTokens).toLocaleString();
  },2000);
})();

// ─── Load threads from Supabase (perf-002) ───────────────────────────────
async function loadThreadsFromSupabase(){
  try{
    const r=await fetch(GATEWAY,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'load_threads',userEmail:'music.japan.llc@gmail.com'}),credentials:'omit',redirect:'follow'});
    if(!r.ok)return null;
    const data=await r.json();
    if(data.threads&&Array.isArray(data.threads)&&data.threads.length>0){
      threads=data.threads;saveThreads();return true;
    }
    return false;
  }catch(e){return false}
}

// Init
if(githubToken){$('#githubToken').value=githubToken}
if(githubRepo){$('#githubUrl').value=githubRepo}
(async()=>{
  const loaded=await loadThreadsFromSupabase();
  if(!loaded&&(!threads||threads.length===0)){threads=loadThreads()}
  if(!activeId)newThread();else{renderAll(true);threads.forEach(resumeExecution)}
  updateGhPanel();
  log('AI FOUNDRY IDE v2 — boot complete');
  log(`GitHub: ${githubRepo?'✓ '+githubRepo:'not connected — enter repo in left panel'}`);
  log('models: GPT-5.6-SOL / Claude Sonnet / Gemini 2.0');
  log('⚙ SELF-FORGE: active — AI improves this app autonomously');
  log('shortcuts: Ctrl+K=clear input  Ctrl+L=clear log  Esc=cancel stream  ?=help');
})();

// ─── Split Pane Layout (ux-004) ──────────────────────────────
(function initSplitPane(){
  const editor=$('#editor');
  const divider=$('#divider');
  const splitContent=$('.split-content');
  const editorPane=$('.editor-pane');
  const previewPane=$('.preview-pane');

  if(!editor||!divider||!splitContent)return;

  // Track editor line/char count
  function updateEditorStats(){
    const lines=editor.value.split('\n').length;
    const chars=editor.value.length;
    const lc=$('#editorLines');const cc=$('#editorChars');
    if(lc)lc.textContent=lines;if(cc)cc.textContent=chars;
  }

  editor.addEventListener('input',()=>{updateEditorStats()});
  editor.addEventListener('change',()=>{updateEditorStats()});
  updateEditorStats();

  // Draggable divider to resize panes
  let isDragging=false;
  divider.addEventListener('mousedown',()=>{isDragging=true;document.body.style.cursor='col-resize'});
  document.addEventListener('mouseup',()=>{isDragging=false;document.body.style.cursor='auto'});
  document.addEventListener('mousemove',(e)=>{
    if(!isDragging)return;
    const rect=splitContent.getBoundingClientRect();
    const x=e.clientX-rect.left;
    const pct=(x/rect.width)*100;
    if(pct>30&&pct<70){
      editorPane.style.flex=`${pct} 0 auto`;
      previewPane.style.flex=`${100-pct} 0 auto`;
    }
  });

  // Update preview when user sends a message
  window.updatePreviewOutput=function(output){
    const preview=$('#preview');
    if(!preview)return;
    if(typeof output==='string'){
      preview.innerHTML=`<div style="white-space:pre-wrap;font-size:12px;line-height:1.6;color:#dce5df">${escapeHtml(output)}</div>`;
    }else if(output instanceof HTMLElement){
      preview.innerHTML='';preview.appendChild(output);
    }else{
      preview.innerHTML=`<div style="color:#65ff9b">${escapeHtml(JSON.stringify(output,null,2))}</div>`;
    }
    const status=$('#previewStatus');if(status)status.textContent='Updated';
  };

  // Clear preview
  window.clearPreview=function(){
    const preview=$('#preview');
    if(!preview)return;
    preview.innerHTML='<div class="preview-placeholder"><span>📄 Preview output will appear here</span><small>Execute code or view results</small></div>';
    const status=$('#previewStatus');if(status)status.textContent='Ready';
  };

  log('split-pane editor loaded');
})();

// ─── Monaco Editor Integration (ULTIMATE IDE v3) ─────────────────
(function initMonacoEditor(){
  // Configure Monaco loader
  require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.50.0/min/vs' }});

  require(['vs/editor/editor.main'], function() {
    // Initialize Monaco Editor
    const editor = monaco.editor.create(document.getElementById('monaco-editor'), {
      value: '// 🚀 ULTIMATE IDE v3\n// Start coding here\n// Press Ctrl+Enter or click RUN to execute\n\nconsole.log("Hello from Ultimate IDE!");',
      language: 'javascript',
      theme: 'vs-dark',
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      fontFamily: "'M PLUS 1 Code', 'Cascadia Code', Consolas, monospace",
      lineNumbers: 'on',
      scrollBeyondLastLine: false,
      wordWrap: 'on',
      tabSize: 2,
      insertSpaces: true
    });

    // Update position indicator
    editor.onDidChangeCursorPosition((e) => {
      const pos = editor.getPosition();
      if (pos) {
        document.getElementById('editorLines').textContent = pos.lineNumber;
        document.getElementById('editorCols').textContent = pos.column;
      }
    });

    // Auto-format on save
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      editor.getAction('editor.action.formatDocument').run();
    });

    // Execute on Ctrl+Enter
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      executeCode(editor.getValue());
    });

    // Store editor reference for global access
    window.monacoEditor = editor;

    // RUN button
    const runBtn = document.getElementById('runCodeBtn');
    if (runBtn) {
      runBtn.addEventListener('click', () => {
        executeCode(editor.getValue());
      });
    }

    log('✓ Monaco Editor loaded and ready');
  });

  // Enhanced code execution engine with HTML/CSS/JS support
  window.executeCode = function(code) {
    const preview = document.getElementById('preview');
    if (!preview) return;

    const startTime = performance.now();
    const output = [];
    const errors = [];

    // Detect if this is HTML/CSS content
    const isHTML = code.includes('<') || code.includes('<!DOCTYPE') || code.includes('<html');
    const isCSS = code.trim().startsWith('@') || code.includes('{') && !code.includes('function') && !code.includes('const') && !code.includes('let') && !code.includes('var');

    // Handle HTML/CSS/mixed content
    if (isHTML) {
      try {
        // Create a sandbox iframe for HTML
        const iframe = document.createElement('iframe');
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.style.background = '#fff';
        iframe.sandbox.add('allow-scripts');
        iframe.sandbox.add('allow-same-origin');

        // Build complete HTML document
        let htmlContent = code;
        if (!code.includes('<!DOCTYPE') && !code.includes('<html')) {
          htmlContent = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>body{margin:0;padding:8px;font-family:system-ui}</style>
</head>
<body>${code}</body>
</html>`;
        }

        const blob = new Blob([htmlContent], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        iframe.src = url;

        preview.innerHTML = '';
        preview.appendChild(iframe);

        const status = document.getElementById('previewStatus');
        if (status) status.textContent = '✓ HTML Preview';
      } catch (e) {
        preview.innerHTML = `<div style="color:#ff8e8e;padding:8px">Error rendering HTML: ${escapeHtml(e.message)}</div>`;
        const status = document.getElementById('previewStatus');
        if (status) status.textContent = '✗ Error';
      }
      return;
    }

    // JavaScript execution
    const originalLog = console.log;
    const originalError = console.error;
    const originalWarn = console.warn;

    console.log = (...args) => output.push(args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' '));
    console.error = (...args) => errors.push(args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' '));
    console.warn = (...args) => output.push('[WARN] ' + args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' '));

    try {
      const fn = new Function(code);
      const result = fn();

      if (result !== undefined && result !== null) {
        output.push(`✓ Result: ${typeof result === 'string' ? result : JSON.stringify(result, null, 2)}`);
      }

      console.log = originalLog;
      console.error = originalError;
      console.warn = originalWarn;

      const elapsed = (performance.now() - startTime).toFixed(2);
      let html = `<div style="font-size:12px;line-height:1.6;color:#dce5df;padding:8px;font-family:monospace">`;
      html += `<div style="color:#65ff9b;margin-bottom:8px">✓ Executed in ${elapsed}ms</div>`;
      if (output.length > 0) {
        output.forEach(line => {
          html += `<div>${escapeHtml(line)}</div>`;
        });
      } else {
        html += `<div style="color:#4d5b52">(no output)</div>`;
      }
      html += `</div>`;

      preview.innerHTML = html;
      const status = document.getElementById('previewStatus');
      if (status) status.textContent = '✓ Executed';
    } catch (e) {
      console.log = originalLog;
      console.error = originalError;
      console.warn = originalWarn;

      const elapsed = (performance.now() - startTime).toFixed(2);
      let html = `<div style="font-size:12px;line-height:1.6;color:#ff8e8e;padding:8px;font-family:monospace">`;
      html += `<div style="color:#ff8e8e;margin-bottom:8px">✗ Error (${elapsed}ms)</div>`;
      html += `<div>${escapeHtml(e.message)}</div>`;
      if (e.stack) {
        html += `<div style="color:#9db0a3;font-size:10px;margin-top:8px">${escapeHtml(e.stack.split('\n').slice(0, 3).join('\n'))}</div>`;
      }
      html += `</div>`;

      preview.innerHTML = html;
      const status = document.getElementById('previewStatus');
      if (status) status.textContent = '✗ Error';
    }
  };

  log('code executor initialized');
})();

// ─── Send AI-Generated Code to Editor ────────────────────────────
window.sendToEditor = function(codeId) {
  const el = document.getElementById(codeId);
  if (!el && !window.monacoEditor) return;

  const code = el ? (el.innerText || el.textContent || '') : '';
  if (!code) return;

  if (window.monacoEditor) {
    window.monacoEditor.setValue(code);
    window.monacoEditor.focus();
    log(`✓ Code loaded into editor (${code.split('\n').length} lines)`);
  }
};

// ─── Diff Viewer (github-003) ────────────────────────────────────
window.diffCache = {}; // Store diffs: { filePath: {old, new} }

window.addFileDiff = function(filePath, oldContent, newContent) {
  window.diffCache[filePath] = { old: oldContent || '', new: newContent || '' };
  log(`✓ Diff added: ${filePath}`);
};

// Generate unified diff-like format
window.formatDiff = function(filePath, oldText, newText) {
  const oldLines = (oldText || '').split('\n');
  const newLines = (newText || '').split('\n');
  let diff = `--- ${filePath}\n+++ ${filePath}\n`;

  const maxLen = Math.max(oldLines.length, newLines.length);
  for (let i = 0; i < Math.min(maxLen, 20); i++) {
    if (oldLines[i] !== newLines[i]) {
      if (oldLines[i]) diff += `- ${oldLines[i]}\n`;
      if (newLines[i]) diff += `+ ${newLines[i]}\n`;
    }
  }

  if (maxLen > 20) diff += `\n... (${maxLen - 20} more lines)\n`;
  return diff;
};

// Clear all diffs
window.clearDiffs = function() {
  window.diffCache = {};
  log('✓ Diffs cleared');
};

window.showDiffPreview = function() {
  const diffPanel = document.getElementById('diffPanel');
  if (!diffPanel) {
    // Create diff panel if it doesn't exist
    const panel = document.createElement('div');
    panel.id = 'diffPanel';
    panel.style.cssText = 'position:fixed;top:80px;right:20px;width:400px;max-height:600px;background:#1a1a1a;border:1px solid #444;border-radius:8px;padding:12px;overflow-y:auto;z-index:9999;font-family:monospace;font-size:11px';
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="color:#65ff9b">DIFF PREVIEW</b><button onclick="document.getElementById(\'diffPanel\').style.display=\'none\'" style="background:none;border:none;color:#aaa;cursor:pointer;font-size:14px;padding:0;width:20px;height:20px">×</button></div><div id="diffContent" style="color:#dce5df;line-height:1.4"></div>';
    document.body.appendChild(panel);
  }

  const content = document.getElementById('diffContent');
  if (Object.keys(window.diffCache).length === 0) {
    content.innerHTML = '<div style="color:#888">No diffs added yet</div>';
    document.getElementById('diffPanel').style.display = 'block';
    return;
  }

  let html = '';
  Object.entries(window.diffCache).forEach(([file, diff]) => {
    const oldLines = (diff.old || '').split('\n');
    const newLines = (diff.new || '').split('\n');
    html += `<div style="margin-bottom:12px;border-bottom:1px solid #333;padding-bottom:8px">
      <div style="color:#65ff9b;margin-bottom:4px">📄 ${escapeHtml(file)}</div>
      <div style="font-size:10px;color:#888">-${oldLines.length} +${newLines.length}</div>
      <div style="background:#0d1e12;border:1px solid #2d5e3e;border-radius:4px;padding:6px;margin-top:4px;max-height:120px;overflow-y:auto">
        ${oldLines.slice(0,3).map(l=>`<div style="color:#ff8e8e">−${escapeHtml(l)}</div>`).join('')}
        ${newLines.slice(0,3).map(l=>`<div style="color:#65ff9b">+${escapeHtml(l)}</div>`).join('')}
        ${(oldLines.length > 3 || newLines.length > 3) ? '<div style="color:#888">...</div>' : ''}
      </div>
    </div>`;
  });

  content.innerHTML = html;
  document.getElementById('diffPanel').style.display = 'block';
  log(`✓ Diff preview: ${Object.keys(window.diffCache).length} files`);
};

// ─── Integration: Auto-run AI-generated code on demand ───────────
window.quickExecute = function(codeId) {
  const el = document.getElementById(codeId);
  if (!el) return;
  const code = el.innerText || el.textContent || '';
  if (code && window.executeCode) {
    window.executeCode(code);
  }
};
