"""Keep public install dependencies and channel selection reproducible."""
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
    assert 'nodejs>=22.12' in dependencies
    pip = next(row['pip'] for row in dependencies if isinstance(row, dict) and 'pip' in row)
    assert '-e .[web,ocr-cpu,asr]' in pip


def test_conda_environment_uses_only_forge_and_disables_default_channels():
    environment = yaml.safe_load((ROOT / 'environment.yml').read_text())
    assert environment['channels'] == ['conda-forge', 'nodefaults']
    assert 'python=3.11' in environment['dependencies']
    assert 'nodejs>=22.12' in environment['dependencies']
    assert 'ffmpeg' in environment['dependencies']


def test_manual_conda_commands_override_channels_in_both_readmes():
    for name in ('README.md', 'README.zh-CN.md'):
        text = (ROOT / name).read_text()
        commands = re.findall(r'^conda create .+$', text, re.M)
        assert commands, name
        assert not re.search(r'^conda env create ', text, re.M), name
        for command in commands:
            assert '--override-channels -c conda-forge' in command, (name, command)
            assert 'nodejs>=22.12' in command, (name, command)
        assert 'npm ci --include=dev' in text
