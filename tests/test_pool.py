import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import proxy_pool as p


class PoolTests(unittest.TestCase):
    def test_public_endpoints(self):
        self.assertEqual(p.parse_endpoint('http://8.8.8.8:8080'), ('8.8.8.8', 8080))
        self.assertEqual(p.parse_endpoint('1.1.1.1:80'), ('1.1.1.1', 80))

    def test_reject_untrusted_addresses_and_syntax(self):
        for value in ['127.0.0.1:80', '10.1.2.3:80', '169.254.169.254:80',
                      '192.168.1.1:80', '100.64.0.1:80', '192.0.2.1:80',
                      '224.0.0.1:80', '0.0.0.0:80', '[::1]:80',
                      'example.org:80', '8.8.8.8:0', '8.8.8.8:65536',
                      'http://user:pass@8.8.8.8:80', 'socks5://8.8.8.8:80',
                      'http://8.8.8.8:80/path', '8.8.8.8:80#x', '--help', '']:
            with self.subTest(value=value):
                self.assertIsNone(p.parse_endpoint(value))

    @patch.object(p, 'transfer')
    def test_merge_and_source_failure(self, transfer):
        transfer.side_effect = [dict(ok=True, status=200, body=b'8.8.8.8:80\n8.8.8.8:80\n127.0.0.1:80'),
                                dict(ok=False, error='timeout')]
        endpoints, reports = p.collect()
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(reports[0]['accepted'], 1)
        self.assertFalse(reports[1]['ok'])

    @patch.object(p, 'transfer')
    def test_probe_median_speed_and_freshness(self, transfer):
        transfer.side_effect = [dict(ok=True, status=204, body=b'', latency_ms=t, ttfb_ms=t-5)
                                for t in [100, 200]] + [dict(ok=True, status=200, body=b'x'*65536, download_mbps=4.2)]
        result = p.probe((('8.8.8.8', 80), {'a'}))
        self.assertEqual(result['latency_ms'], 150)
        self.assertEqual(result['download_mbps'], 4.2)
        self.assertGreater(result['expires_at'], result['checked_at'])

    @patch.object(p, 'transfer')
    def test_reject_redirects_interception_and_intermittent_proxy(self, transfer):
        for bad in [dict(ok=True, status=302, body=b''), dict(ok=True, status=200, body=b'login'),
                    dict(ok=True, status=204, body=b'injected'), dict(ok=False, error='tls')]:
            transfer.side_effect = [dict(ok=True, status=204, body=b'', latency_ms=10, ttfb_ms=8), bad]
            self.assertIsNone(p.probe((('8.8.8.8', 80), {'a'})))

    @patch.object(p, 'transfer')
    def test_failed_speed_not_zero_or_false_success(self, transfer):
        transfer.side_effect = [dict(ok=True, status=204, body=b'', latency_ms=5, ttfb_ms=4),
                                dict(ok=True, status=200, body=b'short', download_mbps=100)]
        result = p.probe((('8.8.8.8', 80), {'a'}), samples=1)
        self.assertIsNone(result['download_mbps'])
        self.assertFalse(result['speed_test_ok'])

    def test_empty_results_publish_explicit_status(self):
        for reports, status in [([{'ok': False}], 'sources_unavailable'), ([{'ok': True}], 'no_working_proxies')]:
            doc = p.build_document([], reports, 10, 10)
            self.assertEqual(doc['status'], status)
            self.assertEqual(doc['proxies'], [])
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp)/'proxies.json'
                dest.write_text('{"old":true}')
                p.write_json(dest, doc)
                self.assertEqual(json.loads(dest.read_text()), doc)
                self.assertFalse(dest.with_suffix('.tmp').exists())

    def test_ranking_is_latency_first(self):
        rows = [dict(latency_ms=100, download_mbps=8, host='8.8.8.8', port=80),
                dict(latency_ms=50, download_mbps=None, host='1.1.1.1', port=80)]
        doc = p.build_document(rows, [{'ok': True}, {'ok': False}], 2, 2)
        self.assertEqual(doc['proxies'][0]['host'], '1.1.1.1')
        self.assertEqual(doc['status'], 'degraded')

    @patch.object(subprocess, 'run')
    def test_curl_forces_proxy_and_preserves_tls_verification(self, run):
        def fake(cmd, **kwargs):
            self.assertEqual(cmd[:2], ['curl', '-q'])
            self.assertEqual(cmd[cmd.index('--proxy')+1], 'http://8.8.8.8:80')
            self.assertEqual(cmd[cmd.index('--noproxy')+1], '')
            self.assertNotIn('--insecure', cmd)
            self.assertNotIn('--location', cmd)
            self.assertFalse(any(k.lower() == 'https_proxy' for k in kwargs['env']))
            Path(cmd[cmd.index('--output')+1]).write_bytes(b'')
            return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(http_code=204, http_connect=200,
                remote_ip='8.8.8.8', ssl_verify_result=0, time_total=.1, time_starttransfer=.08, speed_download=0)), '')
        run.side_effect = fake
        self.assertTrue(p.transfer(p.PROBE_URL, endpoint=('8.8.8.8',80))['ok'])

    @patch.object(subprocess, 'run')
    def test_direct_fallback_is_rejected(self, run):
        def fake(cmd, **kwargs):
            Path(cmd[cmd.index('--output')+1]).write_bytes(b'')
            return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(http_code=204, http_connect=0,
                remote_ip='1.1.1.1', ssl_verify_result=0)), '')
        run.side_effect = fake
        self.assertEqual(p.transfer(p.PROBE_URL, endpoint=('8.8.8.8',80))['error'], 'proxy_not_used')

if __name__ == '__main__':
    unittest.main()
