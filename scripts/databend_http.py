"""Minimal synchronous HTTP client. No implicit cloud configuration or credentials."""
import base64
import json
import os
import time
import urllib.error
import urllib.request


class Client:
    def __init__(self, url=None, threads=1):
        self.url=(url or os.environ['SM4_URL']).rstrip('/')
        credentials=(os.environ.get('SM4_USER','root')+':'+os.environ.get('SM4_PASSWORD','')).encode()
        self.headers={'Content-Type':'application/json','Authorization':'Basic '+base64.b64encode(credentials).decode()}
        self.threads=threads

    def request(self,path,payload=None,timeout=30):
        req=urllib.request.Request(self.url+path,data=None if payload is None else json.dumps(payload).encode(),headers=self.headers)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode()) from e

    def query(self,sql,timeout=600):
        start=time.monotonic()
        response=self.request('/v1/query',{'sql':sql,'session':{'settings':{
            'max_threads':str(self.threads),'max_block_size':'8192','enable_query_result_cache':'0'}},
            'pagination':{'wait_time_secs':5,'max_rows_in_buffer':10000,'max_rows_per_page':10000}})
        query_id=response['id'];final=response.get('final_uri');kill=response.get('kill_uri')
        rows=[];elapsed=0
        try:
            while True:
                if response.get('error'):raise RuntimeError(f'{query_id}: {response["error"]}')
                rows.extend(response.get('data',[]))
                elapsed=max(elapsed,response.get('stats',{}).get('running_time_ms',0))
                uri=response.get('next_uri')
                if not uri or uri.endswith('/final'):break
                if time.monotonic()-start>timeout:raise TimeoutError(query_id)
                response=self.request(uri)
            return {'query_id':query_id,'server_ms':elapsed,'wall_ms':(time.monotonic()-start)*1000,'data':rows}
        except BaseException:
            if kill:
                try:self.request(kill)
                except Exception:pass
            raise
        finally:
            if final:
                try:self.request(final)
                except Exception:pass

    def upload(self,stage,path):
        boundary='SM4UploadBoundary'
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
              'Content-Type: application/wasm\r\n\r\n').encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        headers={**self.headers,'Content-Type':f'multipart/form-data; boundary={boundary}','x-databend-stage-name':stage}
        req=urllib.request.Request(self.url+'/v1/upload_to_stage',data=body,headers=headers,method='PUT')
        with urllib.request.urlopen(req,timeout=60) as response:result=json.load(response)
        if result.get('state')!='SUCCESS':raise RuntimeError(result)
        return result


def quote(s):
    return "'"+s.replace('\\','\\\\').replace("'","''")+"'"
