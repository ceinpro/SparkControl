"""Controller: fixed root-owned catalog, serialized transitions, fail closed."""
import fcntl
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.error
from contextlib import contextmanager

CATALOG = '/etc/spark-control/catalog.json'

def load(path=CATALOG):
    with open(path) as f:
        cfg = json.load(f)
    ids = set()
    for p in cfg['profiles']:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', p['id']) or p['id'] in ids:
            raise ValueError('Identificador inválido o duplicado')
        ids.add(p['id'])
        if not isinstance(p['command'], list) or not p['command'] or not all(isinstance(x,str) for x in p['command']):
            raise ValueError('command debe ser una lista de argumentos')
        if not os.path.isabs(p['cwd']):
            raise ValueError('cwd debe ser absoluto')
        if not p['health']['url'].startswith(('http://127.0.0.1:', 'http://localhost:')):
            raise ValueError('La comprobación debe ser local')
    return cfg

def run(args, check=True, timeout=90):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError((p.stderr or p.stdout or 'Error de comando')[-3000:])
    return p

def unit(p):
    return 'spark-app@' + p['id'] + '.service'

def health(p):
    h = p['health']
    try:
        req = urllib.request.Request(h['url'], headers=h.get('headers', {}))
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status in h.get('statuses', [200])
    except urllib.error.HTTPError as e:
        return e.code in h.get('statuses', [200])
    except Exception:
        return False

def state(p):
    r = run(['systemctl','show',unit(p), '--property=ActiveState,SubState,ActiveEnterTimestamp'], check=False, timeout=5)
    props = dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    return props

def cleanup(p):
    # Only explicitly configured containers; never stop unrelated Docker workloads.
    for name in p.get('containers', []):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name):
            raise ValueError('Nombre de contenedor inválido')
        probe = run(['docker','inspect','--format={{.State.Running}}',name],check=False,timeout=10)
        if probe.returncode == 0 and probe.stdout.strip() == 'true':
            run(['docker','stop','--time','30',name],timeout=45)

class Controller:
    def __init__(self, cfg, state_fn=state, health_fn=health, run_fn=run, cleanup_fn=cleanup, sleep_fn=time.sleep):
        self.cfg, self.state, self.health = cfg, state_fn, health_fn
        self.run, self.cleanup, self.sleep = run_fn, cleanup_fn, sleep_fn

    def stop_all(self):
        for p in self.cfg['profiles']:
            self.run(['systemctl','stop',unit(p)], timeout=120)
            self.cleanup(p)
        for p in self.cfg['profiles']:
            if self.state(p).get('ActiveState') not in ('inactive','failed'):
                raise RuntimeError('No se ha detenido: ' + p['name'])
        # Detect manual/outside-systemd services. Shared endpoint profiles are checked once.
        for p in self.cfg['profiles']:
            if self.health(p):
                raise RuntimeError('Sigue respondiendo ' + p['name'] + '. Detén su arranque manual antes de continuar.')

    def start(self, pid):
        p = next((p for p in self.cfg['profiles'] if p['id']==pid),None)
        if p is None:
            raise ValueError('Perfil desconocido')
        self.stop_all()
        self.run(['systemctl','reset-failed',unit(p)],check=False)
        try:
            self.run(['systemctl','start',unit(p)])
            deadline = time.monotonic() + p.get('startup_timeout',900)
            while time.monotonic() < deadline:
                current = self.state(p).get('ActiveState')
                if current in ('failed','inactive'):
                    raise RuntimeError('El arranque ha terminado con error. Consulta los registros de ' + p['name'])
                if current == 'active' and self.health(p):
                    return {'ok':True,'message':p['name']+' está listo'}
                self.sleep(2)
            raise RuntimeError('Se agotó el tiempo de arranque; el perfil se ha detenido.')
        except Exception as cause:
            try:
                self.run(['systemctl','stop',unit(p)])
                self.cleanup(p)
            except Exception as stop_error:
                raise RuntimeError(str(cause) + ' Además, la limpieza ha fallado: ' + str(stop_error)) from cause
            raise

    def status(self):
        rows = []
        for p in self.cfg['profiles']:
            s = self.state(p)
            active = s.get('ActiveState')
            ready = active == 'active' and self.health(p)
            status = 'ready' if ready else 'starting' if active in ('activating','active') else 'stopping' if active == 'deactivating' else 'error' if active == 'failed' else 'stopped'
            rows.append({'id':p['id'],'name':p['name'],'app':p.get('app',''),'description':p.get('description',''), 'port':p.get('port'), 'status':status,'since':s.get('ActiveEnterTimestamp','')})
        return rows

@contextmanager
def exclusive_lock(path='/run/lock/spark-control.lock'):
    with open(path,'a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield
        fcntl.flock(f,fcntl.LOCK_UN)
