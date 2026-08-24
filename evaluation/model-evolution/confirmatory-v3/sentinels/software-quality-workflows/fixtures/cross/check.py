from consumer import consume
from producer import produce

assert produce('7') == {'schema': 2, 'user_id': 7}
assert consume(produce('7')) == 7
try:
    consume({'schema': 1, 'user_id': 7})
except ValueError:
    pass
else:
    raise AssertionError('schema boundary missing')
print('CROSS_OK')
