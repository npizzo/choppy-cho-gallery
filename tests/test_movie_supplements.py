from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/apply_movie_supplements.py'
spec = importlib.util.spec_from_file_location('supplements', SCRIPT)
supplements = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supplements)


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.page = self.root/'experiments/langmuir-steepening/index.html'
        self.page.parent.mkdir(parents=True)
        self.snapshot = dict(source_fingerprint='a'*64, cho_enabled=True, cho_damping_multiplier=2.4,
            cases=[dict(id='steep12', status='complete', parameters={'duration': 6}),
                   dict(id='long10', status='complete', parameters={'duration': 30})])
        self.page.with_name('snapshot.json').write_text(json.dumps(self.snapshot))
        self.page.write_text(self.original_page())
        self.base = self.root/'supplements/langmuir-steepening'
        self.manifest = dict(schema_version=1, experiment='langmuir-steepening', source_fingerprint='a'*64, cases={})

    def original_page(self):
        return '<html>' + ''.join(f'<section><video id="late-{case}"></video><h3>Full parent evolution</h3><video id="parent-{case}"></video><p><a href="assets/{case}/parent_evolution.json">Parent movie metadata</a></p><h3>Underwater current structures</h3></section>' for case in ['steep12','long10']) + '</html>'

    def add_case(self, case='steep12', **changes):
        duration = 6 if case == 'steep12' else 30
        p = self.base/case;p.mkdir(parents=True, exist_ok=True)
        meta = dict(case=case, source_fingerprint='a'*64, quantity='parent_plus_cho', cho_enabled=True,
            damping_multiplier=2.4, physical_interval_s=[0,duration], physical_playback_speed=.2,
            fps=20, video_frame_count=duration*100+1, encoded_duration_s=duration*5+.05, vertical_exaggeration=1,
            render_complete=True, full_saved_interval=True)
        meta.update(changes)
        entry = {'sha256': {}}
        for key, suffix, data in [('video','mp4',b'test-video'),('poster','png',b'test-poster'),('metadata','json',json.dumps(meta).encode())]:
            file=p/('parent_plus_cho_evolution.'+suffix);file.write_bytes(data)
            entry[key]=str(file.relative_to(self.base));entry['sha256'][key]=hashlib.sha256(data).hexdigest()
        self.manifest['cases'][case] = entry
        (self.base/'manifest.json').write_text(json.dumps(self.manifest))

    def test_full_movie_follows_parent_preserves_late_clip_and_is_idempotent(self):
        self.add_case()
        self.assertEqual(supplements.apply(self.root), 1)
        content=self.page.read_text()
        self.assertLess(content.index('id="parent-steep12"'),content.index('id="full-cho-steep12"'))
        self.assertLess(content.index('id="full-cho-steep12"'),content.index('Underwater current structures'))
        self.assertIn('id="late-steep12"',content)
        supplements.apply(self.root)
        self.assertEqual(self.page.read_text(),content)

    def test_recreated_frozen_page_regains_both_supplements(self):
        self.add_case();supplements.apply(self.root)
        self.page.write_text(self.original_page())
        self.add_case('long10')
        self.assertEqual(supplements.apply(self.root),2)
        self.assertIn('id="full-cho-steep12"',self.page.read_text())
        self.assertIn('id="full-cho-long10"',self.page.read_text())

    def test_wrong_source_interval_or_timing_rejected(self):
        for bad in [{'source_fingerprint':'b'*64}, {'physical_interval_s':[5.5,6]},
                    {'physical_playback_speed':.1}, {'fps':60}, {'video_frame_count':31},
                    {'quantity':'parent_only'}, {'vertical_exaggeration':2},
                    {'render_complete':False}, {'full_saved_interval':False}]:
            with self.subTest(bad=bad):
                self.add_case(**bad)
                with self.assertRaises(ValueError):supplements.apply(self.root)

    def test_incomplete_case_and_changed_asset_rejected(self):
        self.add_case()
        self.snapshot['cases'][0]['status']='awaiting_completed_run'
        self.page.with_name('snapshot.json').write_text(json.dumps(self.snapshot))
        with self.assertRaisesRegex(ValueError,'completed published case'):supplements.apply(self.root)
        self.snapshot['cases'][0]['status']='complete'
        self.page.with_name('snapshot.json').write_text(json.dumps(self.snapshot))
        (self.base/self.manifest['cases']['steep12']['video']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):supplements.apply(self.root)

    def test_changed_page_anchor_fails_instead_of_silent_omission(self):
        self.add_case();self.page.write_text('<html>Different layout</html>')
        with self.assertRaisesRegex(ValueError,'insertion point'):supplements.apply(self.root)


if __name__ == '__main__':unittest.main()
