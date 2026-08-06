def charge(client, payment):
    return client.retry(lambda: client.post('/charge', payment))
