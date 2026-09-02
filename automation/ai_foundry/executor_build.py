#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,urllib.request
from pathlib import Path

RUNTIME='https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-runtime'

def post(payload:dict)->dict:
    req=urllib.request.Request(RUNTIME,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','User-Agent':'ai-foundry-github-executor/v1'},method='POST')
    with urllib.request.urlopen(req,timeout=120) as res: return json.loads(res.read().decode())

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--payload',required=True); p.add_argument('--out-root',default='public/generated'); p.add_argument('--meta-out',required=True); a=p.parse_args()
    payload=json.loads(Path(a.payload).read_text(encoding='utf-8')); job=payload.get('job') or {}; request=job.get('request') or {}; job_id=str(job.get('id') or '')
    if not job_id: raise RuntimeError('job id missing')
    messages=request.get('messages') if isinstance(request.get('messages'),list) else []
    if not messages:
        messages=[{'role':'user','content':str(request.get('request_text') or 'Build a useful AI assistant.')}]
    built=post({'action':'build','messages':messages}); spec=built.get('spec') or {}
    required=('name','description','systemPrompt','capabilities','starterPrompts')
    if not all(k in spec for k in required): raise RuntimeError('runtime returned invalid AI specification')
    root=Path(a.out_root)/job_id; root.mkdir(parents=True,exist_ok=False)
    title=str(spec['name'])[:100]; desc=str(spec['description'])[:1000]
    index=f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="./styles.css"></head>
<body><main class="shell"><header><div class="kicker">AI FOUNDRY · VERIFIED DEPLOYMENT</div><h1 id="name"></h1><p id="desc"></p></header><section id="messages" class="messages"></section><form id="form" class="composer"><textarea id="input" rows="2" placeholder="Message this AI..." autofocus></textarea><button>SEND</button></form><footer><span>RUNTIME: AI FOUNDRY DEEP</span><span>JOB: {job_id}</span></footer></main><script type="module" src="./app.js"></script></body></html>'''
    styles="""@import url('https://fonts.googleapis.com/css2?family=M+PLUS+1+Code:wght@400;500;600&display=swap');*{box-sizing:border-box}html,body{margin:0;height:100%;background:#030504;color:#dce8df;font-family:'M PLUS 1 Code',Consolas,monospace}.shell{height:100dvh;max-width:1100px;margin:auto;display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;border-left:1px solid #17231b;border-right:1px solid #17231b;background:#060907}header{padding:26px 34px;border-bottom:1px solid #17231b}h1{font-size:20px;margin:7px 0 8px;color:#adffc4}.kicker{font-size:9px;letter-spacing:.18em;color:#62e58a}p{font-size:12px;color:#7f9185;line-height:1.6;margin:0}.messages{overflow:auto;padding:28px 34px}.msg{max-width:850px;margin:0 auto 24px}.role{font-size:9px;letter-spacing:.14em;color:#5e7065;margin-bottom:8px}.content{white-space:pre-wrap;line-height:1.75;font-size:13px}.user .content{color:#aabbb0}.assistant .role{color:#65ff9b}.composer{display:grid;grid-template-columns:1fr 88px;gap:8px;padding:14px 28px;border-top:1px solid #17231b;background:#080d0a}textarea{resize:none;background:#030504;border:1px solid #26392c;color:#e1ebe4;padding:13px;font:inherit;outline:0}textarea:focus{border-color:#65ff9b}button{border:0;background:#65ff9b;color:#041007;font:600 11px 'M PLUS 1 Code',monospace;cursor:pointer}button:disabled{opacity:.45}footer{display:flex;justify-content:space-between;padding:9px 28px;font-size:8px;color:#425148;border-top:1px solid #101812}@media(max-width:650px){header,.messages{padding-left:18px;padding-right:18px}.composer{padding:10px}.composer{grid-template-columns:1fr 70px}}"""
    system_json=json.dumps(str(spec['systemPrompt']),ensure_ascii=False)
    name_json=json.dumps(title,ensure_ascii=False); desc_json=json.dumps(desc,ensure_ascii=False); starters_json=json.dumps(spec.get('starterPrompts') or [],ensure_ascii=False)
    app=f"""const GATEWAY='https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-runtime';const SYSTEM={system_json};const NAME={name_json};const DESC={desc_json};const STARTERS={starters_json};const messages=[];const $=s=>document.querySelector(s);$('#name').textContent=NAME;$('#desc').textContent=DESC;function esc(v){{return String(v).replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#039;'}}[c]))}}function render(){{const box=$('#messages');if(!messages.length){{box.innerHTML='<div class=\"msg assistant\"><div class=\"role\">AI</div><div class=\"content\">'+esc(STARTERS[0]?'Try: '+STARTERS[0]:'Ready.')+'</div></div>';return}}box.innerHTML=messages.map(m=>'<div class=\"msg '+m.role+'\"><div class=\"role\">'+(m.role==='user'?'YOU':'AI')+'</div><div class=\"content\">'+esc(m.content)+'</div></div>').join('');box.scrollTop=box.scrollHeight}}async function send(text){{messages.push({{role:'user',content:text}});render();const btn=$('button');btn.disabled=true;try{{const r=await fetch(GATEWAY,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{action:'runtime',systemPrompt:SYSTEM,messages}})}});const d=await r.json();if(!r.ok)throw new Error(d.error||'runtime failed');messages.push({{role:'assistant',content:d.text||''}})}}catch(e){{messages.push({{role:'assistant',content:'RUNTIME ERROR: '+e.message}})}}finally{{btn.disabled=false;render();$('#input').focus()}}}}$('#form').addEventListener('submit',e=>{{e.preventDefault();const i=$('#input');const text=i.value.trim();if(!text)return;i.value='';send(text)}});$('#input').addEventListener('keydown',e=>{{if(e.key==='Enter'&&!e.shiftKey){{e.preventDefault();$('#form').requestSubmit()}}}});render();"""
    (root/'index.html').write_text(index,encoding='utf-8'); (root/'styles.css').write_text(styles,encoding='utf-8'); (root/'app.js').write_text(app,encoding='utf-8')
    meta={'job_id':job_id,'name':title,'description':desc,'system_prompt':spec['systemPrompt'],'capabilities':spec.get('capabilities') or [],'starter_prompts':spec.get('starterPrompts') or [],'test_prompt':spec.get('testPrompt') or '', 'files':[str(root/'index.html'),str(root/'styles.css'),str(root/'app.js')]}
    (root/'foundry.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); meta['files'].append(str(root/'foundry.json')); Path(a.meta_out).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'job_id':job_id,'name':title,'path':str(root)},ensure_ascii=False)); return 0

if __name__=='__main__': raise SystemExit(main())
