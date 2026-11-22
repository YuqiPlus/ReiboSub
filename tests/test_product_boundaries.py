"""The website consumes the independently installable subtitle library."""
import ast
from pathlib import Path
import subprocess
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from reibosub import Subtitle
from video_translate.chinese_script import convert_chinese_text

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / 'packages/subtitles'


def test_two_independent_products_and_one_way_dependency():
    web = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    lib = tomllib.loads((TOOLKIT / 'pyproject.toml').read_text())
    assert web['project']['name'] == 'reibosub-web'
    assert lib['project']['name'] == 'reibosub'
    assert 'reibosub>=0.1.0,<0.2' in web['project']['dependencies']
    assert web['tool']['setuptools']['packages']['find']['include'] == ['video_translate*']
    assert lib['tool']['setuptools']['packages']['find']['where'] == ['src']
    assert set(lib['project']['optional-dependencies']) == {'dev', 'asr', 'ocr', 'ocr-cpu', 'video'}
    assert set(lib['project']['scripts']) == {'reibosub'}
    assert lib['tool']['pytest']['ini_options']['testpaths'] == ['tests']
    assert (TOOLKIT / 'README.md').exists() and (TOOLKIT / 'tests').is_dir()


def test_toolkit_never_imports_application_or_recognition_code():
    forbidden = {'video_translate', 'frontend', 'requests', 'yaml', 'redis', 'pymysql', 'paddle', 'paddleocr', 'cv2', 'faster_whisper'}
    for source in (TOOLKIT / 'src/reibosub').glob('*.py'):
        tree = ast.parse(source.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.append(node.module.split('.')[0])
        assert not forbidden.intersection(imports), source


def test_website_reuses_public_chinese_conversion(monkeypatch):
    calls = []
    original = Subtitle.to_simplified
    def spy(self, **kwargs):
        calls.append(self[0].text)
        return original(self, **kwargs)
    monkeypatch.setattr(Subtitle, 'to_simplified', spy)
    assert convert_chinese_text('繁體字幕', 'simplified') == '繁体字幕'
    assert calls == ['繁體字幕']
    assert convert_chinese_text('繁體字幕', 'original') == '繁體字幕'
    assert len(calls) == 1


def test_source_compatibility_and_toolkit_use_same_types():
    import reibosub
    from reibosub.models import Cue
    from reibosub import Cue as public
    assert Cue is public
    assert Path(sys.modules['reibosub.models'].__file__).is_relative_to(TOOLKIT)
    assert reibosub.__version__ == tomllib.loads((TOOLKIT / 'pyproject.toml').read_text())['project']['version']


def test_source_compatibility_cli_is_still_available_without_website(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'reibosub.cli', '--help'], cwd=ROOT, capture_output=True, text=True, check=True)
    assert 'convert' in result.stdout and 'extract' not in result.stdout
