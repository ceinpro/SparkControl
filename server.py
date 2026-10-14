#!/usr/bin/python3
import hmac
import json
import os
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

TOKEN = Path('/etc/spark-control/panel.token').read_text().strip()
PAGE = Path('/opt/spark-control/index.html').read_bytes()
LOCK = threading.Lock()
JOB = {'busy':False,'message':'Preparado','error':'','target':None}
CTL = ['/usr/bin/sudo','-n','/usr/local/bin/sparkctl']

def control(args, timeout=None):
    r = subprocess.run(CTL+args,capture_output=True,text=True,timeout=timeout)
    try: data = json.loads(r.stdout)
    except Exception: raise RuntimeError((r.stderr or r.stdout or 'No se pudo contactar con el controlador')[-2000:])
    if r.returncode: raise RuntimeError(data.get('error','Fallo del controlador'))
    return data

def metrics():
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k,v = line.split(':',1)
        mem[k] = int(v.strip().split()[0])
    gpu = None
    try:
        r = subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
        if r.returncode==0:
            values = r.stdout.strip().splitlines()[0].split(',')
            gpu = {'utilization':int(values[0]),'temperature':int(values[1])}
    except Exception: pass
    return {'memory_total_gib':round(mem['MemTotal']/1048576,1),'memory_available_gib':round(mem['MemAvailable']/1048576,1),'gpu':gpu}

def worker(action, pid):
    try:
        data = control(['start',pid] if action=='start' else ['stop'])
        with LOCK: JOB.update(message=data['message'],error='')
    except Exception as e:
        with LOCK: JOB.update(message='Operación bloqueada o fallida',error=str(e))
    finally:
        with LOCK: JOB.update(busy=False,target=None)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,status,data,ctype='application/json'):
        body = data if isinstance(data,bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def authorized(self):
        if not hmac.compare_digest(self.headers.get('X-Spark-Token',''),TOKEN):
            self.send(401,{'error':'Contraseña incorrecta'})
            return False
        return True
    def do_GET(self):
        if self.path=='/':
            self.send(200,PAGE,'text/html; charset=utf-8')
            return
        if not self.authorized(): return
        try:
            if self.path=='/api/status':
                data = control(['status'],timeout=30)
                with LOCK: data['job'] = dict(JOB)
                data['metrics'] = metrics()
                self.send(200,data)
            elif self.path.startswith('/api/logs/'):
                pid = self.path.removeprefix('/api/logs/')
                self.send(200,control(['logs',pid],timeout=20))
            else: self.send(404,{'error':'Ruta desconocida'})
        except Exception as e: self.send(500,{'error':str(e)})
    def do_POST(self):
        if not self.authorized(): return
        try:
            n = int(self.headers.get('Content-Length','0'))
            if not 0<n<=2048: raise ValueError('Solicitud inválida')
            data = json.loads(self.rfile.read(n))
            action, pid = data.get('action'),data.get('id')
            if self.path!='/api/action' or action not in ('start','stop'): raise ValueError('Acción desconocida')
            if action=='start':
                profiles = control(['status'],timeout=30)['profiles']
                if pid not in [p['id'] for p in profiles]: raise ValueError('Perfil desconocido')
            with LOCK:
                if JOB['busy']:
                    self.send(409,{'error':'Hay un cambio en curso'})
                    return
                JOB.update(busy=True,message='Deteniendo aplicaciones y preparando el cambio…' if action=='start' else 'Deteniendo aplicaciones…',error='',target=pid)
            threading.Thread(target=worker,args=(action,pid),daemon=True).start()
            self.send(202,{'ok':True})
        except Exception as e: self.send(400,{'error':str(e)})

if __name__=='__main__':
    ThreadingHTTPServer((os.environ.get('SPARK_PANEL_HOST','0.0.0.0'),int(os.environ.get('SPARK_PANEL_PORT','8090'))),Handler).serve_forever()
