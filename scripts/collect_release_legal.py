"""Collect exact installed notices and AGPL dependency source for each build."""
from __future__ import annotations
import hashlib
import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()

def main() -> None:
    legal = ROOT / 'app/ui/web/legal'
    legal.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'LICENSE', legal / 'LICENSE.txt')
    shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', legal / 'THIRD_PARTY_NOTICES.txt')
    rows = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name, version = dist.metadata['Name'], dist.version
        rows.append({'name': name, 'version': version, 'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', ''), 'project_urls': dist.metadata.get_all('Project-URL') or []})
        for item in dist.files or ():
            if any(word in item.name.lower() for word in ('license', 'copying', 'notice', 'copyright')):
                src = Path(dist.locate_file(item))
                if src.is_file() and src.suffix not in ('.py', '.pyc', '.so', '.pyd'):
                    dest = legal / 'dependencies' / name / str(item).replace('..', '_')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
    (legal / 'dependencies.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    # Keep model-card declarations in the distribution, at exact pinned revisions.
    from app.vision.model_manifest import CATALOG
    for model in CATALOG:
        if model.huggingface_id:
            url = f'https://huggingface.co/{model.huggingface_id}/raw/{model.revision}/README.md'
            (legal / f'{model.id}-model-card.md').write_bytes(download(url))
    # Exact source distributions for directly integrated copyleft dependencies.
    target = ROOT / 'release-sources'
    target.mkdir(exist_ok=True)
    manifest = []
    copyleft = {'nudenet', 'ultralytics'}
    for dist in metadata.distributions():
        terms = ' '.join((str(dist.metadata.get('License', '')),
                          str(dist.metadata.get('License-Expression', '')),
                          *dist.metadata.get_all('Classifier', [])))
        if 'AGPL' in terms or 'Affero' in terms:
            copyleft.add(dist.metadata['Name'])
    for name in sorted(copyleft):
        version = metadata.version(name)
        info = json.loads(download(f'https://pypi.org/pypi/{name}/{version}/json'))
        source = next(f for f in info['urls'] if f['packagetype'] == 'sdist')
        data = download(source['url'])
        assert hashlib.sha256(data).hexdigest() == source['digests']['sha256']
        (target / source['filename']).write_bytes(data)
        manifest.append({'name': name, 'version': version, 'url': source['url'], 'sha256': source['digests']['sha256']})
    (target / 'sources.json').write_text(json.dumps(manifest, indent=2))
    with zipfile.ZipFile(ROOT / f'LAVOCADO-{platform.system()}-Dependency-Sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in target.iterdir():
            archive.write(path, path.name)

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    main()
