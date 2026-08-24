from parser import parse_names

def test_contract():
    assert parse_names([' Ada ', '', 'Bob']) == ['Ada', 'Bob']
