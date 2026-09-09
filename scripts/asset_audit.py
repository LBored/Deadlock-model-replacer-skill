"""Read-only directory / Valve VPK v1-v2 payload audit. Python 3.10+, stdlib.

Does not extract, modify packages, resolve game dependencies or verify VPK MD5.
Output paths are explicit. Directory links/reparse points are rejected.
Reports omit absolute source paths unless --include-source-path is supplied.
"""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import zlib

CHUNK = 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_name(name):
    name = name.replace('\\', '/')
    require(name and not name.startswith('/') and ':' not in name,
            f'Invalid resource path: {name!r}')
    require(all(p not in ('', '.', '..') for p in name.split('/')),
            f'Invalid resource path: {name!r}')
    return name


def linked(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def file_chunks(path, offset=0, count=None):
    with path.open('rb') as stream:
        stream.seek(offset)
        while count is None or count:
            data = stream.read(CHUNK if count is None else min(CHUNK, count))
            if not data:
                require(count in (None, 0), f'Truncated payload: {path.name}')
                break
            yield data
            if count is not None:
                count -= len(data)


def digest(chunks):
    h, crc, size = hashlib.sha256(), 0, 0
    for data in chunks:
        h.update(data)
        crc = zlib.crc32(data, crc)
        size += len(data)
    return {'sha256': h.hexdigest(), 'bytes': size}, crc & 0xffffffff


class VPK:
    def __init__(self, path):
        self.path = path
        with path.open('rb') as f:
            header = f.read(28)
            require(len(header) >= 12, 'Truncated VPK header')
            magic, self.version, tree_size = struct.unpack_from('<III', header)
            require(magic == 0x55aa1234 and self.version in (1, 2),
                    'Only Valve VPK versions 1 and 2 supported')
            header_size = 12 if self.version == 1 else 28
            require(len(header) >= header_size, 'Truncated VPK header')
            require(tree_size <= 256 * CHUNK, 'VPK tree exceeds audit limit')
            self.data_start = header_size + tree_size
            require(self.data_start <= path.stat().st_size, 'Truncated VPK tree')
            self.data_size = (struct.unpack_from('<I', header, 12)[0] if self.version == 2
                              else path.stat().st_size - self.data_start)
            require(self.data_start + self.data_size <= path.stat().st_size,
                    'Truncated VPK data section')
            f.seek(header_size)
            self.tree = f.read(tree_size)
        self.pos, self.entries = 0, {}
        folded = set()
        while True:
            ext = self.string()
            if not ext:
                break
            while True:
                folder = self.string()
                if not folder:
                    break
                while True:
                    name = self.string()
                    if not name:
                        break
                    require(self.pos + 18 <= len(self.tree), 'Truncated VPK entry')
                    crc, pre, archive, offset, size, term = struct.unpack_from('<IHHIIH', self.tree, self.pos)
                    self.pos += 18
                    require(term == 0xffff and self.pos + pre <= len(self.tree), 'Invalid VPK entry')
                    preload = self.tree[self.pos:self.pos + pre]
                    self.pos += pre
                    key = safe_name(('' if folder == ' ' else folder + '/') + name + ('' if ext == ' ' else '.' + ext))
                    require(key.casefold() not in folded, f'Duplicate/case-colliding resource: {key}')
                    folded.add(key.casefold())
                    self.entries[key] = (crc, preload, archive, offset, size)
        require(self.pos == len(self.tree), 'Unexpected trailing VPK tree bytes')

    def string(self):
        end = self.tree.find(b'\0', self.pos)
        require(end >= 0, 'Unterminated VPK string')
        value = self.tree[self.pos:end].decode('utf-8')
        self.pos = end + 1
        return value

    def chunks(self, entry):
        _, preload, archive, offset, size = entry
        yield preload
        if not size:
            return
        if archive == 0x7fff:
            require(offset + size <= self.data_size, 'Inline VPK payload out of bounds')
            archive_path, offset = self.path, self.data_start + offset
        else:
            require(self.path.name.endswith('_dir.vpk'), 'Split VPK requires *_dir.vpk filename')
            archive_path = self.path.with_name(self.path.name[:-8] + f'_{archive:03}.vpk')
            require(offset + size <= archive_path.stat().st_size, 'Split VPK payload out of bounds')
        yield from file_chunks(archive_path, offset, size)


def snapshot(source, output, include_source_path=False):
    source, output = source.resolve(), output.resolve()
    require(source != output, 'Output cannot overwrite input')
    files = {}
    if source.is_dir():
        require(not output.is_relative_to(source), 'Place manifest outside scanned directory')
        folded = set()
        for current, dirs, names in os.walk(source, followlinks=False):
            for name in dirs + names:
                require(not linked(Path(current) / name), 'Directory scan refuses symlinks/reparse points')
            for name in sorted(names):
                path = Path(current) / name
                require(path.is_file(), f'Not a regular file: {path}')
                key = safe_name(path.relative_to(source).as_posix())
                require(key.casefold() not in folded, f'Case-colliding resource: {key}')
                folded.add(key.casefold())
                files[key] = digest(file_chunks(path))[0]
        metadata = {'kind': 'directory', 'crc_checked': False}
    else:
        pak = VPK(source)
        for key, entry in sorted(pak.entries.items()):
            record, crc = digest(pak.chunks(entry))
            require(crc == entry[0], f'CRC mismatch: {key}')
            record['crc32'] = f'{crc:08x}'
            files[key] = record
        metadata = {'kind': 'vpk', 'version': pak.version, 'crc_checked': True,
                    'index_file_sha256': digest(file_chunks(source))[0]['sha256'],
                    'package_md5_checked': False}
    source_label = str(source) if include_source_path else (source.name or source.anchor)
    result = {'schema': 1, 'source': source_label,
              'source_path_included': include_source_path,
              **metadata, 'count': len(files),
              'files': dict(sorted(files.items()))}
    write(output, result)
    return {'count': len(files), **metadata}


def read_manifest(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    require(value['schema'] == 1 and value['count'] == len(value['files']), 'Invalid manifest')
    for key, entry in value['files'].items():
        require(safe_name(key) == key and len(entry['sha256']) == 64 and entry['bytes'] >= 0,
                'Invalid manifest entry')
    return value['files']


def compare(args):
    require(args.output.resolve() not in (args.baseline.resolve(), args.candidate.resolve()),
            'Output cannot overwrite a manifest input')
    before, after = read_manifest(args.baseline), read_manifest(args.candidate)
    common = before.keys() & after.keys()
    changes = {
        'added': sorted(after.keys() - before.keys()),
        'removed': sorted(before.keys() - after.keys()),
        'changed': sorted(k for k in common if any(before[k][f] != after[k][f] for f in ('sha256', 'bytes')))
    }
    allowances = {'added': args.allow_add, 'removed': args.allow_remove, 'changed': args.allow_change}
    violations = {kind: [p for p in paths if not any(fnmatch.fnmatchcase(p, pattern) for pattern in allowances[kind])]
                  for kind, paths in changes.items()}
    passed = not any(violations.values())
    report = {'passed': passed, 'unchanged_count': len(common) - len(changes['changed']),
              **changes, 'violations': violations}
    write(args.output, report)
    return report


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    snap = sub.add_parser('snapshot')
    snap.add_argument('--input', required=True, type=Path)
    snap.add_argument('--output', required=True, type=Path)
    snap.add_argument('--include-source-path', action='store_true',
                      help='Record the absolute input path in the report (may expose local details)')
    diff = sub.add_parser('compare')
    diff.add_argument('--baseline', required=True, type=Path)
    diff.add_argument('--candidate', required=True, type=Path)
    diff.add_argument('--output', required=True, type=Path)
    for kind in ('add', 'change', 'remove'):
        diff.add_argument('--allow-' + kind, action='append', default=[])
    args = p.parse_args()
    try:
        report = (snapshot(args.input, args.output, args.include_source_path)
                  if args.command == 'snapshot' else compare(args))
        print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, ensure_ascii=False))
        return 0 if report.get('passed', True) else 1
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        print(f'Audit failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
