async def run_once(lock, operation):
    await lock.acquire()
    result = await operation()
    lock.release()
    return result
