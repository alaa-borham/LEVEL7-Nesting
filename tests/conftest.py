import os

import pytest

# the regular tests check LEVEL7's own (deterministic) engine; the sparrow engine has its own test
os.environ.setdefault("LEVEL7_ENGINE", "builtin")

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "..", "samples")
MDL = os.path.join(SAMPLES, "Neay blue pants.mdl")
SCB = os.path.join(SAMPLES, "Neay blue pants-44.scb")


@pytest.fixture(scope="session")
def mdl():
    from level7.readers.grafis import read_grafis
    return read_grafis(MDL)


@pytest.fixture(scope="session")
def scb():
    from level7.readers.grafis import read_grafis
    return read_grafis(SCB)
