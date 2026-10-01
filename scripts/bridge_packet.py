"""Validate AZ/Codex packets and persist a one-owner ledger. Never executes tasks."""
import argparse, copy, hashlib, json, os, pathlib, re, stat, sys, uuid
PROTOCOL = "az-codex/1"
TERMINAL_STATES = ("complete","partial","blocked","uncertain","cancelled","failed")

def sha256(payload):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def canonical(requests,rid):
    seen=set()
    while requests[rid].get("alias_request_id"):
        if rid in seen:raise ValueError("alias cycle")
        seen.add(rid);rid=requests[rid]["alias_request_id"]
    return rid,requests[rid]

def validate(p, contract):
    fields = ("protocol","kind","sender","receiver","request_id","operation_key","payload",
              "payload_sha256","request_sha256","contract_sha256")
    if not isinstance(p,dict) or any(not isinstance(p.get(f),str) or not p[f] for f in fields):
        raise ValueError("missing or invalid packet field")
    if p["protocol"] != PROTOCOL or p["kind"] not in ("request","result","ack","cancel"):
        raise ValueError("unsupported protocol or kind")
    if p["contract_sha256"] != contract:
        raise ValueError("contract hash mismatch")
    for f in ("payload_sha256","request_sha256","contract_sha256"):
        if not re.fullmatch("[0-9a-f]{64}",p[f]):
            raise ValueError("invalid hash: "+f)
    if sha256(p["payload"]) != p["payload_sha256"]:
        raise ValueError("payload hash mismatch")
    body=json.loads(p["payload"])
    if not isinstance(body,dict):
        raise ValueError("payload must decode to an object")
    expected=("codex","az") if p["kind"]=="result" else ("az","codex")
    if (p["sender"],p["receiver"]) != expected:
        raise ValueError("wrong sender or receiver")
    if p["kind"]=="request":
        if p["request_sha256"] != p["payload_sha256"] or not isinstance(body.get("objective"),str) or not body["objective"]:
            raise ValueError("invalid request objective or hash")
    if p["kind"]=="ack" and (not isinstance(p.get("result_sha256"),str)
                              or not re.fullmatch("[0-9a-f]{64}",p["result_sha256"])):
        raise ValueError("ack lacks result hash")
    return body

