#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,urllib.parse,urllib.request
from pathlib import Path
from typing import Any

AUDIENCE='ai-foundry-executor'
EDGE_URL='https://czwdtjgunsafcifjhpwt.supabase.co/functions/v1/ai-foundry-executor-gateway'

def oidc()->str:
    url=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL','').strip(); token=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN','').strip()
    if not url or not token: raise RuntimeError('GitHub OIDC environment unavailable')
    sep='&' if '?' in url else '?'
    req=urllib.request.Request(url+sep+urllib.parse.urlencode({'audience':AUDIENCE}),headers={'Authorization':f'Bearer {token}','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as res: data=json.loads(res.read().decode())
    value=str(data.get('value') or '')
    if not value: raise RuntimeError('OIDC response had no token')
    return value

def edge(payload:dict[str,Any])->dict[str,Any]:
    req=urllib.request.Request(EDGE_URL,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':f'Bearer {oidc()}','Content-Type':'application/json','User-Agent':'ai-foundry-executor/v1'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=30) as res: return json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        body=exc.read().decode(errors='replace')[:2000]; raise RuntimeError(f'executor gateway HTTP {exc.code}: {body}') from exc

def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('claim'); q.add_argument('--task-id',default=''); q.add_argument('--out',required=True)
    q=sub.add_parser('status'); q.add_argument('--job-id',required=True); q.add_argument('--status',required=True); q.add_argument('--public-url',default=''); q.add_argument('--result',default='')
    q=sub.add_parser('finish'); q.add_argument('--job-id',required=True); q.add_argument('--success',action='store_true'); q.add_argument('--public-url',default=''); q.add_argument('--result',default=''); q.add_argument('--error',default='')
    a=p.parse_args()
    if a.cmd=='claim':
        d=edge({'action':'claim','task_id':a.task_id}); Path(a.out).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print('NO_JOB' if not d.get('job') else f"CLAIM {d['job']['id']}"); return 0
    result={}
    if getattr(a,'result',''):
        result=json.loads(Path(a.result).read_text(encoding='utf-8'))
    if a.cmd=='status':
        d=edge({'action':'status','job_id':a.job_id,'status':a.status,'public_url':a.public_url,'result':result}); print(json.dumps(d,ensure_ascii=False)); return 0
    d=edge({'action':'finish','job_id':a.job_id,'success':bool(a.success),'public_url':a.public_url,'result':result,'error':a.error}); print(json.dumps(d,ensure_ascii=False)); return 0 if d.get('finished') else 1

if __name__=='__main__': raise SystemExit(main())
