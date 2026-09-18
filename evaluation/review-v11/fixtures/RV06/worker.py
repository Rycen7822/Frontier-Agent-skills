def _use(handle, callback):
    return callback(handle)


def process(opener, callback):
    handle = opener()
    try:
        return _use(handle, callback)
    finally:
        handle.close()
