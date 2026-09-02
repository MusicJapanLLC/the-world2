const $=(s)=>document.querySelector(s);
const STORE='ai-foundry-threads-v1';
const GATEWAY='https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-runtime';
let threads=loadThreads();
let activeId=threads[0]?.id||null;
let busy=false;
const executionTimers=new Map();

function loadThreads(){try{return JSON.parse(localStorage.getItem(STORE)||'[]')}catch{return[]}}
function saveThreads(){localStorage.setItem(STORE,JSON.stringify(threads))}
function uid(){return crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random()}`}
function active(){return threads.find(t=>t.id===activeId)}
function stamp(){return new Date().toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function formatText(text){return String(text).split(/```/).map((p,i)=>i%2?`<pre>${escapeHtml(p.replace(/^\w+\n/,''))}</pre>`:escapeHtml(p)).join('')}
function newThread(){const t={id:uid(),title:'New AI Development',createdAt:Date.now(),updatedAt:Date.now(),messages:[]};threads.unshift(t);activeId=t.id;saveThreads();renderAll(true);return t}
function log(line,type='ok'){const el=$('#terminal');const tag=type==='err'?'ERR':type==='warn'?'WRN':'RUN';el.textContent+=`[${stamp()}] ${tag}  ${line}\n`;el.scrollTop=el.scrollHeight}
function state(sel,value,pass=false){const el=$(sel);el.textContent=value;el.style.color=pass?'#65ff9b':''}
function scrollMessagesToBottom(){requestAnimationFrame(()=>{const box=$('#messages');if(box)box.scrollTop=box.scrollHeight})}

async function postJson(url,payload,credentials='same-origin'){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials,redirect:'follow'});
  const ct=r.headers.get('content-type')||'';
  if(!ct.includes('application/json'))throw new Error(`non-json runtime response (${r.status})`);
  const data=await r.json();
  if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);
  return data;
}
async function direct(action,payload){return postJson('/api/foundry',{action,...payload})}
async function gateway(action,payload){return postJson(GATEWAY,{action,...payload},'omit')}
async function call(action,payload){
  try{
    const r=await direct(action,payload);
    return {...r,route:'GPT-5.6 SOL / VERCEL'};
  }catch(primaryError){
    log(`primary runtime protected/unavailable -> Supabase gateway (${primaryError.message})`,'warn');
    const r=await gateway(action,payload);
    return {...r,route:r.route||'AI FOUNDRY DEEP / SUPABASE'};
  }
}

function renderThreads(){
  const el=$('#threadList');el.innerHTML='';
  threads.forEach(t=>{
    const row=document.createElement('div');row.className=`thread ${t.id===activeId?'active':''}`;
    row.innerHTML=`<div><div class="thread-title">${escapeHtml(t.title)}</div><div class="thread-time">${new Date(t.updatedAt).toLocaleString('ja-JP',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}</div></div><button class="thread-delete">×</button>`;
    row.addEventListener('click',e=>{if(e.target.classList.contains('thread-delete'))return;activeId=t.id;renderAll(true);resumeExecution(t)});
    row.querySelector('.thread-delete').addEventListener('click',e=>{e.stopPropagation();threads=threads.filter(x=>x.id!==t.id);if(activeId===t.id)activeId=threads[0]?.id||null;saveThreads();renderAll(true)});
    el.appendChild(row);
  });
}
function renderMessages(follow=false){
  const t=active();$('#threadTitle').textContent=t?.title||'New AI Development';const box=$('#messages');
  if(!t||!t.messages.length){box.innerHTML='<div class="welcome"><h3>AI FOUNDRY CORE</h3><p>AI開発専用の実行IDE。中央で設計・実装を会話し、実行指示または右の <code>RUN BUILD PIPELINE</code> から GitHub Actions → 実ファイル生成 → Smoke Test → Vercel Deploy → 本番HTTP検証まで進めます。</p></div>';if(follow)scrollMessagesToBottom();return}
  box.innerHTML=t.messages.map(m=>`<article class="message ${m.role} ${m.error?'error':''}"><div class="role">${m.role==='user'?'YOU':'FOUNDRY'}</div><div class="content">${formatText(m.content)}</div></article>`).join('');
  if(follow)scrollMessagesToBottom();
}
function renderAll(follow=false){renderThreads();renderMessages(follow);renderExecution(active())}
function resizeComposer(){const c=$('#composer');c.style.height='auto';c.style.height=Math.min(c.scrollHeight,210)+'px'}

