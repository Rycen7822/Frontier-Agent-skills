def legacy_parse(text):
    return text.split(',')

def parse_v2(text):
    return [item.strip() for item in text.split(',')]
