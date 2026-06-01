#!/usr/bin/env python3
"""
tokens.py — Token-consumption collector for Claude Performance Monitor.

Reads Claude Code's local transcript logs (~/.claude/projects/**/*.jsonl) and
aggregates token usage and estimated cost. Each assistant message carries a
`message.usage` block with input / output / cache-read / cache-creation tokens
and the `model` id; every line is timestamped, so the data is an event log we
can aggregate without touching the CPU sampler.

Pure standard library — no external dependencies. (`ccusage` is a great
companion tool but is intentionally NOT a dependency here.)
"""
import json
import os
import glob
from datetime import datetime, timezone, timedelta

CLAUDE_PROJECTS = os.path.join(os.path.expanduser('~'), '.claude', 'projects')
BLOCK_HOURS = 5  # Claude usage windows are 5 hours

# ── Pricing ──────────────────────────────────────────────────────────────────
# USD per 1M tokens. Matched by substring on the model id (opus/sonnet/haiku).
# `cache_write` is the prompt-caching write rate (≈1.25× input, as used by
# ccusage/LiteLLM); `cache_read` is the cache-hit rate (≈0.1× input).
# ⚠️  UPDATE these when Anthropic pricing changes — token counts are exact, the
#     cost figure is only as good as this table.
PRICES = {
    'opus':   {'input': 15.0, 'output': 75.0, 'cache_write': 18.75, 'cache_read': 1.50},
    'sonnet': {'input':  3.0, 'output': 15.0, 'cache_write':  3.75, 'cache_read': 0.30},
    'haiku':  {'input':  1.0, 'output':  5.0, 'cache_write':  1.25, 'cache_read': 0.10},
}
DEFAULT_PRICE = PRICES['sonnet']


def _price_for(model):
    m = (model or '').lower()
    for key, price in PRICES.items():
        if key in m:
            return price
    return DEFAULT_PRICE


def _cost(model, inp, out, cache_write, cr):
    p = _price_for(model)
    return (inp * p['input'] + out * p['output']
            + cache_write * p['cache_write'] + cr * p['cache_read']) / 1_000_000


def _parse_ts(s):
    """ISO-8601 with trailing Z → aware datetime (UTC)."""
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None


# ── Per-file cache: avoid re-parsing unchanged transcripts on every poll ──────
# fp -> {'sig': (size, mtime), 'events': [event, ...]}
# event = (dt_utc, model, inp, out, cw5, cw1, cr, dedupe_key)
_FILE_CACHE = {}


def _parse_file(fp):
    events = []
    try:
        with open(fp, 'r', errors='replace') as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get('type') != 'assistant':
                    continue
                msg = o.get('message') or {}
                usage = msg.get('usage') or {}
                if not usage:
                    continue
                cc = usage.get('cache_creation') or {}
                cw5 = cc.get('ephemeral_5m_input_tokens', 0) or 0
                cw1 = cc.get('ephemeral_1h_input_tokens', 0) or 0
                if not cw5 and not cw1:
                    # Older entries only carry the flat counter — treat as 5m write.
                    cw5 = usage.get('cache_creation_input_tokens', 0) or 0
                events.append((
                    _parse_ts(o.get('timestamp', '')),
                    msg.get('model'),
                    usage.get('input_tokens', 0) or 0,
                    usage.get('output_tokens', 0) or 0,
                    cw5,
                    cw1,
                    usage.get('cache_read_input_tokens', 0) or 0,
                    # Streaming writes duplicate usage lines; dedupe on id + requestId.
                    (msg.get('id'), o.get('requestId')),
                ))
    except Exception:
        return []
    return events


def _all_events(projects_dir):
    out = []
    seen = set(_FILE_CACHE.keys())
    current = set()
    for fp in glob.glob(os.path.join(projects_dir, '**', '*.jsonl'), recursive=True):
        current.add(fp)
        try:
            st = os.stat(fp)
            sig = (st.st_size, st.st_mtime)
        except OSError:
            continue
        cached = _FILE_CACHE.get(fp)
        if not cached or cached['sig'] != sig:
            cached = {'sig': sig, 'events': _parse_file(fp)}
            _FILE_CACHE[fp] = cached
        out.extend(cached['events'])
    # Drop cache entries for files that disappeared.
    for gone in seen - current:
        _FILE_CACHE.pop(gone, None)
    return out


# ── Aggregation ────────────────────────────────────────────────────────────
def _empty():
    return {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0,
            'total': 0, 'cost_usd': 0.0}


