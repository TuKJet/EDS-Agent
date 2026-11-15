"""The experiment ledger must not scale with repeated raw tool payloads."""
import json
import tempfile
import unittest
from pathlib import Path

from eds.study import StudyStore, StudyError


class RecordStorageTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output/repository-tests/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.store = StudyStore.create(Path(self.tmp.name)/'study', 'Keep scientific evidence', mode='cae')
        self.exp = self.store.add('experiment', {'question':'Compare response', 'observations':['A1'], 'decision_rule':'compare'}, ref='exp')

    def run_record(self, key):
        return self.store.add_run(experiment_ref=self.exp['ref'],input_refs=[],backend='fixture',capability='solve',input_snapshot={'force_N':.05},idempotency_key=key)

    def test_latest_output_is_derived_not_stored_twice(self):
        r=self.run_record('one');self.store.transition_run(r['run_id'],'submitting')
        self.store.transition_run(r['run_id'],'completed',output={'tip_mm':2.207})
        disk=json.loads(self.store.path.read_text())
        self.assertNotIn('output',disk['runs'][0])
        self.assertEqual(self.store.get_run(r['run_id'])['output'],{'tip_mm':2.207})
        self.assertEqual(disk['runs'][0]['history'][-1]['output'],{'tip_mm':2.207})

    def test_large_output_saved_once_and_explicitly_verified(self):
        payload={'trace':'raw-evidence-'*20000}
        receipts=[]
        for key in ['a','b']:
            r=self.run_record(key);self.store.transition_run(r['run_id'],'submitting')
            receipts.append(self.store.transition_run(r['run_id'],'completed',output=payload)['output'])
        self.assertLess(self.store.path.stat().st_size,20000)
        self.assertEqual(receipts[0],receipts[1])
        self.assertEqual(self.store.read_artifact(receipts[0]),payload)
        artifacts=list((self.store.root/'artifacts').glob('*.json'))
        self.assertEqual(len(artifacts),1)
        artifacts[0].write_text('{}')
        with self.assertRaises(StudyError):self.store.read_artifact(receipts[0])

    def test_recorded_time_is_distinct_from_backdated_observation(self):
        r=self.run_record('time')
        result=self.store.transition_run(r['run_id'],'submitting',observed_at='2020-01-01T00:00:00+00:00')
        self.assertGreater(result['history'][-1]['recorded_at'],result['history'][-1]['at'])

    def test_artifact_paths_cannot_escape_the_study(self):
        payload = {'data': 'x' * 20000}
        receipt = self.store._store_payload(payload)
        for uri in [str(self.store.root.parent / 'outside.json'), '../outside.json']:
            with self.assertRaises(StudyError):
                self.store.read_artifact({**receipt, 'uri': uri})
        outside = self.store.root.parent / 'outside.json'
        outside.write_text('{}')
        link = self.store.root / 'artifacts' / 'escape.json'
        link.symlink_to(outside)
        with self.assertRaises(StudyError):
            self.store.read_artifact({**receipt, 'uri': 'artifacts/escape.json'})

    def test_compacted_arguments_keep_the_same_action_identity(self):
        snapshot = {'tool': 'solve', 'expected_server': 'fixture', 'arguments': {'code': 'x' * 20000}}
        request = dict(experiment_ref=self.exp['ref'], input_refs=[], backend='fixture',
                       capability='solve', input_snapshot=snapshot)
        run = self.store.add_run(**request, idempotency_key='original')
        self.store.transition_run(run['run_id'], 'submitting')
        self.store.transition_run(run['run_id'], 'completed', output={'amplitude': 2})
        state = self.store.read()
        self.store.compact_storage(state, write_artifacts=True)
        self.store._write(state)
        self.assertEqual(self.store.add_run(**request, idempotency_key='original')['run_id'], run['run_id'])
        with self.assertRaisesRegex(StudyError, 'repeated MCP action'):
            self.store.add_run(**request, idempotency_key='different-key')


if __name__=='__main__':unittest.main()
