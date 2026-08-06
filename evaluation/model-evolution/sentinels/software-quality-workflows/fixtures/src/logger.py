def log_request(request, debug):
    debug.write(request.headers['Authorization'])
