def _first(values):
    return values[0]


def first_positive(values):
    selected = [value for value in values if value > 0]
    if not selected:
        return None
    return _first(selected)
