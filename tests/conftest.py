import pytest

from wfengine import Dictionary, load_rules

# Liten testordlista. Testerna ska inte bero på den riktiga ordlistan.
TEST_WORDS = """
HUS HUSET HUSEN HAT HATT HATTEN AT ATT TA TAR TAS SE SER SET ES ER EN ET
EL ELD BAD BADA BADAR BAR BARN BARNEN DE DEN DET DU NU NE NO NOT SO SOL SOLEN
OS OST OSTEN LO LOS LOT TO TOR TOT RO ROT ROS ROSEN SÅ SÅG SÅR ÅR ÅT ÄR ÄT
ÖL ÖRA ÖRAT AL ALE ALT LA LAS LAT LATE SAL SALT SALTA TAL TALA TALAR RA RAS
ANDE ANDAS ANSE ANSER RAST RASTA STA STAR STAT STATS TASS TESTA SATT SATTE
ARE ARTEN ART TALANG ATTRAPS STATARE
""".split()


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def small_dict(rules):
    return Dictionary.from_words(TEST_WORDS, rules.alphabet)
