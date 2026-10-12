import os

import pytest

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