def validate_ledger(state):
    """Check persisted suppression evidence without repairing or normalizing it."""
    def require(condition,reason):
        if not condition:raise ValueError("invalid ledger; reconciliation required: "+reason)
    def nonempty(value):return isinstance(value,str) and bool(value)
    def digest(value):return isinstance(value,str) and bool(re.fullmatch("[0-9a-f]{64}",value))
    require(isinstance(state,dict),"top level")
    require(type(state.get("schema_version")) is int and state["schema_version"]==1,"schema version")
    requests=state.get("requests");operations=state.get("operations")
    require(isinstance(requests,dict) and isinstance(operations,dict),"required mappings")
    for rid,record in requests.items():
        require(nonempty(rid) and isinstance(record,dict),"request record")
        require(record.get("state") in ("queued","executing","operation_reuse",*TERMINAL_STATES),"state")
        require(nonempty(record.get("operation_key")) and digest(record.get("request_sha256")),"request correlation")
        require(type(record.get("executions")) is int and record["executions"] in (0,1),"execution count")
        require((record["state"]=="operation_reuse")==("alias_request_id" in record),"alias marker")
        if "legacy_completion" in record:
            require(record["legacy_completion"] is True and record["state"]=="complete"
                    and "alias_request_id" not in record,"legacy marker")
        if "alias_request_id" in record:
            require(nonempty(record["alias_request_id"]) and record["state"]=="operation_reuse"
                    and record["executions"]==0,"alias state")
            require(not any(field in record for field in ("owner","result","ack","delivery")),"alias effect ownership")
        else:
            require(operations.get(record["operation_key"])==rid,"missing canonical index")
            if record["state"]=="queued":
                require(record["executions"]==0 and "owner" not in record and "result" not in record,"queued claim")
            elif record["state"]=="cancelled" and record["executions"]==0:
                require("owner" not in record and "result" not in record and "cancel_packet" in record,"cancel tombstone")
            elif record.get("legacy_completion") is True:
                require(record["state"]=="complete" and record["executions"]==1
                        and all(nonempty(record.get(f)) for f in ("verified_outcome","receipt_reference","note"))
                        and not any(f in record for f in ("packet","owner","result","ack","delivery")),"legacy completion evidence")
            else:
                require(record["executions"]==1 and nonempty(record.get("owner")),"active or terminal owner")
                require(record["state"] in ("executing","uncertain") or "result" in record,"terminal result")
                require(record["state"]!="executing" or "result" not in record,"executing result")
    for key,rid in operations.items():
        require(nonempty(key) and nonempty(rid) and rid in requests,"operation target")
        record=requests[rid]
        require("alias_request_id" not in record and record["operation_key"]==key,"canonical operation target")
    roots={}
    for rid,record in requests.items():
        try:root,_=canonical(requests,rid)
        except (KeyError,ValueError):raise ValueError("invalid ledger; reconciliation required: alias path") from None
        require(operations.get(record["operation_key"])==root,"alias operation index")
        roots[rid]=root
    for rid,record in requests.items():
        if "cancellation_requested" in record:
            require(type(record["cancellation_requested"]) is bool,"cancellation flag")
        if "cancel_packet" in record or record.get("cancellation_requested") is True:
            require(requests[roots[rid]]["state"]!="queued","queued cancellation contradiction")
    def envelope(value,kind,rid):
        require(isinstance(value,dict) and value.get("kind")==kind,"stored envelope kind")
        try:body=validate(value,value.get("contract_sha256"))
        except (ValueError,TypeError):raise ValueError("invalid ledger; reconciliation required: stored envelope") from None
        record=requests[rid]
        require(value["request_id"]==rid and value["operation_key"]==record["operation_key"]
                and value["request_sha256"]==record["request_sha256"],"stored envelope correlation")
        return body
    for rid,record in requests.items():
        if "packet" in record:envelope(record["packet"],"request",rid)
        elif not record.get("legacy_completion"):
            require("cancel_packet" in record and ("alias_request_id" in record
                    or (record["state"]=="cancelled" and record["executions"]==0)),"missing request evidence")
        if "cancel_packet" in record:
            cancel=record["cancel_packet"]
            require(isinstance(cancel,dict) and cancel.get("request_id") in requests,"cancel reference")
            target=cancel["request_id"];envelope(cancel,"cancel",target)
            require(roots[target]==roots[rid],"cancel operation root")
        result=record.get("result")
        if "result" in record:
            body=envelope(result,"result",rid);status=body.get("domain_status")
            require(status in TERMINAL_STATES,"result status")
            require(record["state"]==status or (record["state"]=="cancelled" and status in ("failed","blocked")
                    and "cancel_packet" in record),"result state")
            require(result["contract_sha256"]==record["packet"]["contract_sha256"],"result contract")
        if "ack" in record:
            require(isinstance(result,dict),"ACK without result")
            envelope(record["ack"],"ack",rid)
            require(record["ack"]["result_sha256"]==result["payload_sha256"]
                    and record["ack"]["contract_sha256"]==result["contract_sha256"],"ACK result")
        if "delivery" in record:
            delivery=record["delivery"]
            require(isinstance(result,dict) and isinstance(delivery,dict),"delivery without result")
            require(delivery.get("status") in ("sending","sent","uncertain")
                    and delivery.get("owner")==record.get("owner")
                    and delivery.get("result_sha256")==result["payload_sha256"]
                    and type(delivery.get("attempts")) is int and delivery["attempts"]==1,"delivery correlation")
            if delivery["status"]!="sending":
                require(isinstance(delivery.get("receipt"),(str,dict)) and bool(delivery["receipt"]),"delivery receipt")

