#!/usr/bin/env python3
"""Bounded HTTP CONNECT proxy collector. Python 3.11+, curl 8+."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import tempfile
from urllib.parse import urlsplit

PROBE_URL = 'https://www.youtube.com/generate_204'
SPEED_URL = 'https://speed.cloudflare.com/__down?bytes=65536'
SPEED_BYTES = 65536
SOURCE_LIMIT = 2_000_000
SOURCES = {
    'proxifly': 'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt',
    'speedx': 'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat(timespec='seconds').replace('+00:00', 'Z')


def parse_endpoint(line):
    """Public literal IPv4 only: no DNS rebinding, credentials, local or reserved IPs."""
    try:
        line = line.strip()
        if not line or any(c.isspace() for c in line):
            return None
        u = urlsplit(line if '://' in line else 'http://' + line)
        if u.scheme != 'http' or u.username or u.password or u.path or u.query or u.fragment:
            return None
        ip = ipaddress.ip_address(u.hostname or '')
        if ip.version != 4 or not ip.is_global or ip.is_multicast or ip.is_reserved:
            return None
        if u.port is None or not 1 <= u.port <= 65535:
            return None
        return (str(ip), u.port)
    except ValueError:
        return None


def transfer(url, *, endpoint=None, timeout=8, limit=SOURCE_LIMIT):
    """Fresh curl process: explicit routing, TLS verification, no redirects/retries."""
    with tempfile.TemporaryDirectory(prefix='proxy-probe-') as tmp:
        body = Path(tmp) / 'body'
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
        # -q must be first: do not load ~/.curlrc (could change proxy/TLS behavior).
        cmd = ['curl', '-q', '--silent', '--show-error', '--proto', '=https',
               '--connect-timeout', str(min(4, timeout)), '--max-time', str(timeout),
               '--max-filesize', str(limit), '--retry', '0', '--output', str(body),
               '--write-out', '%{json}', '--user-agent', 'YouTrocProxyPool/1.0',
               '--proxy', f'http://{endpoint[0]}:{endpoint[1]}' if endpoint else '',
               '--noproxy', '' if endpoint else '*', url]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout + 2)
            if p.returncode:
                return {'ok': False, 'error': f'curl_exit_{p.returncode}'}
            m = json.loads(p.stdout)
            data = body.read_bytes()
            if len(data) > limit or int(m.get('ssl_verify_result', -1)) != 0:
                return {'ok': False, 'error': 'invalid_transfer'}
            # Never count a direct fallback or failed CONNECT as a proxy success.
            if endpoint and (int(m.get('http_connect', 0)) != 200 or m.get('remote_ip') != endpoint[0]):
                return {'ok': False, 'error': 'proxy_not_used'}
            values = [float(m[k]) for k in ('time_total', 'time_starttransfer', 'speed_download')]
            if not all(math.isfinite(v) and v >= 0 for v in values):
                return {'ok': False, 'error': 'invalid_metrics'}
            return {'ok': True, 'status': int(m['http_code']), 'body': data,
                    'latency_ms': round(values[0] * 1000, 2),
                    'ttfb_ms': round(values[1] * 1000, 2),
                    'download_mbps': round(values[2] * 8 / 1_000_000, 4)}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            return {'ok': False, 'error': 'transfer_error'}


def collect():
    candidates = {}
    reports = []
    for source_id, url in SOURCES.items():
        r = transfer(url, timeout=20)
        if not r['ok'] or r['status'] != 200:
            reports.append({'id': source_id, 'url': url, 'ok': False,
                            'error': r.get('error', 'http_status'), 'accepted': 0})
            continue
        found = {ep for line in r['body'].decode('utf-8', 'replace').splitlines()
                 if (ep := parse_endpoint(line)) is not None}
        for ep in found:
            candidates.setdefault(ep, set()).add(source_id)
        reports.append({'id': source_id, 'url': url, 'ok': bool(found), 'accepted': len(found)})
    return candidates, reports


def probe(candidate, *, samples=2, timeout=8, speed=True):
    endpoint, sources = candidate
    timings, ttfbs = [], []
    # Require every sample to succeed: one lucky response is not a stable candidate.
    for _ in range(samples):
        r = transfer(PROBE_URL, endpoint=endpoint, timeout=timeout, limit=1024)
        if not r['ok'] or r['status'] != 204 or r['body']:
            return None
        timings.append(r['latency_ms'])
        ttfbs.append(r['ttfb_ms'])
    mbps = None
    if speed:
        r = transfer(SPEED_URL, endpoint=endpoint, timeout=timeout, limit=SPEED_BYTES)
        if r['ok'] and r['status'] == 200 and len(r['body']) == SPEED_BYTES:
            mbps = r['download_mbps']
    now = utcnow()
    return {'host': endpoint[0], 'port': endpoint[1], 'protocol': 'HTTP',
            'https_connect': True, 'youtube_probe_ok': True,
            'latency_ms': round(statistics.median(timings), 2),
            'ttfb_ms': round(statistics.median(ttfbs), 2),
            'latency_samples_ms': timings, 'successful_samples': samples,
            'download_mbps': mbps, 'download_bytes': SPEED_BYTES if mbps is not None else 0,
            'speed_test_ok': mbps is not None, 'checked_at': stamp(now),
            'expires_at': stamp(now + timedelta(hours=2)), 'sources': sorted(sources)}


def build_document(results, reports, discovered, tested):
    now = utcnow()
    results.sort(key=lambda p: (p['latency_ms'], -(p['download_mbps'] or 0), p['host'], p['port']))
    available = sum(bool(r['ok']) for r in reports)
    status = ('sources_unavailable' if not available else
              'no_working_proxies' if not results else
              'degraded' if available != len(reports) else 'ok')
    return {'schema_version': 1, 'generated_at': stamp(now),
            'expires_at': stamp(now + timedelta(hours=2)), 'status': status,
            'measurement': {'vantage': 'github-actions' if os.getenv('GITHUB_ACTIONS') else 'local',
                            'probe_url': PROBE_URL, 'speed_url': SPEED_URL,
                            'sort': 'latency_ms_ascending',
                            'latency_definition': 'median total HTTPS request time on fresh connections',
                            'speed_definition': 'curl average download rate for 65536-byte Cloudflare sample; not YouTube video speed'},
            'stats': {'discovered': discovered, 'tested': tested, 'working': len(results)},
            'sources': reports, 'proxies': results}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='public/proxies.json')
    parser.add_argument('--limit', type=int, default=400)
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--timeout', type=float, default=8)
    parser.add_argument('--samples', type=int, default=2)
    parser.add_argument('--no-speed', action='store_true')
    args = parser.parse_args()
    if not (1 <= args.limit <= 2000 and 1 <= args.workers <= 24 and
            1 <= args.timeout <= 20 and 1 <= args.samples <= 3):
        parser.error('limits: candidates 1..2000, workers 1..24, timeout 1..20, samples 1..3')
    baseline = transfer(PROBE_URL, timeout=args.timeout, limit=1024)
    baseline_summary = {k: v for k, v in baseline.items() if k != 'body'}
    candidates, reports = collect()
    batch = list(candidates.items())
    random.SystemRandom().shuffle(batch)  # Rotate the sample instead of always testing list heads.
    batch = batch[:args.limit]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(filter(None, pool.map(
            lambda c: probe(c, samples=args.samples, timeout=args.timeout, speed=not args.no_speed), batch)))
    document = build_document(results, reports, len(candidates), len(batch))
    document['measurement']['direct_baseline'] = baseline_summary
    # Publish truthful empty/degraded output; never renew timestamps on old endpoints.
    write_json(args.output, document)
    print(json.dumps({'status': document['status'], **document['stats']}))


if __name__ == '__main__':
    main()
