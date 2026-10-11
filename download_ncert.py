import json, urllib.request, time, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
ROOT=args.output;ROOT.mkdir(parents=True,exist_ok=True)
books=json.loads((Path(__file__).parent/'curriculum/ncert_manifest.json').read_text())
out=ROOT/'books';out.mkdir(exist_ok=True)
def fetch(item):
 b,n=item;name=f"{b['code']}{n:02}.pdf";url='https://ncert.nic.in/textbook/pdf/'+name
 p=out/str(b['grade'])/b['code']/name;p.parent.mkdir(parents=True,exist_ok=True)
 for attempt in range(3):
  try:
   data=p.read_bytes() if p.exists() else urllib.request.urlopen(url,timeout=90).read()
   if not data.startswith(b'%PDF-'):raise ValueError('Not a PDF')
   temp=p.with_suffix('.part');temp.write_bytes(data);temp.replace(p)
   return dict(code=b['code'],chapter=n,url=url,path=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
  except Exception as e:
   if attempt==2:return dict(code=b['code'],chapter=n,url=url,error=str(e))
   time.sleep(2*(attempt+1))
items=[(b,n) for b in books for n in (b.get('chapter_ids') or range(1,b['chapters']+1))]
results=[]
with ThreadPoolExecutor(max_workers=8) as pool:
 for f in as_completed([pool.submit(fetch,item) for item in items]):
  r=f.result();results.append(r)
  if 'error' in r:print('FAILED',r,flush=True)
  if len(results)%20==0:print('Downloaded',len(results),'/',len(items),flush=True)
  (ROOT/'ncert-download-report.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('COMPLETE',len(results),'failures',sum('error' in r for r in results),flush=True)
