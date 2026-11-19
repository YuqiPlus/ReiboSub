"""Keep the published starter installation aligned with downloader needs."""
from pathlib import Path
import re

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def test_downloader_installs_its_javascript_challenge_components():
    metadata = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r'^\s*"(yt-dlp[^\"]*)",?$', metadata, re.M)
    assert match is not None
    dependency = Requirement(match.group(1))
    assert dependency.name == 'yt-dlp'
    assert 'default' in dependency.extras


def test_starter_environment_provides_tools_and_both_cpu_engines():
    environment = yaml.safe_load((ROOT / 'environment.yml').read_text(encoding='utf-8'))
    dependencies = environment['dependencies']
    assert 'python=3.11' in dependencies
    assert 'ffmpeg' in dependencies
    assert 'nodejs>=22' in dependencies
    pip = next(row['pip'] for row in dependencies if isinstance(row, dict) and 'pip' in row)
    assert '-e .[asr,ocr-cpu]' in pip
