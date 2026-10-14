import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from core import Controller, exclusive_lock

class Fixture:
    def __init__(self):
        self.profiles=[{'id':'a','name':'A','startup_timeout':1},{'id':'b','name':'B','startup_timeout':1}]
        self.states={'a':'active','b':'inactive'}
        self.events=[]
        self.external=False
        self.failed_stop=False
        self.failed_start=False
        self.raise_start=False
        self.c=Controller({'profiles':self.profiles},self.state,self.health,self.run,self.cleanup,lambda _:None)
    def state(self,p): return {'ActiveState':self.states[p['id']]}
    def health(self,p): return self.external or self.states[p['id']]=='active'
    def cleanup(self,p): self.events.append(('cleanup',p['id']))
    def run(self,args,**kwargs):
        action=args[1]
        pid=args[2].split('@')[1].split('.')[0]
        self.events.append((action,pid))
        if action=='stop':
            if self.failed_stop: raise RuntimeError('stop failed')
            self.states[pid]='inactive'
        if action=='start':
            if self.raise_start: raise RuntimeError('start failed')
            if any(v=='active' for v in self.states.values()): raise AssertionError('Overlap!')
            self.states[pid]='failed' if self.failed_start else 'active'

def lock_task(path, queue):
    with exclusive_lock(path):
        queue.put(('enter',time.monotonic()))
        time.sleep(.1)
        queue.put(('exit',time.monotonic()))

class Tests(unittest.TestCase):
    def test_switch_stops_and_cleans_every_profile_before_start(self):
        f=Fixture(); f.c.start('b')
        self.assertEqual(f.states,{'a':'inactive','b':'active'})
        self.assertLess(f.events.index(('cleanup','b')),f.events.index(('start','b')))
        self.assertLess(f.events.index(('cleanup','a')),f.events.index(('start','b')))
    def test_failed_stop_blocks_start(self):
        f=Fixture(); f.failed_stop=True
        with self.assertRaises(RuntimeError): f.c.start('b')
        self.assertNotIn(('start','b'),f.events)
    def test_outside_service_blocks_start(self):
        f=Fixture(); f.external=True
        with self.assertRaises(RuntimeError): f.c.start('b')
        self.assertNotIn(('start','b'),f.events)
    def test_unknown_profile_has_no_side_effect(self):
        f=Fixture()
        with self.assertRaises(ValueError): f.c.start('../../etc')
        self.assertEqual(f.events,[])
    def test_failed_start_cleans_profile(self):
        f=Fixture(); f.failed_start=True
        with self.assertRaises(RuntimeError): f.c.start('b')
        self.assertEqual(f.events[-2:],[('stop','b'),('cleanup','b')])
    def test_launcher_exception_still_cleans_profile(self):
        f=Fixture(); f.raise_start=True
        with self.assertRaises(RuntimeError): f.c.start('b')
        self.assertEqual(f.events[-2:],[('stop','b'),('cleanup','b')])
    def test_startup_timeout_stops_profile(self):
        f=Fixture(); f.profiles[1]['startup_timeout']=0
        with self.assertRaises(RuntimeError): f.c.start('b')
        self.assertEqual(f.states['b'],'inactive')
        self.assertEqual(f.events[-2:],[('stop','b'),('cleanup','b')])
    def test_status_green_only_ready_active(self):
        f=Fixture(); result=f.c.status()
        self.assertEqual([r['status'] for r in result],['ready','stopped'])
    def test_cross_process_lock_serializes(self):
        with tempfile.TemporaryDirectory() as directory:
            q=multiprocessing.Queue(); path=str(Path(directory)/'lock')
            jobs=[multiprocessing.Process(target=lock_task,args=(path,q)) for _ in range(2)]
            for p in jobs:p.start()
            events=[q.get(timeout=3)[0] for _ in range(4)]
            for p in jobs:p.join(timeout=3)
            self.assertEqual(events,['enter','exit','enter','exit'])

if __name__=='__main__': unittest.main()
