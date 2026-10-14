#!/usr/bin/python3
import json
import sys
from core import load, Controller, exclusive_lock, run, unit

def main():
    cfg = load()
    c = Controller(cfg)
    args = sys.argv[1:]
    if args == ['status']:
        result = {'profiles':c.status()}
    elif len(args)==2 and args[0]=='logs':
        p = next((p for p in cfg['profiles'] if p['id']==args[1]),None)
        if p is None: raise ValueError('Perfil desconocido')
        result = {'logs':run(['journalctl','-u',unit(p),'-n','100','--no-pager','-o','short-iso'],timeout=10).stdout}
    elif args == ['stop']:
        with exclusive_lock(): c.stop_all()
        result = {'ok':True,'message':'Todas las aplicaciones detenidas'}
    elif len(args)==2 and args[0]=='start':
        with exclusive_lock(): result = c.start(args[1])
    else:
        raise ValueError('Uso: sparkctl status | logs PERFIL | start PERFIL | stop')
    print(json.dumps(result))

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)}))
        sys.exit(1)
