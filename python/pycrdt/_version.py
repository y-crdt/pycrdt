from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pycrdt")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "uninstalled"
