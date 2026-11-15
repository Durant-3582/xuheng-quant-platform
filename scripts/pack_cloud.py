"""Build or independently verify the private, content-addressed cloud archive."""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import ExitStack, closing
from pathlib import Path


PRIVATE = Path(__file__).resolve().parents[1] / '.private'
SOURCE = PRIVATE / 'database'
RELEASE = PRIVATE / 'cloud-release'
TARGET = 4 * 1024**2
LIMIT = 16 * 1024**2
SHA = re.compile(r'[0-9a-f]{64}')
RESEARCH = re.compile(r'(portfolio-|days-|bench-[dm]|value-[dm])20\d{2}')
STARTUP = ('snapshot', 'coverage', 'series/000300.SH')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_manifest():
    raw = (SOURCE / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['format'] != 1 or manifest['sample'] is not False or not manifest['files']:
        raise ValueError('Expected a full format-1 release in .private/database.')
    return manifest, sha(raw)


def validate_shards(manifest):
    paths = []
    for spec in manifest['files'].values():
        name = spec['file']
        if not re.fullmatch(r'[a-z0-9-]+\.sqlite', name) or not SHA.fullmatch(spec['sha256']):
            raise ValueError(f'Invalid shard specification: {name}')
        path = SOURCE / name
        if path.stat().st_size != spec['bytes'] or file_sha(path) != spec['sha256']:
            raise ValueError(f'Source shard failed verification: {name}')
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate source shards in manifest.')
    print(f'Verified {len(paths)} source SQLite files ({sum(p.stat().st_size for p in paths):,} bytes).', flush=True)
    return paths


def open_shard(path):
    return closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True))


def family(key):
    if key in ('snapshot', 'coverage'):
        return 'overview'
    if key == STARTUP[2]:
        return 'series-overview'
    prefix = key.split('/', 1)[0]
    if prefix != 'research':
        return prefix
    name = key.rsplit('/', 1)[-1]
    if name.endswith('-index'):
        return 'research-index'
    dated = RESEARCH.match(name)
    return 'research-' + (dated[1] if dated else name.split('-', 1)[0])


def write_once(path, data, release):
    """Link a complete file into place and never replace an existing destination."""
    def check_existing():
        if path.is_symlink() or path.stat().st_size != len(data) or path.read_bytes() != data:
            raise ValueError(f'Existing file has different contents: {path}')

    if path.exists():
        check_existing()
        return
    tmp = tempfile.NamedTemporaryFile(dir=release, prefix='.pack-cloud-', delete=False)
    staged = Path(tmp.name)
    try:
        with tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        try:
            os.link(staged, path)
        except FileExistsError:
            check_existing()
    finally:
        staged.unlink(missing_ok=True)


def store(data, release):
    if not 0 < len(data) <= LIMIT:
        raise ValueError(f'Invalid content object size: {len(data)}')
    digest = sha(data)
    write_once(release / 'objects' / digest, data, release)
    return digest


