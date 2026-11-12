"""Product takeover through the same public CLI used by a fresh Codex session."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductCLITests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'output' / 'repository-tests' / 'tmp'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.data = self.workspace / '个人数据'
        self.env = {**os.environ, 'EDS_DATA_HOME': str(self.data),
                    'EDS_CACHE_HOME': str(self.workspace / 'cache'), 'PYTHONIOENCODING': 'utf-8'}
        self.cli('data', 'init', str(self.data), '--user-id', 'fixture-user')

    def cli(self, *arguments, data=None, success=True):
        result = subprocess.run([sys.executable, '-m', 'eds', *arguments], cwd=ROOT,
                                env=self.env, text=True, encoding='utf-8', capture_output=True,
                                input=json.dumps(data, ensure_ascii=False) if data is not None else None)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return json.loads(result.stderr)

    def test_takeover_text_and_drawing_then_reuse_and_find_across_processes(self):
        product = '@product/gearbox'
        self.cli('product', product, 'init', '--product-id', 'gearbox', '--name', '成熟减速箱')
        first = self.cli('product', product, 'show')
        self.assertEqual(first['ref'], 'product-baseline@1')
        drawing = self.workspace / '图纸说明.txt'
        drawing.write_text('Fixture drawing observation: hole spacing 120 mm. No CAD parsing performed.', encoding='utf-8')
        second = self.cli('product', product, 'attach', str(drawing), '--asset-id', 'drawing',
                          '--role', 'drawing', '--revision', 'Rev-C', '--base', first['ref'])
        self.assertEqual(second['ref'], 'product-baseline@2')
        changes = {'statements': [
            {'id': 'interface', 'subject': 'mount', 'topic': 'constraint',
             'text': '安装接口必须兼容老产品', 'attribution': 'user',
             'sources': [{'uri': 'chat://fixture/turn-1', 'locator': '用户原话第1条'}]},
            {'id': 'spacing', 'subject': 'mount', 'topic': 'parameter', 'text': '图示安装孔距120毫米',
             'value': 120, 'unit': 'mm', 'attribution': 'document',
             'sources': [{'asset_id': 'drawing', 'locator': 'fixture line 1'}]},
        ], 'gaps': ['材料牌号待确认']}
        third = self.cli('product', product, 'update', '--base', second['ref'], '--data', '-', data=changes)
        self.assertEqual(third['ref'], 'product-baseline@3')
        self.assertEqual(len(self.cli('product', product, 'show', '--ref', first['ref'])['payload']['assets']), 0)
        self.assertIn('材料牌号待确认', json.dumps(self.cli('product', product, 'resume'), ensure_ascii=False))
        # Modifying the source must not mutate the preserved product attachment.
        drawing.write_text('New external source revision', encoding='utf-8')
        self.cli('product', product, 'check-assets', '--ref', third['ref'])
        snapshots = []
        for mode in ('cad', 'cae'):
            task = '@study/' + mode
            self.cli('study', task, 'init', '--mode', mode, '--goal', '以既有产品开展' + mode)
            self.cli('product', product, 'use', '--study', task, '--baseline', third['ref'])
            before = self.cli('study', task, 'show', '--kind', 'design')
            self.cli('product', product, 'use', '--study', task, '--baseline', third['ref'])
            self.assertEqual(self.cli('study', task, 'show', '--kind', 'design'), before)
            self.assertIn(third['ref'], json.dumps(before))
            snapshots.append((task, before))
        newer = self.cli('product', product, 'update', '--base', third['ref'], '--data', '-',
                         data={'gaps': ['待提供工作载荷']})
        for task, before in snapshots:
            self.assertEqual(self.cli('study', task, 'show', '--kind', 'design'), before)
        self.cli('product', product, 'use', '--study', '@study/cad', '--baseline', newer['ref'])
        cad_designs = self.cli('study', '@study/cad', 'show', '--kind', 'design')
        self.assertEqual(len(cad_designs), 2)
        self.assertEqual(cad_designs[0], snapshots[0][1][0])
        self.assertIn(newer['ref'], json.dumps(cad_designs[-1]))
        self.cli('product', product, 'publish', '--baseline', third['ref'])
        self.cli('product', product, 'publish', '--baseline', third['ref'])
        matches = self.cli('kb', '@knowledge', 'search', '安装接口', '--type', 'design')['matches']
        self.assertTrue(matches)
        unit = self.cli('kb', '@knowledge', 'read', matches[0]['id'], '--version', matches[0]['version'])
        self.assertIn('材料牌号待确认', json.dumps(unit, ensure_ascii=False))
        self.assertIn('chat://fixture/turn-1', json.dumps(unit, ensure_ascii=False))

    def test_invalid_alias_and_stale_update_do_not_replace_baseline(self):
        self.cli('product', '@product/../escape', 'init', '--product-id', 'bad', '--name', 'bad', success=False)
        product = '@product/part'
        self.cli('product', product, 'init', '--product-id', 'part', '--name', '零件')
        current = self.cli('product', product, 'update', '--base', 'product-baseline@1', '--data', '-',
                           data={'gaps': ['来源待补充']})
        self.cli('product', product, 'update', '--base', 'product-baseline@1', '--data', '-',
                 data={'gaps': []}, success=False)
        self.assertEqual(self.cli('product', product, 'show'), current)
        self.cli('product', product, 'show', '--ref', 'missing@1', success=False)
        self.cli('product', product, 'update', '--base', 'product-baseline', '--data', '-',
                 data={'gaps': []}, success=False)


if __name__ == '__main__':
    unittest.main()
