"""Optional local format exports. Never overwrite an existing different file."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

from video_translate.subtitle.convert import convert_subtitle_file


def copy_delivery_file(source: Path, destination: Path, *, version: str) -> Path:
    """Publish a complete copy; keep differing, possibly user-edited sidecars."""
    source, destination = source.resolve(), destination.resolve()
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:12]
    version = ''.join(c for c in version if c.isalnum() or c in '-_')[:48] or digest
    alternatives = (destination, destination.with_name(f'{destination.stem}.run_{version}{destination.suffix}'),
                    destination.with_name(f'{destination.stem}.{digest}{destination.suffix}'))
    with tempfile.TemporaryDirectory(prefix='.subtitle-copy-', dir=destination.parent) as folder:
        temporary = Path(folder) / 'copy'
        temporary.write_bytes(content)
        for target in alternatives:
            try:
                os.link(temporary, target)
                return target
            except FileExistsError:
                if target.read_bytes() == content:
                    return target
    raise FileExistsError('字幕副本目标已有不同内容，未覆盖旧文件。')


def export_bcc(source: Path) -> Path:
    source = source.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix='.bcc-export-', dir=source.parent) as folder:
        temporary = Path(folder) / 'export.bcc'
        convert_subtitle_file(source, temporary, output_format='bcc')
        content = temporary.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        for destination in (source.with_suffix('.bcc'), source.with_name(f'{source.stem}.{digest}.bcc')):
            try:
                os.link(temporary, destination)  # Atomic and exclusive, unlike replace().
                return destination
            except FileExistsError:
                if destination.read_bytes() == content:
                    return destination
        raise FileExistsError('BCC 目标已有不同内容，未覆盖；SRT 保持不变。')