def build_index(paths, manifest, source_sha, release=RELEASE):
    sizes, items = {}, {}
    block = bytearray()
    entries = []

    def finish_pack():
        digest = store(block, release)
        sizes[digest] = len(block)
        for key, offset, length, value_sha in entries:
            items[key] = [digest, offset, length, value_sha]
        block.clear()
        entries.clear()

    with ExitStack() as stack:
        shards = [stack.enter_context(open_shard(path)) for path in paths]
        ordered = []
        seen = set()
        for number, db in enumerate(shards):
            for key, in db.execute('SELECT key FROM objects'):
                if key in seen:
                    raise ValueError(f'Duplicate source key: {key}')
                seen.add(key)
                ordered.append((family(key), key, number))
        current = None
        for group, key, number in sorted(ordered):
            blob, = shards[number].execute('SELECT value FROM objects WHERE key=?', (key,)).fetchone()
            if not blob.startswith(b'\x1f\x8b\x08') or len(blob) > LIMIT:
                raise ValueError(f'Invalid gzip value or value larger than 16 MiB: {key}')
            total = len(block) + len(blob)
            # Prefer the nearer of the two possible boundaries around 4 MiB.
            past_target = total > TARGET and abs(total - TARGET) >= abs(len(block) - TARGET)
            if block and (group != current or total > LIMIT or len(blob) >= TARGET or past_target):
                finish_pack()
            entries.append((key, len(block), len(blob), sha(blob)))
            block.extend(blob)
            current = group
        if block:
            finish_pack()

    index = {'version': 1, 'source_sha256': source_sha, 'manifest': manifest, 'sizes': sizes, 'items': items}
    output = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=6, mtime=0) as gz:
        gz.write(json.dumps(index, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())
    return store(output.getvalue(), release)


def read_pointer(path):
    data = path.read_text(encoding='ascii')
    if not re.fullmatch(r'[0-9a-f]{64}\n?', data):
        raise ValueError(f'Invalid release pointer: {path}')
    return data.rstrip('\n')


def verify(index_sha, paths, release=RELEASE):
    """Reopen the index, every published pack and every source row from disk."""
    manifest, source_sha = source_manifest()
    objects = release / 'objects'
    index_path = objects / index_sha
    if not 0 < index_path.stat().st_size <= LIMIT or file_sha(index_path) != index_sha:
        raise ValueError('Index failed SHA-256 or size check.')
    with gzip.open(index_path, 'rb') as stream:
        index = json.load(stream)
    if (set(index) != {'version', 'source_sha256', 'manifest', 'sizes', 'items'} or index['version'] != 1
            or index['source_sha256'] != source_sha or index['manifest'] != manifest):
        raise ValueError('Release index does not describe the current source manifest.')
    sizes, items = index['sizes'], index['items']
    ranges = defaultdict(set)
    for key, (digest, offset, length, value_sha) in items.items():
        if (digest not in sizes or not SHA.fullmatch(value_sha) or type(offset) is not int or offset < 0
                or type(length) is not int or length <= 0 or offset + length > sizes[digest]):
            raise ValueError(f'Invalid index entry: {key}')
        ranges[digest].add((offset, length))
    for digest, size in sizes.items():
        if not SHA.fullmatch(digest) or type(size) is not int or not 0 < size <= LIMIT:
            raise ValueError(f'Invalid pack specification: {digest}')
        path = objects / digest
        if path.stat().st_size != size or file_sha(path) != digest:
            raise ValueError(f'Pack failed SHA-256 or size check: {digest}')
        end = 0
        for offset, length in sorted(ranges[digest]):
            if offset != end:
                raise ValueError(f'Gap or overlap in pack: {digest}')
            end += length
        if end != size:
            raise ValueError(f'Unaccounted bytes in pack: {digest}')

    seen = set()
    for path in paths:
        with open_shard(path) as db:
            for key, original in db.execute('SELECT key,value FROM objects'):
                if key in seen or key not in items:
                    raise ValueError(f'Duplicate or unindexed source key: {key}')
                digest, offset, length, value_sha = items[key]
                with (objects / digest).open('rb') as pack:
                    pack.seek(offset)
                    value = pack.read(length)
                if value != original or sha(value) != value_sha:
                    raise ValueError(f'Slice differs from the source gzip value: {key}')
                seen.add(key)
    if seen != items.keys():
        raise ValueError('Index contains keys absent from the original databases.')
    print(f'Verified {len(seen):,} gzip values, {len(sizes):,} packs, {sum(sizes.values()):,} pack bytes; '
          f'largest pack {max(sizes.values()):,} bytes. Index {index_sha} ({index_path.stat().st_size:,} bytes).', flush=True)
    for key in STARTUP:
        digest, _, length, _ = items[key]
        print(f'  {key}: {length:,} gzip bytes; pack {digest} ({sizes[digest]:,} bytes).', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=RELEASE, type=Path, help='Directory for this immutable release.')
    parser.add_argument('--verify-only', action='store_true', help='Verify an existing published index and all data.')
    args = parser.parse_args()
    manifest, source_sha = source_manifest()
    paths = validate_shards(manifest)
    release = args.output.resolve()
    pointer = release / 'index.sha256'
    if pointer.exists() or args.verify_only:
        verify(read_pointer(pointer), paths, release)
        return
    release.mkdir(parents=True, exist_ok=True, mode=0o700)
    (release / 'objects').mkdir(exist_ok=True, mode=0o700)
    index_sha = build_index(paths, manifest, source_sha, release)
    verify(index_sha, paths, release)
    write_once(pointer, (index_sha + '\n').encode('ascii'), release)
    print(f'Published {pointer}', flush=True)


if __name__ == '__main__':
    main()
