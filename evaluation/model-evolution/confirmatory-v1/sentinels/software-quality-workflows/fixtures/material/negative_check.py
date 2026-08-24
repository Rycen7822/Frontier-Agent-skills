from auth import authorized

assert not authorized('wrong', 'secret')
print('NEGATIVE_OK')
