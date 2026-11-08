import json
from pathlib import Path
import tempfile
import unittest
from campaign import resume_case, parallel_case, sanitize, save

class CampaignTests(unittest.TestCase):
    def test_checkpoint_resume_and_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=resume_case(Path(tmp))
            self.assertTrue(result['passed'])
            self.assertTrue(all(result['checks'].values()))

    def test_parallel_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=parallel_case(Path(tmp),True)
            self.assertTrue(result['passed'])
            self.assertEqual([r['workers'] for r in result['results']],[1,2,4,8])

    def test_report_write_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dest=root/'report.json'
            save(dest,{'results':[1]});save(dest,{'results':[1,2]})
            self.assertEqual(json.loads(dest.read_text(encoding='utf-8'))['results'],[1,2])
            self.assertFalse(dest.with_suffix('.tmp').exists())
            self.assertEqual(sanitize(str(root/'fixture'),root),'<fixture>'+str(Path('/fixture')).replace('/', __import__('os').sep))

if __name__=='__main__': unittest.main()
