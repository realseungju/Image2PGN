"""Build an offline review page with sibling PNG assets; never mutate source labels."""
import argparse
import hashlib
import json
from pathlib import Path


def build(audit, template, output):
    raw = Path(audit).read_bytes()
    rows = [r for r in json.loads(raw)['items'] if r['used_in_final_replay']]
    if len(rows) != 50 or len({r['id'] for r in rows}) != 50:
        raise ValueError('Expected 50 unique replay items')
    items = []
    output = Path(output)
    asset_dir = output.with_name(output.stem + '-images')
    asset_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        data = Path(r['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != r['sha256']:
            raise ValueError('Image checksum mismatch: ' + r['id'])
        items.append({k: r[k] for k in ('id', 'kind', 'stored_side', 'sha256')})
        filename = r['sha256'] + '.png'
        (asset_dir / filename).write_bytes(data)
        items[-1]['image'] = asset_dir.name + '/' + filename
    payload = json.dumps({'manifest': hashlib.sha256(raw).hexdigest(), 'items': items}, ensure_ascii=True).replace('<', '\\u003c')
    output.write_text(Path(template).read_text(encoding='utf-8').replace('__DATA__', payload), encoding='utf-8')
    return len(items)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    print(build(args.audit, Path(__file__).with_name('label_review.html'), args.output))
