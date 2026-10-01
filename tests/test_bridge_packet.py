import copy, hashlib, importlib.util, json, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bridge_packet.py"
spec = importlib.util.spec_from_file_location("bridge_packet", SCRIPT) if SCRIPT.is_file() else None
bridge = importlib.util.module_from_spec(spec) if spec else None
if spec:
    spec.loader.exec_module(bridge)
CONTRACT = "a" * 64
SOURCE = "verified-az-source"

def packet(kind="request", request_id="req-0001", key="operation-0001", body=None, request_hash=None, result_hash=None):
    payload = json.dumps(body or {"objective":"echo a nonce","nonce":"n-001"}, ensure_ascii=False, separators=(",",":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    p = {"protocol":"az-codex/1","kind":kind,"sender":"codex" if kind=="result" else "az",
         "receiver":"az" if kind=="result" else "codex","request_id":request_id,
         "operation_key":key,"payload":payload,"payload_sha256":digest,
         "request_sha256":request_hash or digest,"contract_sha256":CONTRACT}
    if result_hash is not None:
        p["result_sha256"] = result_hash
    return p

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bridge, "bridge packet/ledger implementation is absent")
        self.state = {"schema_version":1,"requests":{},"operations":{}}
    def apply(self,p,state=None,source=SOURCE):
        return bridge.apply_event(state or self.state,p,CONTRACT,source,SOURCE)
    def test_utf8_hash_preserves_newline_and_unicode(self):
        self.assertEqual(bridge.sha256("你好\r\nx"), hashlib.sha256("你好\r\nx".encode()).hexdigest())
        self.assertNotEqual(bridge.sha256("你好\r\nx"), bridge.sha256("你好\nx"))
    def test_adopted_contract_raw_bytes_are_unchanged(self):
        raw=(ROOT/'references'/'protocol.md').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         'a6a033b18963df6dfcf6f49428ec6d05545642c807f2da775f05a1002e4a62c2')
    def test_fresh_request_is_queued_without_execution(self):
        s,d = self.apply(packet())
        self.assertEqual(d["action"],"queued")
        self.assertEqual(s["requests"]["req-0001"]["executions"],0)
    def test_duplicate_request_reuses_queue(self):
        p=packet();s,_=self.apply(p);s,d=self.apply(p,s)
        self.assertEqual(d["action"],"duplicate")
        self.assertEqual(len(s["requests"]),1)
    def test_same_id_changed_payload_conflicts(self):
        p=packet();s,_=self.apply(p)
        _,d=self.apply(packet(body={"objective":"changed target"}),s)
        self.assertEqual(d["action"],"conflict")
    def test_new_id_same_completed_operation_cannot_reexecute(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete","nonce":"n-001"},request_hash=p["payload_sha256"])
        s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
        s,d=self.apply(packet(request_id="req-0002"),s)
        self.assertEqual(d["action"],"operation_reuse")
        self.assertEqual(s["requests"]["req-0001"]["executions"],1)
    def test_cancel_before_request_remains_cancelled(self):
        p=packet();c=packet("cancel",body={"reason":"cancelled"},request_hash=p["payload_sha256"])
        s,_=self.apply(c);s,d=self.apply(p,s)
        self.assertEqual(d["action"],"cancelled")
        self.assertEqual(s["requests"]["req-0001"]["executions"],0)
    def test_uncertain_execution_never_replays(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        s["requests"]["req-0001"]["state"]="uncertain"
        _,d=bridge.begin(s,"req-0001","owner-two")
        self.assertEqual(d["action"],"reconcile")
        self.assertEqual(s["requests"]["req-0001"]["executions"],1)
    def test_other_owner_cannot_claim_active_request(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        _,d=bridge.begin(s,"req-0001","owner-two")
        self.assertEqual(d["action"],"reconcile")
    def test_ack_is_correlated_and_terminal(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete"},request_hash=p["payload_sha256"])
        s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
        a=packet("ack",body={"received":True},request_hash=p["payload_sha256"],result_hash=r["payload_sha256"])
        s,d=self.apply(a,s)
        self.assertEqual(d["action"],"acknowledged_no_reply")
        _,d=self.apply(a,s)
        self.assertEqual(d["action"],"duplicate_ack_no_reply")
    def test_cancel_after_completion_does_not_imply_rollback(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete"},request_hash=p["payload_sha256"])
        s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
        _,d=self.apply(packet("cancel",body={"reason":"cancel"},request_hash=p["payload_sha256"]),s)
        self.assertEqual(d["action"],"already_complete")
    def test_alias_ack_does_not_certify_canonical_result(self):
        for body in ({'objective':'echo a nonce','nonce':'n-001'}, {'objective':'retry with changed wording'}):
            with self.subTest(body=body):
                p=packet();s,_=self.apply(p);s,_=bridge.begin(s,'req-0001','owner-one')
                r=packet('result',body={'domain_status':'complete'},request_hash=p['payload_sha256'])
                s,_=bridge.finish(s,'req-0001',r,'owner-one',CONTRACT)
                alias=packet(request_id='req-0002',body=body);s,_=self.apply(alias,s)
                a=packet('ack',request_id='req-0002',body={'received':True},
                         request_hash=alias['payload_sha256'],result_hash=r['payload_sha256'])
                s,d=self.apply(a,s)
                self.assertEqual(d['action'],'unmatched_ack_no_reply')
                self.assertNotIn('ack',s['requests']['req-0001'])
                canonical_ack=packet('ack',body={'received':True},request_hash=p['payload_sha256'],
                                     result_hash=r['payload_sha256'])
                s,d=self.apply(canonical_ack,s)
                self.assertEqual(d['action'],'acknowledged_no_reply')
                self.assertEqual(s['requests']['req-0001']['ack'],canonical_ack)
                self.assertEqual(s['requests']['req-0001']['executions'],1)
    def test_alias_id_with_canonical_hash_conflicts(self):
        p=packet();s,_=self.apply(p)
        alias=packet(request_id='req-0002',body={'objective':'changed wording'});s,_=self.apply(alias,s)
        a=packet('ack',request_id='req-0002',body={'received':True},
                 request_hash=p['payload_sha256'],result_hash='b'*64)
        s,d=self.apply(a,s)
        self.assertEqual(d['action'],'conflict')
        self.assertNotIn('ack',s['requests']['req-0001'])
    def test_cancel_before_request_suppresses_later_operation_alias(self):
        p=packet();c=packet('cancel',body={'reason':'cancel'},request_hash=p['payload_sha256'])
        s,_=self.apply(c)
        alias=packet(request_id='req-0002');s,_=self.apply(alias,s)
        s,d=bridge.begin(s,'req-0002','owner-one')
        self.assertEqual(d['action'],'reconcile')
        self.assertEqual(s['requests']['req-0001']['state'],'cancelled')
        self.assertEqual(s['requests']['req-0001']['executions'],0)
        self.assertEqual(s['requests']['req-0002']['executions'],0)
    def test_bad_hash_source_and_version_rejected(self):
        for mutation in ("hash","source","version"):
            p=packet()
            if mutation=="hash":p["payload_sha256"]="f"*64
            if mutation=="version":p["protocol"]="az-codex/2"
            with self.assertRaises(ValueError):
                self.apply(p,source="untrusted" if mutation=="source" else SOURCE)
    def test_result_requires_matching_claim_and_request_hash(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete"},request_hash="b"*64)
        with self.assertRaises(ValueError):
            bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)

    def test_alias_cancellation_suppresses_canonical_queue(self):
        p=packet();s,_=self.apply(p);s,_=self.apply(packet(request_id="req-0002"),s)
        c=packet("cancel",request_id="req-0002",body={"reason":"cancel"},request_hash=p["payload_sha256"])
        s,_=self.apply(c,s);s,d=bridge.begin(s,"req-0001","owner-one")
        self.assertEqual(d["action"],"reconcile")
        self.assertEqual(s["requests"]["req-0001"]["state"],"cancelled")
        self.assertEqual(s["requests"]["req-0001"]["executions"],0)

    def test_alias_replay_reads_current_canonical_outcome(self):
        for status in ("complete","uncertain"):
            p=packet();s,_=self.apply(p);alias=packet(request_id="req-0002");s,_=self.apply(alias,s)
            s,_=bridge.begin(s,"req-0001","owner-one")
            r=packet("result",body={"domain_status":status},request_hash=p["payload_sha256"])
            s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
            _,d=self.apply(alias,s)
            self.assertEqual(d["state"],status);self.assertEqual(d["result"],r)
            _,d=bridge.begin(s,"req-0002","owner-two")
            self.assertEqual(d["action"],"reuse_result" if status=="complete" else "reconcile")

    def test_alias_cancel_marks_active_canonical_for_reconciliation(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        s,_=self.apply(packet(request_id="req-0002"),s)
        c=packet("cancel",request_id="req-0002",body={"reason":"cancel"},request_hash=p["payload_sha256"])
        s,d=self.apply(c,s)
        self.assertEqual(d["action"],"reconcile_cancellation")
        self.assertTrue(s["requests"]["req-0001"]["cancellation_requested"])
    def test_first_seen_alias_cancellation_resolves_existing_operation(self):
        for status in ('queued','executing','uncertain','partial','complete'):
            with self.subTest(status=status):
                p=packet();s,_=self.apply(p)
                if status!='queued':
                    s,_=bridge.begin(s,'req-0001','owner-one')
                if status in ('uncertain','partial','complete'):
                    r=packet('result',body={'domain_status':status},request_hash=p['payload_sha256'])
                    s,_=bridge.finish(s,'req-0001',r,'owner-one',CONTRACT)
                c=packet('cancel',request_id='req-0002',body={'reason':'cancel alias'},
                         request_hash=packet(request_id='req-0002',body={'objective':'retry'})['payload_sha256'])
                s,d=self.apply(c,s)
                original=s['requests']['req-0001']
                self.assertEqual(s['requests']['req-0002']['alias_request_id'],'req-0001')
                self.assertEqual(s['operations']['operation-0001'],'req-0001')
                if status=='queued':
                    self.assertEqual(original['state'],'cancelled')
                    s,start=bridge.begin(s,'req-0001','owner-one')
                    self.assertEqual(start['action'],'reconcile')
                    self.assertEqual(original['executions'],0)
                elif status=='complete':
                    self.assertEqual(d['action'],'already_complete')
                    self.assertEqual(d['result'],r)
                    self.assertEqual(original['state'],'complete')
                else:
                    self.assertEqual(d['action'],'reconcile_cancellation')
                    self.assertTrue(original['cancellation_requested'])
                    self.assertEqual(original['state'],status)
    def test_acknowledged_result_never_receives_new_send_permission(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,'req-0001','owner-one')
        r=packet('result',body={'domain_status':'complete'},request_hash=p['payload_sha256'])
        s,_=bridge.finish(s,'req-0001',r,'owner-one',CONTRACT)
        a=packet('ack',body={'received':True},request_hash=p['payload_sha256'],result_hash=r['payload_sha256'])
        s,_=self.apply(a,s)
        s,d=bridge.prepare_send(s,'req-0001','owner-one')
        self.assertEqual(d['action'],'acknowledged_no_send')
        self.assertNotIn('delivery',s['requests']['req-0001'])
    def test_null_ack_result_hash_is_structured_validation_error(self):
        a=packet('ack');a['result_sha256']=None
        with self.assertRaises(ValueError): bridge.validate(a,CONTRACT)

    def test_result_send_claim_and_receipt_survive_retries(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete"},request_hash=p["payload_sha256"])
        s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
        s,d=bridge.prepare_send(s,"req-0001","owner-one")
        self.assertEqual(d["action"],"send_once")
        _,d=bridge.prepare_send(s,"req-0001","owner-one")
        self.assertEqual(d["action"],"reconcile_send")
        receipt={"status":"uncertain","result_sha256":r["payload_sha256"],"receipt":"tool interrupted"}
        s,_=bridge.record_delivery(s,"req-0001","owner-one",receipt)
        _,d=bridge.prepare_send(s,"req-0001","owner-one")
        self.assertEqual(d["action"],"reconcile_send")
        receipt.update(status="sent",receipt="verified destination item")
        s,_=bridge.record_delivery(s,"req-0001","owner-one",receipt)
        _,d=bridge.prepare_send(s,"req-0001","owner-one")
        self.assertEqual(d["action"],"reuse_send_receipt")
        self.assertEqual(s["requests"]["req-0001"]["delivery"]["attempts"],1)

    def test_result_send_rejects_wrong_owner_or_hash(self):
        p=packet();s,_=self.apply(p);s,_=bridge.begin(s,"req-0001","owner-one")
        r=packet("result",body={"domain_status":"complete"},request_hash=p["payload_sha256"])
        s,_=bridge.finish(s,"req-0001",r,"owner-one",CONTRACT)
        with self.assertRaises(ValueError):bridge.prepare_send(s,"req-0001","owner-two")
        s,_=bridge.prepare_send(s,"req-0001","owner-one")
        with self.assertRaises(ValueError):
            bridge.record_delivery(s,"req-0001","owner-one",{"status":"sent","result_sha256":"f"*64,"receipt":"wrong"})

if __name__=="__main__":
    unittest.main()

