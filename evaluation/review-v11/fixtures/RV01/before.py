def read_record(records, record_id, actor_id):
    record = records[record_id]
    if record["owner_id"] != actor_id:
        raise PermissionError("record is not owned by actor")
    return record["payload"]
