from src.client import request

def test_timeout():
    assert request() == 30000
