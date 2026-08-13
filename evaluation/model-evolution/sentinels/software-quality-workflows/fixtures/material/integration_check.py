from auth import authorized

assert authorized('secret', 'secret')
print('INTEGRATION_OK')