def apply_event(state,p,contract,source_thread,expected_source):
    validate_ledger(state)
    if source_thread != expected_source:
        raise ValueError("wrong authenticated source thread")
    body=validate(p,contract)
    if p["kind"]=="result":
        raise ValueError("incoming AZ event cannot be a Codex result")
    s=copy.deepcopy(state)
    requests=s["requests"]; operations=s["operations"]
    rid=p["request_id"]; key=p["operation_key"]; h=p["request_sha256"]; old=requests.get(rid)
    if old and (old["request_sha256"] != h or old["operation_key"] != key):
        return s,{"action":"conflict","request_id":rid}
    if p["kind"]=="request":
        if old:
            original,current=canonical(requests,rid)
            return s,{"action":"cancelled" if current["state"]=="cancelled" else "duplicate","request_id":rid,
                      "original_request_id":original,"state":current["state"],"result":current.get("result")}
        if key in operations:
            original=operations[key]
            requests[rid]={"state":"operation_reuse","operation_key":key,"request_sha256":h,
                           "executions":0,"alias_request_id":original,"packet":p}
            return s,{"action":"operation_reuse","request_id":rid,"original_request_id":original,
                      "state":requests[original]["state"],"result":requests[original].get("result")}
        requests[rid]={"state":"queued","operation_key":key,"request_sha256":h,"executions":0,"packet":p}
        operations[key]=rid
        return s,{"action":"queued","request_id":rid}
    if p["kind"]=="cancel":
        if not old and key in operations:
            original=operations[key]
            old=requests[rid]={"state":"operation_reuse","operation_key":key,"request_sha256":h,
                               "executions":0,"alias_request_id":original,"cancel_packet":p}
        if old and old.get("alias_request_id"):
            original,current=canonical(requests,rid)
            old["cancellation_requested"]=True
            if current["state"]=="complete":
                return s,{"action":"already_complete","request_id":rid,"original_request_id":original,"result":current.get("result")}
            if current["state"] in ("queued","cancelled"):
                current.update(state="cancelled",cancel_packet=p,cancellation_requested=True)
                return s,{"action":"cancelled","request_id":rid,"original_request_id":original}
            current["cancellation_requested"]=True
            return s,{"action":"reconcile_cancellation","request_id":rid,"original_request_id":original}
        if old and old["state"]=="complete":
            return s,{"action":"already_complete","request_id":rid,"result":old.get("result")}
        if old and old["state"] in ("executing","uncertain","partial"):
            old["cancellation_requested"]=True
            return s,{"action":"reconcile_cancellation","request_id":rid}
        if old and old["state"]=="cancelled":
            return s,{"action":"duplicate_cancel_no_reply","request_id":rid}
        requests[rid]={**(old or {}),"state":"cancelled","operation_key":key,"request_sha256":h,
                       "executions":(old or {}).get("executions",0),"cancel_packet":p}
        operations.setdefault(key,rid)
        return s,{"action":"cancelled","request_id":rid}
    if not old or not old.get("result") or old["result"]["payload_sha256"] != p["result_sha256"]:
        return s,{"action":"unmatched_ack_no_reply","request_id":rid}
    if old.get("ack"):
        return s,{"action":"duplicate_ack_no_reply","request_id":rid}
    old["ack"]=p
    return s,{"action":"acknowledged_no_reply","request_id":rid}

def begin(state,rid,owner):
    validate_ledger(state)
    if not isinstance(owner,str) or not owner:raise ValueError("execution owner required")
    s=copy.deepcopy(state); old=s["requests"][rid]
    if old.get("alias_request_id"):
        original,current=canonical(s["requests"],rid)
        return s,{"action":"reuse_result" if current["state"]=="complete" else "reconcile","request_id":rid,
                  "original_request_id":original,"state":current["state"],"result":current.get("result")}
    if old["state"]!="queued":
        return s,{"action":"reuse_result" if old["state"]=="complete" else "reconcile","request_id":rid,
                  "state":old["state"],"result":old.get("result")}
    old.update(state="executing",owner=owner,executions=old["executions"]+1)
    return s,{"action":"execute_once","request_id":rid}

def finish(state,rid,p,owner,contract):
    validate_ledger(state)
    body=validate(p,contract); s=copy.deepcopy(state); old=s["requests"][rid]
    if (p["kind"]!="result" or p["request_id"]!=rid or p["operation_key"]!=old["operation_key"]
        or p["request_sha256"]!=old["request_sha256"] or old.get("owner")!=owner or old["state"]!="executing"):
        raise ValueError("result does not match active owner/request")
    status=body.get("domain_status")
    if status not in TERMINAL_STATES:
        raise ValueError("invalid domain_status")
    old.update(state=status,result=p)
    return s,{"action":"result_persisted","request_id":rid,"domain_status":status}

def prepare_send(state,rid,owner):
    validate_ledger(state)
    s=copy.deepcopy(state);old=s["requests"][rid]
    if old.get("owner")!=owner or not old.get("result"):
        raise ValueError("send requires result and matching execution owner")
    delivery=old.get("delivery")
    if delivery:
        return s,{"action":"reuse_send_receipt" if delivery["status"]=="sent" else "reconcile_send",
                  "request_id":rid,"delivery":delivery}
    if old.get("ack"):
        return s,{"action":"acknowledged_no_send","request_id":rid}
    old["delivery"]={"status":"sending","owner":owner,"attempts":1,"result_sha256":old["result"]["payload_sha256"]}
    return s,{"action":"send_once","request_id":rid,"result":old["result"]}

def record_delivery(state,rid,owner,receipt):
    validate_ledger(state)
    s=copy.deepcopy(state);old=s["requests"][rid];delivery=old.get("delivery")
    if (not delivery or old.get("owner")!=owner or delivery.get("owner")!=owner
        or not isinstance(receipt,dict) or receipt.get("status") not in ("sent","uncertain")
        or receipt.get("result_sha256")!=old["result"]["payload_sha256"]
        or not isinstance(receipt.get("receipt"),(str,dict)) or not receipt["receipt"]):
        raise ValueError("delivery receipt does not match owner/result")
    if delivery["status"]=="sent":
        return s,{"action":"reuse_send_receipt","request_id":rid,"delivery":delivery}
    delivery.update(status=receipt["status"],receipt=receipt["receipt"])
    return s,{"action":"delivery_persisted","request_id":rid,"delivery":delivery}

