from app import normalize_name

assert normalize_name('  Ada  ') == 'Ada'
print('TARGET_OK')
