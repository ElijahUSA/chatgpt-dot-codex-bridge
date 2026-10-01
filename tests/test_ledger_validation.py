"""Corrupt persisted state must never authorize another effect."""
import copy
import json
import unittest

from test_bridge_packet import bridge, packet, CONTRACT, SOURCE


def queued():
    return bridge.apply_event({'schema_version':1,'requests':{},'operations':{}},
                              packet(),CONTRACT,SOURCE,SOURCE)[0]


def finished(status='complete'):
    state,_=bridge.begin(queued(),'req-0001','owner-one')
    result=packet('result',body={'domain_status':status},request_hash=packet()['payload_sha256'])
    return bridge.finish(state,'req-0001',result,'owner-one',CONTRACT)[0]


class LedgerValidationTests(unittest.TestCase):
    def test_retained_cancellation_cannot_authorize_queued_execution(self):
        direct=bridge.apply_event(queued(),packet('cancel',body={'reason':'stop'},
            request_hash=packet()['payload_sha256']),CONTRACT,SOURCE,SOURCE)[0]
        alias=bridge.apply_event(queued(),packet('cancel',request_id='req-0002',
            body={'reason':'stop'},request_hash='b'*64),CONTRACT,SOURCE,SOURCE)[0]
        alias_only=copy.deepcopy(alias)
        alias_only['requests']['req-0001'].pop('cancel_packet')
        alias_only['requests']['req-0001'].pop('cancellation_requested')
        flag=queued();flag['requests']['req-0001']['cancellation_requested']=True
        alias_flag=bridge.apply_event(queued(),packet(request_id='req-0002'),CONTRACT,SOURCE,SOURCE)[0]
        alias_flag['requests']['req-0002']['cancellation_requested']=True
        for state in (direct,alias,alias_only,flag,alias_flag):
            state['requests']['req-0001']['state']='queued';before=copy.deepcopy(state)
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError,'ledger'):bridge.validate_ledger(state)
                with self.assertRaisesRegex(ValueError,'ledger'):bridge.begin(state,'req-0001','owner-one')
                self.assertEqual(state,before)
                self.assertEqual(state['requests']['req-0001']['executions'],0)
        ordinary=queued();ordinary['requests']['req-0001']['cancellation_requested']=False
        self.assertEqual(bridge.begin(ordinary,'req-0001','owner-one')[1]['action'],'execute_once')
    def test_invalid_cancellation_flag_is_rejected(self):
        for value in (None,'true',1,[]):
            state=queued();state['requests']['req-0001']['cancellation_requested']=value
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,'ledger'):bridge.validate_ledger(state)

    def test_invalid_existing_schema_and_index_never_authorize_effects(self):
        base=finished()
        bad=[]
        for name in ('schema_version','requests','operations'):
            value=copy.deepcopy(base);del value[name];bad.append(value)
        for version in (999,True,'1'):
            value=copy.deepcopy(base);value['schema_version']=version;bad.append(value)
        for index in ({},{'operation-0001':'missing'},{'wrong-key':'req-0001'},[]):
            value=copy.deepcopy(base);value['operations']=index;bad.append(value)
        for value in bad:
            before=copy.deepcopy(value)
            for transition in (
                lambda:bridge.apply_event(value,packet(request_id='req-0002'),CONTRACT,SOURCE,SOURCE),
                lambda:bridge.begin(value,'req-0001','owner-one'),
                lambda:bridge.prepare_send(value,'req-0001','owner-one')):
                with self.subTest(state=value):
                    with self.assertRaisesRegex(ValueError,'ledger'):
                        transition()
            self.assertEqual(value,before)

    def test_bad_record_alias_and_result_correlation_are_rejected(self):
        base=finished();base,_=bridge.apply_event(base,packet(request_id='req-0002'),CONTRACT,SOURCE,SOURCE)
        mutations=(
            lambda s:s['requests'].update({'req-0001':None}),
            lambda s:s['requests']['req-0001'].update(state='unknown'),
            lambda s:s['requests']['req-0001'].update(executions=True),
            lambda s:s['requests']['req-0001'].update(request_sha256='broken'),
            lambda s:s['requests']['req-0002'].update(alias_request_id='missing'),
            lambda s:s['requests']['req-0002'].update(alias_request_id='req-0002'),
            lambda s:s['requests']['req-0002'].update(operation_key='other'),
            lambda s:s['requests']['req-0002'].update(executions=1),
            lambda s:s['requests']['req-0002'].update(owner='another-owner'),
            lambda s:s['operations'].update({'operation-0001':'req-0002'}),
            lambda s:s['requests']['req-0001']['result'].update(request_id='other'),
            lambda s:s['requests']['req-0001'].update(state='partial'),
            lambda s:s['requests']['req-0001'].update(ack=packet('ack',result_hash='b'*64)),
            lambda s:s['requests']['req-0001'].update(delivery={'status':'sent'}),
        )
        for mutation in mutations:
            state=copy.deepcopy(base);mutation(state)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):bridge.validate_ledger(state)

    def test_valid_compatibility_shapes_and_metadata_are_preserved(self):
        shapes=[{'schema_version':1,'requests':{},'operations':{}},queued()]
        active,_=bridge.begin(queued(),'req-0001','owner-one');shapes.append(active)
        uncertain=copy.deepcopy(active);uncertain['requests']['req-0001']['state']='uncertain';shapes.append(uncertain)
        for status in ('complete','partial','uncertain','cancelled','blocked','failed'):
            shapes.append(finished(status))
        cancel=packet('cancel',body={'reason':'stop'},request_hash=packet()['payload_sha256'])
        shapes.append(bridge.apply_event(shapes[0],cancel,CONTRACT,SOURCE,SOURCE)[0])
        alias_cancel=packet('cancel',request_id='req-0002',body={'reason':'stop'},request_hash='b'*64)
        shapes.append(bridge.apply_event(queued(),alias_cancel,CONTRACT,SOURCE,SOURCE)[0])
        alias,_=bridge.apply_event(finished(),packet(request_id='req-0002',body={'objective':'changed wording'}),CONTRACT,SOURCE,SOURCE)
        shapes.append(alias)
        sent=finished();result=sent['requests']['req-0001']['result']
        sent,_=bridge.prepare_send(sent,'req-0001','owner-one');shapes.append(sent)
        for status in ('sent','uncertain'):
            for receipt in ('synthetic receipt',{'source_item':'synthetic-item'}):
                shapes.append(bridge.record_delivery(sent,'req-0001','owner-one',
                    {'status':status,'result_sha256':result['payload_sha256'],'receipt':receipt})[0])
        ack=packet('ack',body={'received':True},request_hash=packet()['payload_sha256'],result_hash=result['payload_sha256'])
        shapes.append(bridge.apply_event(finished(),ack,CONTRACT,SOURCE,SOURCE)[0])
        legacy={'schema_version':1,'requests':{'legacy':{'state':'complete','operation_key':'legacy-operation',
                 'request_sha256':'a'*64,'executions':1,'legacy_completion':True,
                 'verified_outcome':'reviewed completion','receipt_reference':'private evidence reference','note':'imported'}},
                 'operations':{'legacy-operation':'legacy'}}
        shapes.append(legacy)
        for status in ('failed','blocked'):
            shapes.append(bridge.apply_event(finished(status),cancel,CONTRACT,SOURCE,SOURCE)[0])
        for state in shapes:
            state['metadata']={'keep':'unchanged'};before=copy.deepcopy(state)
            bridge.validate_ledger(state)
            self.assertEqual(state,before)
        self.assertEqual(bridge.begin(legacy,'legacy','owner-one')[1]['action'],'reuse_result')
        with self.assertRaises(ValueError):bridge.prepare_send(legacy,'legacy','owner-one')


if __name__=='__main__':unittest.main()
