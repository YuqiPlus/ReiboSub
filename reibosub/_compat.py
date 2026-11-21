"""Transition bridge for processes which imported the former source-tree layout."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def redirect(name):
    path = Path(__file__).resolve().parents[1] / "packages/subtitles/src/reibosub" / (name.rsplit(".", 1)[-1] + ".py")
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
