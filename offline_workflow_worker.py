"""Internal single-use shim for the exact owned ScriptedDemo command, no models."""

import argparse
import http.client
import socket
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

import agent
from agent import Refused, canonical, sha
from offline_workflow import _json, _new, _read, _root, _directory, _metadata_matches, expected_command, require, validate_fixture


def run_worker(work_dir, run_id, arguments):
    _root(work_dir);os.close(_directory(work_dir));os.close(_directory(work_dir/"receipts"))
    command=expected_command(work_dir,run_id)
    require(type(arguments) is list and arguments==command[3:],"ARGV")
    # The parent confirms its normal metadata transition before the child reads
    # runtime state. This avoids racing the unchanged Manager's atomic replace.
    deadline=time.monotonic()+10
    while (not (work_dir/"receipts/parent-started.json").exists()
           or (work_dir/"receipts/parent-started.json.next").exists()):
        require(time.monotonic()<deadline,"PARENT_UNSETTLED");time.sleep(0.01)
    marker=validate_fixture(work_dir)
    launch=_json(work_dir,"receipts/launch.json");claim=_json(work_dir,"receipts/start-claim.json")
    require(launch.get("argv")==command and launch.get("id")==run_id
            and launch.get("fixture_id")==marker["fixture_id"]==claim.get("fixture_id")
            and launch.get("task_sha256")==sha(canonical(_json(work_dir,"workspace/task.json"))),"CLAIM")
    meta=_json(work_dir,"workspace/data/jobs/"+run_id+".json")
    _metadata_matches(work_dir,marker,run_id,meta)
    parent=_json(work_dir,"receipts/parent-started.json")
    require(set(parent)=={"version","id","fixture_id","pid"} and type(parent["version"]) is int and parent["version"]==1
            and parent["id"]==run_id and parent["fixture_id"]==marker["fixture_id"]
            and type(parent["pid"]) is int and parent["pid"]==os.getpid() and meta.get("pid")==os.getpid()
            and _json(work_dir,"workspace/data/tasks/"+run_id+".json")==_json(work_dir,"workspace/task.json"),"SCRIPTED_ONLY")
    _new(work_dir/"receipts/worker-start.json",{"version":1,"id":run_id,"fixture_id":marker["fixture_id"],"pid":os.getpid()})
    counts={"provider_attempts":0,"network_attempts":0};code=2
    def block_provider(*_args,**_kwargs):counts["provider_attempts"]+=1;raise Refused("OFFLINE_WORKFLOW_PROVIDER_REFUSED")
    def block_network(*_args,**_kwargs):counts["network_attempts"]+=1;raise Refused("OFFLINE_WORKFLOW_NETWORK_REFUSED")
    try:
        with ExitStack() as stack:
            for target in ["agent.Ollama.request","agent.Ollama.preflight"]:stack.enter_context(patch(target,block_provider))
            for target in ["http.client.HTTPConnection.connect","http.client.HTTPSConnection.connect","socket.socket.connect","socket.socket.connect_ex","socket.create_connection","socket.getaddrinfo","socket.gethostbyname","socket.gethostbyname_ex","socket.gethostbyaddr","socket.getnameinfo","socket.socket.send","socket.socket.sendall","socket.socket.sendto"]:stack.enter_context(patch(target,block_network))
            if hasattr(socket.socket,"sendmsg"):stack.enter_context(patch("socket.socket.sendmsg",block_network))
            code=agent.main(arguments)
        return code
    finally:
        _new(work_dir/"receipts/worker-exit.json",{"version":1,"id":run_id,"fixture_id":marker["fixture_id"],"pid":os.getpid(),"exit_code":code,**counts,
              "python_level_guards":True,"os_wide_packet_audit":False})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--work-dir",type=Path,required=True);parser.add_argument("--run-id",required=True);parser.add_argument("arguments",nargs=argparse.REMAINDER)
    args=parser.parse_args(argv);arguments=args.arguments[1:] if args.arguments[:1]==["--"] else args.arguments
    def interrupted(*_args):raise KeyboardInterrupt
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:return run_worker(args.work_dir,args.run_id,arguments)
    finally:signal.signal(signal.SIGTERM,previous)


if __name__=="__main__":
    try:raise SystemExit(main())
    except (Refused,OSError,ValueError,KeyError,TypeError):
        print('{"status":"REFUSED","reason":"OFFLINE_WORKFLOW_WORKER_REFUSED"}');raise SystemExit(2)