def read_json(path):
    return json.loads(pathlib.Path(path).read_bytes().decode("utf-8"))

def replace_windows_file(source,destination):
    """Preserve target protection; leave recovery evidence on a native failure."""
    import ctypes
    from ctypes import wintypes
    backup=destination.with_name(destination.name+"."+uuid.uuid4().hex+".recovery")
    replace=ctypes.WinDLL("kernel32",use_last_error=True).ReplaceFileW
    replace.argtypes=(wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,
                      wintypes.DWORD,wintypes.LPVOID,wintypes.LPVOID)
    replace.restype=wintypes.BOOL
    if not replace(str(destination.resolve()),str(source.resolve()),str(backup.resolve()),0,None,None):
        error=ctypes.get_last_error()
        raise OSError(error,"Windows replacement failed; inspect target and retained recovery evidence; "+str(backup))
    backup.unlink()

def replace_state_file(source,destination):
    if os.name=="nt" and destination.exists():
        replace_windows_file(source,destination)
    else:os.replace(source,destination)

def write_json(path,value):
    path=pathlib.Path(path); path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    previous=path.lstat() if path.exists() or path.is_symlink() else None
    if previous and not stat.S_ISREG(previous.st_mode):raise ValueError("ledger must be a regular file")
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    keep_temp=False
    try:
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:
            if os.name=="posix" and previous:os.fchmod(f.fileno(),stat.S_IMODE(previous.st_mode))
            json.dump(value,f,ensure_ascii=False,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
        try:replace_state_file(tmp,path)
        except OSError:
            keep_temp=any(path.parent.glob(path.name+".*.recovery"))
            raise
    finally:
        if tmp.exists() and not keep_temp:tmp.unlink()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("hash","validate","event","begin","finish","prepare_send","delivery"))
    parser.add_argument("--packet"); parser.add_argument("--ledger"); parser.add_argument("--contract")
    parser.add_argument("--source-thread"); parser.add_argument("--expected-source")
    parser.add_argument("--request-id"); parser.add_argument("--owner")
    a=parser.parse_args()
    if a.action=="hash":
        if not a.packet: parser.error("--packet required (UTF-8 payload file)")
        print(sha256(pathlib.Path(a.packet).read_bytes().decode("utf-8"))); return
    if not a.contract and a.action not in ("begin","prepare_send","delivery"): parser.error("--contract required")
    if a.action=="validate":
        validate(read_json(a.packet),a.contract); print(json.dumps({"valid":True})); return
    if not a.ledger: parser.error("--ledger required")
    path=pathlib.Path(a.ledger);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=path.with_name(path.name+".lock")
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise ValueError("ledger locked; inspect owner, do not spin or remove blindly")
    retain_lock=False
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump({"pid":os.getpid(),"owner":a.owner},f)
        if any(path.parent.glob(path.name+".*.recovery")):
            raise ValueError("ledger recovery evidence present; reconcile before initialization or mutation")
        state=read_json(path) if path.exists() else {"schema_version":1,"requests":{},"operations":{}}
        validate_ledger(state)
        if a.action=="event":
            if not a.source_thread or not a.expected_source:parser.error("source identifiers required")
            state,decision=apply_event(state,read_json(a.packet),a.contract,a.source_thread,a.expected_source)
        elif a.action=="begin":
            if not a.request_id or not a.owner:parser.error("request and owner required")
            state,decision=begin(state,a.request_id,a.owner)
        elif a.action=="finish":
            if not a.request_id or not a.owner:parser.error("request and owner required")
            state,decision=finish(state,a.request_id,read_json(a.packet),a.owner,a.contract)
        elif a.action=="prepare_send":
            if not a.request_id or not a.owner:parser.error("request and owner required")
            state,decision=prepare_send(state,a.request_id,a.owner)
        else:
            if not a.request_id or not a.owner:parser.error("request and owner required")
            state,decision=record_delivery(state,a.request_id,a.owner,read_json(a.packet))
        validate_ledger(state)
        try:write_json(path,state)
        except OSError:
            retain_lock=True
            raise
        print(json.dumps(decision,ensure_ascii=True))
    finally:
        if not retain_lock:lock.unlink()

if __name__=="__main__":
    try:main()
    except (ValueError,KeyError,OSError,json.JSONDecodeError) as e:
        print(json.dumps({"error":str(e)},ensure_ascii=True),file=sys.stderr);sys.exit(2)

