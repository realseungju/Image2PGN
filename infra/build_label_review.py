"""Build an offline, image-embedded review page; never mutate source labels."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def build(audit, template, output):
    raw = Path(audit).read_bytes()
    rows = [r for r in json.loads(raw)['items'] if r['used_in_final_replay']]
    if len(rows) != 50 or len({r['id'] for r in rows}) != 50:
        raise ValueError('Expected 50 unique replay items')
    items = []
    for r in rows:
        data = Path(r['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != r['sha256']:
            raise ValueError('Image checksum mismatch: ' + r['id'])
        items.append({k: r[k] for k in ('id', 'kind', 'stored_side', 'sha256')})
        items[-1]['image'] = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    payload = json.dumps({'manifest': hashlib.sha256(raw).hexdigest(), 'items': items}, ensure_ascii=True).replace('<', '\\u003c')
    Path(output).write_text(Path(template).read_text(encoding='utf-8').replace('__DATA__', payload), encoding='utf-8')
    return len(items)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    print(build(args.audit, Path(__file__).with_name('label_review.html'), args.output))
