from src.legacy import legacy_parse

def test_legacy():
    assert legacy_parse('a,b') == ['a', 'b']
