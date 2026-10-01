import copy, importlib.util, json, pathlib, subprocess, sys, tempfile, unittest
from test_bridge_packet import bridge, packet, CONTRACT
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_batch', ROOT/'scripts'/'source_batch.py')
source = importlib.util.module_from_spec(spec) if spec else None
if spec and (ROOT/'scripts'/'source_batch.py').is_file(): spec.loader.exec_module(source)
SOURCE = 'example-source'
def item(identifier, text='ordinary text', kind='mcpToolCall', status='completed'):
    return {'id':identifier,'type':kind,'server':'codex_apps','tool':'user_message.send_message','status':status,'arguments':{'text':text}}
def page(items, more=False, cursor=None, requested=None):
    return {'requestedCursor':requested,'thread':{'id':SOURCE},'page':{'order':'newest_first','hasMore':more,'nextCursor':cursor},
            'turns':[{'id':'example-turn','status':'completed','items':items}]}
def designated(kind='request'): return 'AZ_BRIDGE_V1 '+json.dumps({'kind':kind})
class SourceTests(unittest.TestCase):
    def scan(self,pages,boundary='known',limit=6): return source.scan_pages(pages,SOURCE,boundary,limit)
    def test_missing_boundary_holds_candidates_and_cursor(self):
        result=self.scan([page([item('new',designated())],True,'older')])
        self.assertFalse(result['complete_coverage']); self.assertEqual(result['continuation'],'older')
        self.assertEqual(len(result['candidates']),1); self.assertEqual(result['boundary'],'known')
    def test_complete_coverage_returns_chronological_events(self):
        result=self.scan([page([item('known'),item('request',designated()),item('cancel',designated('cancel'))])])
        self.assertTrue(result['complete_coverage']); self.assertEqual(result['initial_newest'],'cancel')
        self.assertEqual([x['packet']['kind'] for x in result['candidates']],['request','cancel'])
    def test_newest_turns_and_oldest_items_return_chronological_events(self):
        older=page([item('known'),item('request',designated()),item('ordinary')])['turns'][0]
        newer=page([item('cancel',designated('cancel')),item('ack',designated('ack'))])['turns'][0]
        fixture=page([]);fixture['turns']=[newer,older]
        result=self.scan([fixture])
        self.assertTrue(result['complete_coverage'])
        self.assertEqual(result['initial_newest'],'ack')
        self.assertEqual([x['source_item_id'] for x in result['candidates']],['request','cancel','ack'])
    def test_echo_and_unfinished_output_are_not_packets(self):
        echo={'id':'echo','type':'userMessage','content':[{'type':'text','text':designated()}]}
        result=self.scan([page([item('known'),echo,item('unfinished',designated(),status='inProgress')])])
        self.assertEqual(result['candidates'],[])
        self.assertFalse(result['complete_coverage'])
    def test_truncated_packet_holds_covered_batch(self):
        result=self.scan([page([item('known'),item('bad','AZ_BRIDGE_V1 {')])])
        self.assertFalse(result['complete_coverage']); self.assertTrue(result['issues'])
        self.assertEqual(result['boundary'],'known')
    def test_wrong_registered_source_is_rejected(self):
        p=page([item('known')]);p['thread']['id']='different-source'
        with self.assertRaises(ValueError): self.scan([p])
    def test_unfinished_assistant_output_holds_until_same_item_completes(self):
        for kind in ('agentMessage','assistantMessage'):
            p=page([item('known'),{'id':'pending','type':kind,'text':designated()}])
            p['turns'][0]['status']='inProgress'
            result=self.scan([p]);self.assertFalse(result['complete_coverage'])
            self.assertEqual(result['boundary'],'known')
            p['turns'][0]['status']='completed'
            result=self.scan([p]);self.assertTrue(result['complete_coverage'])
            self.assertEqual(result['candidates'][0]['source_item_id'],'pending')
    def test_boundary_beyond_cap_remains_an_explicit_hold(self):
        pages=[]
        for index in range(7):
            pages.append(page([item('known' if index==6 else 'item-'+str(index))],index<6,
                              'cursor-'+str(index+1) if index<6 else None,
                              None if index==0 else 'cursor-'+str(index)))
        result=self.scan(pages);self.assertFalse(result['complete_coverage'])
        self.assertEqual(result['pages'],6);self.assertEqual(result['continuation'],'cursor-6')
    def test_page_cap_preserves_resume_cursor(self):
        result=self.scan([page([item('new')],True,'older')],limit=1)
        self.assertFalse(result['complete_coverage']);self.assertEqual(result['continuation'],'older')
    def test_multiple_pages_find_boundary_without_old_events(self):
        result=self.scan([page([item('new',designated())],True,'older'),page([item('ancient',designated()),item('known')],requested='older')])
        self.assertTrue(result['complete_coverage']);self.assertEqual(len(result['candidates']),1)
    def test_skipped_page_holds_even_when_later_boundary_exists(self):
        result=self.scan([page([item('new')],True,'required-next'),page([item('known')],requested='wrong-cursor')])
        self.assertFalse(result['complete_coverage']);self.assertIn('cursor chain gap',result['issues'])
    def test_explicit_truncation_holds_packet(self):
        i=item('new',designated());i['truncated']=True
        result=self.scan([page([item('known'),i])]);self.assertFalse(result['complete_coverage'])
    def test_unreadable_source_output_holds_before_prefix_classification(self):
        for text in ('AZ_BRIDGE_', None, 'ordinary partial text'):
            i=item('new',text);i['argumentsTruncated']=True
            result=self.scan([page([item('known'),i])])
            self.assertFalse(result['complete_coverage'])
            self.assertEqual(result['boundary'],'known')
            i.pop('argumentsTruncated');i['arguments']['text']=designated()
            repaired=self.scan([page([item('known'),i])])
            self.assertTrue(repaired['complete_coverage'])
            self.assertEqual(repaired['candidates'][0]['source_item_id'],'new')
    def test_missing_source_text_holds_without_truncation_flag(self):
        for kind in ('mcpToolCall','assistantMessage'):
            i=item('new',None,kind)
            result=self.scan([page([item('known'),i])])
            self.assertFalse(result['complete_coverage'])
    def test_missing_required_containers_cannot_bridge_a_gap(self):
        for level in ('turns','items'):
            newer=page([],True,'older')
            if level=='turns': newer.pop('turns')
            else: newer['turns'][0].pop('items')
            result=self.scan([newer,page([item('known')],requested='older')])
            self.assertFalse(result['complete_coverage'])
            self.assertTrue(result['issues'])
    def test_unrelated_truncated_records_remain_ignorable(self):
        echo={'id':'echo','type':'userMessage','truncated':True}
        unrelated=item('tool',None);unrelated['tool']='unrelated';unrelated['argumentsTruncated']=True
        self.assertTrue(self.scan([page([item('known'),echo,unrelated])])['complete_coverage'])
    def test_missing_or_invalid_classification_metadata_holds_cancellation(self):
        for field in ('type','server','tool'):
            for value in ('missing',None,'',[],True):
                cancel=item('cancel',designated('cancel'))
                if value=='missing':cancel.pop(field)
                else:cancel[field]=value
                with self.subTest(field=field,value=value):
                    result=self.scan([page([item('known'),item('request',designated()),cancel])])
                    self.assertFalse(result['complete_coverage'])
                    self.assertEqual(result['boundary'],'known')
                    self.assertTrue(result['issues'])
        repaired=self.scan([page([item('known'),item('request',designated()),item('cancel',designated('cancel'))])])
        self.assertTrue(repaired['complete_coverage'])
        self.assertEqual([x['packet']['kind'] for x in repaired['candidates']],['request','cancel'])
    def test_missing_first_page_cursor_annotation_holds_coverage(self):
        fixture=page([item('known'),item('new',designated())]);fixture.pop('requestedCursor')
        result=self.scan([fixture])
        self.assertFalse(result['complete_coverage'])
        self.assertEqual(result['boundary'],'known')
        self.assertTrue(result['issues'])
        fixture['requestedCursor']=None
        self.assertTrue(self.scan([fixture])['complete_coverage'])
    def test_cancel_is_reconciled_before_effect_in_covered_batch(self):
        p=packet(); c=packet('cancel',body={'reason':'cancelled'},request_hash=p['payload_sha256'])
        result=self.scan([page([item('known'),item('request','AZ_BRIDGE_V1 '+json.dumps(p)),item('cancel','AZ_BRIDGE_V1 '+json.dumps(c))])])
        state={'schema_version':1,'requests':{},'operations':{}}
        for candidate in result['candidates']: state,_=bridge.apply_event(state,candidate['packet'],CONTRACT,SOURCE,SOURCE)
        state,decision=bridge.begin(state,p['request_id'],'example-owner')
        self.assertEqual(decision['action'],'reconcile');self.assertEqual(state['requests'][p['request_id']]['executions'],0)