def _add(acc, model, inp, out, cw5, cw1, cr):
    cache_write = cw5 + cw1
    acc['input'] += inp
    acc['output'] += out
    acc['cache_read'] += cr
    acc['cache_creation'] += cache_write
    acc['total'] += inp + out + cr + cache_write
    acc['cost_usd'] += _cost(model, inp, out, cache_write, cr)


def _round(acc):
    acc['cost_usd'] = round(acc['cost_usd'], 4)
    return acc


def _active_block(sorted_events, now_utc):
    """ccusage-style 5h windows: a block starts at the first event (floored to
    the hour) and ends 5h later or after a >5h idle gap. Returns the events of
    the block that is still active right now, plus its start, or (None, None)."""
    block_start = None
    block_events = []
    last_dt = None
    for ev in sorted_events:
        dt = ev[0]
        if dt is None:
            continue
        if block_start is None:
            block_start = dt.replace(minute=0, second=0, microsecond=0)
            block_events = [ev]
        elif (dt - block_start) >= timedelta(hours=BLOCK_HOURS) or \
             (last_dt and (dt - last_dt) >= timedelta(hours=BLOCK_HOURS)):
            block_start = dt.replace(minute=0, second=0, microsecond=0)
            block_events = [ev]
        else:
            block_events.append(ev)
        last_dt = dt
    if block_start is None:
        return None, None
    if (now_utc - block_start) >= timedelta(hours=BLOCK_HOURS):
        return None, None  # last block already closed
    return block_events, block_start


def collect_token_usage(interval_s=60, projects_dir=CLAUDE_PROJECTS):
    """Returns the `tokens` section served in /data, or {'available': False}."""
    if not os.path.isdir(projects_dir):
        return {'available': False, 'reason': f'not found: {projects_dir}'}

    raw = _all_events(projects_dir)
    if not raw:
        return {'available': False, 'reason': 'no usage data in transcripts'}

    # Dedupe across files (streaming writes the same usage line more than once).
    seen = set()
    events = []
    for dt, model, inp, out, cw5, cw1, cr, key in raw:
        if key[0] is not None and key in seen:
            continue
        seen.add(key)
        events.append((dt, model, inp, out, cw5, cw1, cr))

    now_utc = datetime.now(timezone.utc)
    today_local = datetime.now().date()
    interval_s = max(1, int(interval_s))

    totals = _empty()
    today = _empty()
    by_model = {}
    buckets = {}  # bucket_epoch -> accumulator (today only, for the chart)

    for dt, model, inp, out, cw5, cw1, cr in events:
        _add(totals, model, inp, out, cw5, cw1, cr)
        bm = by_model.setdefault(model or 'unknown', _empty())
        _add(bm, model, inp, out, cw5, cw1, cr)
        if dt is not None and dt.astimezone().date() == today_local:
            _add(today, model, inp, out, cw5, cw1, cr)
            epoch = int(dt.timestamp())
            b = (epoch // interval_s) * interval_s
            _add(buckets.setdefault(b, _empty()), model, inp, out, cw5, cw1, cr)

    # Active 5h block.
    block = _empty()
    block_start = None
    be, bs = _active_block(sorted([e for e in events if e[0]], key=lambda e: e[0]), now_utc)
    if be is not None:
        block_start = bs
        for dt, model, inp, out, cw5, cw1, cr in be:
            _add(block, model, inp, out, cw5, cw1, cr)

    # Sparse time series (today's active buckets only), cap to last 180 points.
    series = {'labels': [], 'input': [], 'output': [], 'cache_read': [],
              'cache_creation': [], 'total': []}
    for b in sorted(buckets)[-180:]:
        acc = buckets[b]
        series['labels'].append(datetime.fromtimestamp(b).strftime('%H:%M'))
        for k in ('input', 'output', 'cache_read', 'cache_creation', 'total'):
            series[k].append(acc[k])

    result = {
        'available': True,
        'totals': _round(totals),
        'today': _round(today),
        'block_5h': _round(block),
        'by_model': {m: _round(v) for m, v in sorted(
            by_model.items(), key=lambda kv: kv[1]['total'], reverse=True)
            if v['total'] > 0},
        'series': series,
    }
    if block_start is not None:
        block_end = block_start + timedelta(hours=BLOCK_HOURS)
        result['block_5h']['start'] = block_start.astimezone().strftime('%H:%M')
        result['block_5h']['remaining_min'] = max(
            0, int((block_end - now_utc).total_seconds() // 60))
    return result


if __name__ == '__main__':
    # Quick CLI sanity check: python3 tokens.py
    import sys
    data = collect_token_usage(interval_s=60)
    json.dump(data, sys.stdout, indent=2, default=str)
    print()
