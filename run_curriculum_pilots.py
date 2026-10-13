"""Controlled actual-handler pilot, with read-only live curriculum retrieval.

Requires explicit user-approved --approved-budget-usd to call the paid provider.
Account/billing/session/cache services are test adapters: production writes cannot
reach the network. No API retries. Raw provider replies and displayed replies are
both recorded so a rejected generation is not scored as successful teaching.
"""
import argparse
import ast
import asyncio
import functools
import json
import ssl
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'curriculum/audit-2026-10-13'


class ReadQuery:
    def __init__(self,db,path):self.db=db;self.path=path;self.params={}
    def select(self,columns,*_,**__):self.params['select']=columns;return self
    def eq(self,key,value):self.params[key]='eq.'+str(value);return self
    def order(self,key):self.params['order']=key+'.asc';return self
    def range(self,start,end):self.params.update(offset=start,limit=end-start+1);return self
    def limit(self,n):self.params['limit']=n;return self
    def in_(self,key,values):self.params[key]='in.('+','.join(json.dumps(v,ensure_ascii=False) for v in values)+')';return self
    def or_(self,expression):self.params['or']='('+expression+')';return self
    def execute(self):
        start=time.perf_counter()
        response=self.db.client.get(self.db.base+'/'+self.path,params=self.params)
        trace={'path':self.path,'status':response.status_code,'seconds':time.perf_counter()-start}
        self.db.traces.append(trace)
        if response.is_error:
            trace['error_code']=response.json().get('code')
        response.raise_for_status()
        rows=response.json();trace['rows']=len(rows) if isinstance(rows,list) else None
        return SimpleNamespace(data=rows)


class ReadOnlyDB:
    def __init__(self,settings):
        self.base=settings['SUPABASE_URL'].rstrip('/')+'/rest/v1'
        self.client=httpx.Client(verify=ssl.create_default_context(),timeout=45,
            headers={'apikey':settings['SUPABASE_KEY'],'Authorization':'Bearer '+settings['SUPABASE_KEY']})
        self.traces=[]
    def table(self,name):
        if name!='documents':raise ValueError('Only curriculum document reads are permitted')
        return ReadQuery(self,'documents')
    def rpc(self,name,args):
        if name!='match_board_documents':raise ValueError('Only read-only curriculum matching is permitted')
        query=ReadQuery(self,'rpc/'+name)
        query.params={k:json.dumps(v) if isinstance(v,list) else str(v) for k,v in args.items()}
        return query


class BudgetedProvider:
    def __init__(self,key,budget):
        from langchain_deepseek import ChatDeepSeek
        self.model=ChatDeepSeek(model='deepseek-v4-flash',api_key=key,timeout=90,max_retries=0,
                               stream_usage=True,extra_body={'thinking':{'type':'disabled'}},
                               http_client=httpx.Client(verify=ssl.create_default_context()),
                               http_async_client=httpx.AsyncClient(verify=ssl.create_default_context()))
        self.budget=budget;self.reserved=0.;self.calls=[]
    def bind(self,**options):
        owner=self
        class Bound:
            async def astream(self,messages):
                # Bytes conservatively exceed tokens for this tokenizer; include
                # framing allowance. Reserve worst-case cost before sending.
                size=len(json.dumps([{'role':m.type,'content':m.content} for m in messages],ensure_ascii=False).encode())+2048
                output=min(options.get('max_tokens',900),1800)
                cost=(size*.30+output*1.20)/1_000_000
                if size>30000 or len(owner.calls)>=20 or owner.reserved+cost>owner.budget:
                    raise RuntimeError('Pilot budget/input cap reached; no request sent')
                owner.reserved+=cost
                call={'input_byte_bound':size,'output_token_cap':output,'reserved_usd':cost,'generated_answer':'','usage':{},'status':'started'}
                owner.calls.append(call)
                try:
                    async for chunk in owner.model.bind(**dict(options,max_tokens=output)).astream(messages):
                        if chunk.content:call['generated_answer']+=chunk.content
                        if chunk.usage_metadata:call['usage']=chunk.usage_metadata
                        if chunk.response_metadata:call['response_metadata']=chunk.response_metadata
                        yield chunk
                    call['status']='complete'
                except Exception as e:
                    call['status']=type(e).__name__
                    raise
        return Bound()