class SourceCliTests(unittest.TestCase):
    def run_collector(self, pages):
        with tempfile.TemporaryDirectory() as directory:
            saved=pathlib.Path(directory)/'pages.json'
            saved.write_text(json.dumps(pages),encoding='utf-8')
            return subprocess.run([sys.executable,str(ROOT/'scripts'/'source_batch.py'),
                                   '--pages',str(saved),'--source',SOURCE,'--boundary','known'],
                                  capture_output=True,text=True)
    def test_complete_cli_batch_exits_zero(self):
        result=self.run_collector([page([item('known'),item('new',designated())])])
        self.assertEqual(result.returncode,0)
        self.assertTrue(json.loads(result.stdout)['complete_coverage'])
    def test_incomplete_cli_batch_exits_hold_and_preserves_candidates(self):
        result=self.run_collector([page([item('new',designated())],True,'older')])
        self.assertEqual(result.returncode,3)
        body=json.loads(result.stdout)
        self.assertFalse(body['complete_coverage'])
        self.assertEqual(body['continuation'],'older')
        self.assertEqual(body['candidates'][0]['source_item_id'],'new')
    def test_wrong_source_cli_returns_json_error(self):
        wrong=page([item('known')]);wrong['thread']['id']='wrong-source'
        result=self.run_collector([wrong])
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stderr),{'error':'wrong registered source thread'})
        self.assertEqual(result.stdout,'')
    def test_incomplete_classification_or_cursor_cli_holds_execution(self):
        fixtures=[]
        for field in ('type','server','tool'):
            cancel=item('cancel',designated('cancel'));cancel.pop(field)
            fixtures.append(page([item('known'),item('request',designated()),cancel]))
        missing_cursor=page([item('known')]);missing_cursor.pop('requestedCursor');fixtures.append(missing_cursor)
        for fixture in fixtures:
            result=self.run_collector([fixture])
            self.assertEqual(result.returncode,3,result.stderr)
            body=json.loads(result.stdout)
            self.assertFalse(body['complete_coverage'])
            self.assertEqual(body['boundary'],'known')
            self.assertTrue(body['issues'])
    def test_malformed_native_shapes_return_json_error_without_traceback(self):
        malformed=[{}, [None], [dict(page([]),thread=[])], [dict(page([]),page=[])],
                   [dict(page([]),turns={})], [dict(page([]),turns=[None])],
                   [dict(page([]),turns=[{'items':'invalid'}])],
                   [page([None])], [page([dict(item('new',designated()),arguments=[])])]]
        for fixture in malformed:
            with self.subTest(fixture=fixture):
                result=self.run_collector(fixture)
                self.assertEqual(result.returncode,1)
                self.assertEqual(result.stdout,'')
                self.assertIsInstance(json.loads(result.stderr)['error'],str)
                self.assertNotIn('Traceback',result.stderr)
                self.assertNotIn(str(ROOT),result.stderr)
if __name__=='__main__': unittest.main()
