__base_version__ = "0.2"
try:                                    # written by the Windows build (CI run number); absent in a dev checkout
    from ._build import BUILD
except ImportError:                     # pragma: no cover
    BUILD = 0
__version__ = f"{__base_version__}.{BUILD}"
