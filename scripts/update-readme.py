"""Generate only the manifest table between the README markers."""

import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

BEGIN = '<!-- BEGIN GENERATED APPS -->'
END = '<!-- END GENERATED APPS -->'


def cell(value):
    return html.escape(' '.join(str(value).split()), quote=False).replace('|', '&#124;')


def generate(root, readme):
    if readme.count(BEGIN) != 1 or readme.count(END) != 1:
        raise ValueError('README must contain exactly one pair of generated-app markers')
    before, rest = readme.split(BEGIN)
    _, after = rest.split(END)
    rows = ['| アプリ | バージョン | 説明 | 公式サイト |', '| --- | --- | --- | --- |']
    for path in sorted((root / 'bucket').glob('*.json'), key=lambda p: (p.stem.casefold(), p.stem)):
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        version = manifest.get('version')
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f'{path.name}: version must be a nonempty string')
        homepage = manifest.get('homepage', '')
        if homepage and (not isinstance(homepage, str) or urlsplit(homepage).scheme not in ('http', 'https') or not urlsplit(homepage).netloc):
            raise ValueError(f'{path.name}: homepage must be an HTTP(S) URL')
        link = f'[公式サイト]({quote(homepage, safe=":/?#=&%+@~;,")})' if homepage else '—'
        rows.append(f'| [{cell(path.stem)}](bucket/{quote(path.name)}) | {cell(version)} | {cell(manifest.get("description", ""))} | {link} |')
    return before + BEGIN + '\n\n' + '\n'.join(rows) + '\n\n' + END + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true', help='Fail if README is out of date; do not write')
    args = parser.parse_args()
    path = args.root / 'README.md'
    before = path.read_text(encoding='utf-8')
    after = generate(args.root, before)
    if args.check:
        if before != after:
            parser.exit(1, 'README app list is stale; run python scripts/update-readme.py\n')
        print('README app list is current')
    elif before != after:
        path.write_text(after, encoding='utf-8', newline='\n')
        print('Updated README app list')
    else:
        print('README app list is current')


if __name__ == '__main__':
    main()