async def run(budget):
    if (OUT/'real-pilot-results.json').exists():
        raise RuntimeError('Pilot results already exist; refusing automatic paid rerun')
    settings=dotenv_values(ROOT/'.env')
    db=ReadOnlyDB(settings)
    print('Loading cached local embedding model',flush=True)
    import torch
    from huggingface_hub import set_client_factory
    set_client_factory(lambda:httpx.Client(verify=ssl.create_default_context(),follow_redirects=True,timeout=45))
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    model=SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    import textbook_retrieval as retrieval
    env=dict(vars(retrieval),supabase=db,embeddings=SimpleNamespace(embed_query=lambda text:model.encode(text).tolist()),functools=functools,time=time)
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    nodes=[n for n in ast.parse(source).body if getattr(n,'name','') in ('_get_context_cached','get_context')]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/'main.py'),'exec'),env)
    sys.path.insert(0,str(ROOT/'tests'))
    from test_chat_cost_controls import ChatCostTests
    provider=BudgetedProvider(settings['DEEPSEEK_API_KEY'],budget)
    plan=json.loads((OUT/'pilot-plan.json').read_text(encoding='utf-8'))
    results=[];answers={}
    for item in plan['cases']:
        case=ChatCostTests('test_stream_is_bounded_and_actual_usage_is_saved');case.setUp()
        try:
            sessions=case.db.table.return_value
            sessions.select.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'board':item['board'],'grade_level':None,'subject':None}]
            case.db.table.side_effect=lambda name:db.table(name) if name=='documents' else sessions
            contexts=[]
            def get_context(*args,**kwargs):
                begin=time.perf_counter();text=env['get_context'](*args,**kwargs)
                contexts.append({'query':args[0],'text':text,'seconds':time.perf_counter()-begin})
                return text
            case.env.update(get_context=get_context,deepseek_llm=provider,TAMIL_SUBJECTS=retrieval.TAMIL_SUBJECTS)
            history=[]
            if item.get('previous'):
                history=[{'role':'user','content':item['previous']}]
                if item['previous'] in answers:history.append({'role':'assistant','content':answers[item['previous']]})
            request=case.env['ChatRequest'](session_id='00000000-0000-0000-0000-000000000001',
                board=item['board'],grade_level=item['grade'],subject=item['subject'],question=item['question'],history=history)
            start=time.perf_counter();call_start=len(provider.calls);trace_start=len(db.traces)
            response=await case.env['perform_chat'](request,'synthetic-pilot-student')
            answer=''.join([p async for p in response.body_iterator])
            answers[item['question']]=answer
            results.append(dict(item,displayed_answer=answer,answer_source=response.headers.get('x-answer-source'),
                seconds=time.perf_counter()-start,retrieval=contexts,read_requests=db.traces[trace_start:],
                provider_calls=provider.calls[call_start:],evaluation_status='pending source-based review'))
            print(item['id'],response.headers.get('x-answer-source'),round(results[-1]['seconds'],2),'seconds',flush=True)
        finally:case.doCleanups()
        payload={'mode':'Real provider + actual handler/retrieval functions; mocked auth/billing/cache/session adapters. No production writes.',
                 'approved_budget_usd':budget,'reserved_upper_bound_usd':provider.reserved,'provider_call_count':len(provider.calls),'results':results}
        (OUT/'real-pilot-results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    db.client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--approved-budget-usd',type=float,required=True)
    args=parser.parse_args()
    if not 0<args.approved_budget_usd<=.25:parser.error('Budget must be explicitly approved and at most $0.25')
    asyncio.run(run(args.approved_budget_usd))