function showArtifact(spec,url){
  $('#artifact').classList.remove('hidden');$('#artifactName').textContent=spec.name||'Generated AI';$('#artifactDescription').textContent=spec.description||'Verified AI FOUNDRY deployment';
  $('#artifactCaps').innerHTML=(spec.capabilities||['VERIFIED DEPLOYMENT']).slice(0,8).map(x=>`<span class="cap">${escapeHtml(x)}</span>`).join('');$('#artifactUrl').href=url;$('#copyUrl').dataset.url=url;
}
function renderExecution(t){
  const ex=t?.execution;
  if(!ex){state('#buildState','IDLE');state('#testState','IDLE');state('#publishState','IDLE');$('#artifact').classList.add('hidden');return}
  const s=ex.status||'queued';
  if(s==='queued'){state('#buildState','QUEUED');state('#testState','WAIT');state('#publishState','WAIT')}
  else if(s==='building'){state('#buildState','RUNNING');state('#testState','WAIT');state('#publishState','WAIT')}
  else if(s==='testing'){state('#buildState','PASS',true);state('#testState','RUNNING');state('#publishState','WAIT')}
  else if(s==='committing'||s==='deploying'){state('#buildState','PASS',true);state('#testState','PASS',true);state('#publishState',s==='committing'?'COMMIT':'DEPLOY')}
  else if(s==='ready'){state('#buildState','PASS',true);state('#testState','PASS',true);state('#publishState','READY',true);if(ex.public_url)showArtifact({name:ex.result?.name||ex.title,description:ex.result?.description||'Verified production deployment',capabilities:ex.result?.capabilities||['GITHUB COMMIT','SMOKE TEST','VERCEL HTTP 200']},ex.public_url)}
  else if(s==='failed'){state('#buildState','FAIL');state('#testState','FAIL');state('#publishState','FAIL');log(`EXECUTION FAILED · ${ex.error||'unknown error'}`,'err')}
}
function trackExecution(t,execution){
  const jobId=execution.jobId||execution.id;t.execution={...execution,jobId,status:execution.status||'queued'};t.updatedAt=Date.now();saveThreads();renderExecution(t);log(`EXECUTION QUEUED · job ${jobId}`);scheduleExecutionPoll(t,1200)
}
function scheduleExecutionPoll(t,delay=7000){
  const jobId=t?.execution?.jobId;if(!jobId||['ready','failed'].includes(t.execution.status))return;
  if(executionTimers.has(jobId))clearTimeout(executionTimers.get(jobId));
  executionTimers.set(jobId,setTimeout(()=>pollExecution(t.id),delay));
}
async function pollExecution(threadId){
  const t=threads.find(x=>x.id===threadId);const jobId=t?.execution?.jobId;if(!t||!jobId)return;
  try{
    const r=await gateway('execution_status',{jobId});const ex=r.execution||{};const previous=t.execution.status;t.execution={...t.execution,...ex,jobId:ex.id||jobId};t.updatedAt=Date.now();saveThreads();
    if(previous!==t.execution.status)log(`EXECUTION ${String(t.execution.status).toUpperCase()} · ${jobId}`);
    if(activeId===threadId)renderExecution(t);
    if(t.execution.status==='ready'){log(`VERIFIED URL · ${t.execution.public_url}`);return}
    if(t.execution.status==='failed'){log(`EXECUTION FAILED · ${t.execution.error||'unknown error'}`,'err');return}
  }catch(e){log(`execution status retry · ${e.message}`,'warn')}
  scheduleExecutionPoll(t,7000)
}
function resumeExecution(t){if(t?.execution&&!['ready','failed'].includes(t.execution.status))scheduleExecutionPoll(t,500)}

async function titleThread(t,first){
  if(t.messages.filter(m=>m.role==='user').length!==1)return;
  try{const r=await call('title',{text:first});t.title=r.title||t.title;t.updatedAt=Date.now();saveThreads();renderThreads();$('#threadTitle').textContent=t.title}catch(e){log(`title generation failed: ${e.message}`,'warn')}
}
async function send(){
  if(busy)return;const c=$('#composer');const text=c.value.trim();if(!text)return;
  const t=active()||newThread();t.messages.push({role:'user',content:text});t.updatedAt=Date.now();saveThreads();c.value='';resizeComposer();renderAll(true);busy=true;$('#sendBtn').disabled=true;log('chat dispatch');titleThread(t,text);
  try{
    const r=await call('chat',{messages:t.messages});t.messages.push({role:'assistant',content:r.text});t.updatedAt=Date.now();if(r.execution)trackExecution(t,r.execution);saveThreads();renderAll(true);log(`chat complete · ${r.route||r.model||'runtime'}`)
  }catch(e){t.messages.push({role:'assistant',content:`RUNTIME ERROR: ${e.message}`,error:true});saveThreads();renderAll(true);log(e.message,'err')}
  finally{busy=false;$('#sendBtn').disabled=false;c.focus();scrollMessagesToBottom()}
}

async function pipeline(){
  if(busy)return;const t=active();if(!t||!t.messages.some(m=>m.role==='user')){log('execution aborted: no development conversation','warn');return}
  if(t.execution&&!['ready','failed'].includes(t.execution.status)){log(`execution already active · ${t.execution.jobId}`,'warn');resumeExecution(t);return}
  busy=true;$('#runPipeline').disabled=true;$('#artifact').classList.add('hidden');state('#buildState','QUEUED');state('#testState','WAIT');state('#publishState','WAIT');log('EXECUTE -> queue real GitHub build');
  try{const r=await gateway('execute',{messages:t.messages});if(!r.execution)throw new Error('execution job was not created');trackExecution(t,r.execution)}
  catch(e){state('#buildState','FAIL');log(`execution queue failed: ${e.message}`,'err')}
  finally{busy=false;$('#runPipeline').disabled=false}
}

$('#newThread').addEventListener('click',newThread);$('#sendBtn').addEventListener('click',send);$('#composer').addEventListener('input',resizeComposer);$('#composer').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});$('#runPipeline').addEventListener('click',pipeline);$('#clearLog').addEventListener('click',()=>{$('#terminal').textContent=''});$('#copyUrl').addEventListener('click',async e=>{const url=e.currentTarget.dataset.url;if(url){await navigator.clipboard.writeText(url);log('URL copied')}});setInterval(()=>{$('#clock').textContent=stamp()},1000);
if(!activeId)newThread();else{renderAll(true);threads.forEach(resumeExecution)}
log('AI FOUNDRY IDE boot');log('chat runtime: DEVELOPMENT-MAX');log('execution lane: GitHub Actions -> verified Vercel URL');
