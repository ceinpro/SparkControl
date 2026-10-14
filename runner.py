#!/usr/bin/python3
"""Service owner; optional real terminal for existing interactive launchers."""
import errno
import fcntl
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import time
from core import load, cleanup

def run_profile(p):
    env=os.environ.copy()
    env.update(p.get('env',{}))
    child=None
    stopping=False
    master=None
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
        if child is not None and child.poll() is None: child.terminate()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    if p.get('tty',False):
        master,slave=pty.openpty()
        def terminal():
            os.setsid()
            fcntl.ioctl(slave,termios.TIOCSCTTY,0)
        child=subprocess.Popen(p['command'],cwd=p['cwd'],env=env,stdin=slave,stdout=slave,stderr=slave,preexec_fn=terminal)
        os.close(slave)
    else:
        child=subprocess.Popen(p['command'],cwd=p['cwd'],env=env)
    def output():
        nonlocal master
        if master is None:
            time.sleep(.2)
            return
        if select.select([master],[],[],.2)[0]:
            try:
                data=os.read(master,65536)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                else:
                    os.close(master); master=None
            except OSError as e:
                if e.errno != errno.EIO: raise
                os.close(master); master=None
    try:
        while child.poll() is None and not stopping: output()
        if stopping:
            try: child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
            return 0
        # Drain terminal output already queued, including the final error lines.
        if master is not None:
            while select.select([master],[],[],0)[0]:
                output()
                if master is None: break
        if child.returncode==0 and p.get('detached',False):
            while not stopping: time.sleep(1)
            return 0
        return child.returncode if child.returncode else 1
    finally:
        if master is not None: os.close(master)

def main():
    p=next(p for p in load()['profiles'] if p['id']==sys.argv[-1])
    if '--cleanup' in sys.argv:
        cleanup(p)
        return 0
    return run_profile(p)

if __name__=='__main__': sys.exit(main())
