import importlib.util, io, json, os, pathlib, re, stat, subprocess, sys, tempfile, unittest
from unittest.mock import patch
from test_bridge_packet import bridge, packet, CONTRACT, SOURCE
SCRIPT=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'bridge_packet.py'
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
        self.ledger=self.root/'ledger.json';self.incoming=self.root/'packet.json';self.incoming.write_text(json.dumps(packet()),encoding='utf-8')
    def cli(self,action,*args,success=True):
        command=[sys.executable,str(SCRIPT),action,'--ledger',str(self.ledger),*args]
        p=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(p.returncode,0 if success else 2,p.stderr)
        return json.loads(p.stdout if success else p.stderr)
    def enqueue(self):
        self.cli('event','--packet',str(self.incoming),'--contract',CONTRACT,'--source-thread',SOURCE,'--expected-source',SOURCE)
    def test_new_process_replay_uses_claim_and_sent_receipt(self):
        self.enqueue();args=('--request-id','req-0001','--owner','example-owner')
        self.assertEqual(self.cli('begin',*args)['action'],'execute_once')
        self.assertEqual(self.cli('begin',*args)['action'],'reconcile')
        p=packet();result=packet('result',body={'domain_status':'complete'},request_hash=p['payload_sha256'])
        output=self.root/'result.json';output.write_text(json.dumps(result),encoding='utf-8')
        self.cli('finish',*args,'--packet',str(output),'--contract',CONTRACT)
        self.assertEqual(self.cli('prepare_send',*args)['action'],'send_once')
        self.assertEqual(self.cli('prepare_send',*args)['action'],'reconcile_send')
        receipt=self.root/'receipt.json';receipt.write_text(json.dumps({'status':'sent','result_sha256':result['payload_sha256'],'receipt':'synthetic verified destination'}),encoding='utf-8')
        self.cli('delivery',*args,'--packet',str(receipt))
        self.assertEqual(self.cli('prepare_send',*args)['action'],'reuse_send_receipt')
        self.assertEqual(self.cli('begin',*args)['action'],'reuse_result')
        state=json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertEqual(state['requests']['req-0001']['executions'],1)
        self.assertEqual(state['requests']['req-0001']['delivery']['attempts'],1)
    def test_existing_lock_preserves_bytes_and_is_not_deleted(self):
        self.enqueue();before=self.ledger.read_bytes();lock=self.ledger.with_name('ledger.json.lock');lock.write_text('synthetic orphan lock')
        error=self.cli('begin','--request-id','req-0001','--owner','other-owner',success=False)
        self.assertIn('locked',error['error']);self.assertEqual(self.ledger.read_bytes(),before);self.assertTrue(lock.exists())
    def test_invalid_existing_ledger_is_held_without_rewriting_bytes(self):
        for state in ({}, {'schema_version':999,'requests':{},'operations':{}},
                      {'schema_version':1,'requests':{'retained':{}},'operations':{}}):
            self.ledger.write_bytes(('  '+json.dumps(state)+'\n').encode())
            before=self.ledger.read_bytes()
            error=self.cli('event','--packet',str(self.incoming),'--contract',CONTRACT,
                           '--source-thread',SOURCE,'--expected-source',SOURCE,success=False)
            self.assertIn('ledger',error['error']);self.assertEqual(self.ledger.read_bytes(),before)
            self.assertFalse(self.ledger.with_name('ledger.json.lock').exists())
            self.assertEqual(list(self.root.glob('*.tmp')),[])
    def test_replace_failure_preserves_original_bytes(self):
        self.enqueue();before=self.ledger.read_bytes()
        with patch.object(bridge,'replace_state_file',side_effect=OSError('synthetic replacement failure')):
            with self.assertRaises(OSError): bridge.write_json(self.ledger,{'changed':True})
        self.assertEqual(self.ledger.read_bytes(),before);self.assertEqual(list(self.root.glob('*.tmp')),[])
    def test_queued_cancellation_contradictions_hold_without_rewriting_bytes(self):
        self.enqueue();queued=json.loads(self.ledger.read_text(encoding='utf-8'))
        fixtures=[]
        for rid,digest in (('req-0001',packet()['payload_sha256']),('req-0002','b'*64)):
            cancelled=bridge.apply_event(queued,packet('cancel',request_id=rid,
                body={'reason':'stop'},request_hash=digest),CONTRACT,SOURCE,SOURCE)[0]
            cancelled['requests']['req-0001']['state']='queued';fixtures.append(cancelled)
        flag=json.loads(json.dumps(queued));flag['requests']['req-0001']['cancellation_requested']=True;fixtures.append(flag)
        for state in fixtures:
            self.ledger.write_bytes(('  '+json.dumps(state)+'\n').encode());before=self.ledger.read_bytes()
            error=self.cli('begin','--request-id','req-0001','--owner','owner-one',success=False)
            self.assertIn('ledger',error['error']);self.assertEqual(self.ledger.read_bytes(),before)
            self.assertEqual(json.loads(self.ledger.read_bytes())['requests']['req-0001']['executions'],0)
            self.assertFalse(self.ledger.with_name('ledger.json.lock').exists())
    def test_temp_and_lock_creation_request_private_permissions(self):
        actual_open=bridge.os.open;calls=[]
        def checked_open(path,flags,mode=0o777,*args,**kwargs):
            calls.append((str(path),mode))
            return actual_open(path,flags,mode,*args,**kwargs)
        with patch.object(bridge.os,'open',side_effect=checked_open):
            bridge.write_json(self.ledger,{'private':'synthetic'})
        self.assertTrue(calls);self.assertTrue(all(mode==0o600 for _,mode in calls))
    @unittest.skipUnless(os.name=='posix','POSIX permission semantics')
    def test_posix_new_and_existing_modes_survive_permissive_umask(self):
        previous=os.umask(0)
        try:
            bridge.write_json(self.ledger,{'version':1})
            self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode),0o600)
            for mode in (0o600,0o400):
                self.ledger.chmod(mode);bridge.write_json(self.ledger,{'version':2})
                self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode),mode)
        finally:os.umask(previous)
    def test_windows_acl_error_has_no_replace_fallback(self):
        self.ledger.write_text('synthetic original',encoding='utf-8')
        with patch.object(bridge,'replace_windows_file',side_effect=OSError('synthetic ACL merge failure')) as native:
            with patch.object(bridge.os,'name','nt'),patch.object(bridge.os,'replace') as fallback:
                with self.assertRaises(OSError):bridge.replace_state_file(self.incoming,self.ledger)
        native.assert_called_once();fallback.assert_not_called()
    def test_failed_cli_write_retains_owned_lock_until_reconciled(self):
        self.enqueue();before=self.ledger.read_bytes()
        command=['bridge_packet.py','begin','--ledger',str(self.ledger),
                 '--request-id','req-0001','--owner','owner-one']
        with patch.object(sys,'argv',command),patch('sys.stdout',new_callable=io.StringIO):
            with patch.object(bridge,'write_json',side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):bridge.main()
        self.assertEqual(self.ledger.read_bytes(),before)
        self.assertTrue(self.ledger.with_name('ledger.json.lock').exists())
    @unittest.skipUnless(os.name=='nt','Windows native replacement integration')
    def test_windows_replacement_retains_dacl_grants_and_protection(self):
        bridge.write_json(self.ledger,{'version':1})
        def dacl():
            import ctypes
            from ctypes import wintypes
            security=ctypes.WinDLL('advapi32',use_last_error=True)
            get=security.GetFileSecurityW
            get.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD))
            get.restype=wintypes.BOOL
            size=wintypes.DWORD();get(str(self.ledger),4,None,0,ctypes.byref(size))
            self.assertGreater(size.value,0)
            descriptor=ctypes.create_string_buffer(size.value)
            self.assertTrue(get(str(self.ledger),4,descriptor,size.value,ctypes.byref(size)))
            convert=security.ConvertSecurityDescriptorToStringSecurityDescriptorW
            convert.argtypes=(wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,
                              ctypes.POINTER(wintypes.LPWSTR),ctypes.POINTER(wintypes.DWORD))
            convert.restype=wintypes.BOOL
            text=wintypes.LPWSTR()
            self.assertTrue(convert(descriptor,1,4,ctypes.byref(text),None))
            try:return text.value
            finally:
                free=ctypes.WinDLL('kernel32').LocalFree
                free.argtypes=(wintypes.LPVOID,);free.restype=wintypes.LPVOID
                free(ctypes.cast(text,wintypes.LPVOID))
        before=dacl();self.assertTrue(before)
        bridge.write_json(self.ledger,{'version':2})
        def permissions(sddl):
            # ReplaceFileW may normalize inherited-ACE metadata. Compare grants,
            # deny entries, propagation flags and DACL protection, not byte layout.
            header=sddl.split('(',1)[0].replace('AI','')
            entries=re.findall(r'\(([^;]+);([^;]*);([^)]*)\)',sddl)
            return header,[(kind,flags.replace('ID',''),rest) for kind,flags,rest in entries]
        self.assertEqual(permissions(dacl()),permissions(before))
        self.assertEqual(json.loads(self.ledger.read_text())['version'],2)
        self.assertEqual(list(self.root.glob('*.recovery')),[])
if __name__=='__main__':unittest.main()
