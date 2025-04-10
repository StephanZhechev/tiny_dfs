import sys, time, threading, logging, os, math
from typing import List
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
import uvicorn

from src.master_node import MasterNode, get_chunk_assignment, NoSuchClientError, \
    NoSuchFileError
from src.schemas import GetChunkAssignmentRequest, ChunkAssignmentResponse, \
    LogEntry, WriteConfirmation, DeleteRequest

CHUNK_SIZE = 65536
CURRENT_LOG_ID: int # This will be overwritten when the script is run.

logging.basicConfig(level=logging.INFO)

# Global variable for the master node instance.
node = None

# keys are write IDs and values are log entries.
pending_writes = {}
# keys are write IDs and values are lists of pending chunk write confirmations.
pending_confirmations = {}

# "If in doubt keep em locked" - Austrian proverb.
PENDING_RESOURCES_LOCK = threading.Lock()
LOG_ID_LOCK = threading.Lock()

# FastAPI app for exposing the status endpoint.
app = FastAPI()

# if not os.path.exists("/home/data/"):
if not os.path.exists("/home/data/log.jsonl"):
    raise ValueError(r"/home/data/log.jsonl is missing!")

@app.get("/status")
def get_status():
    global node
    try:
        status = node.getStatus()
        # Use _isLeader() if isLeader() is private.
        leader_flag = node._isLeader() if hasattr(node, '_isLeader') else node.isLeader()
        return {
            "uptime": status.get("uptime", None),
            "isLeader": leader_flag,
            "leader": status.get("leader", None)
            }
    except Exception as e:
        return {"error": str(e)}

@app.post("/get_chunk_assignment", response_model=ChunkAssignmentResponse)
async def chunk_assignment_endpoint(req: GetChunkAssignmentRequest):
    """
    In our current model, the client queries the master for metadata, then
    directly passes the file to the reverse proxy with the metadata provided.
    """
    chunk_cnt = math.ceil(req.file_size / CHUNK_SIZE)
    res = await get_chunk_assignment(chunk_cnt, req.client_name, req.file_name)
    return {
        "chunk_size": CHUNK_SIZE,
        "chunk_assignment": res,
    }

@app.post("/propose_write")
async def propose_write(proposal: LogEntry):
    global CURRENT_LOG_ID # Without this line, the next line raises ASGI UnboundLocalError.
    with LOG_ID_LOCK:
        CURRENT_LOG_ID += 1
        write_id = CURRENT_LOG_ID
    timestamp = int(time.time())

    entry = {
        "id": write_id,
        "client": proposal.client,
        "file_name": proposal.file_name,
        "file_size": proposal.file_size,
        "num_chunks": len(proposal.chunks),
        "timestamp": timestamp,
        "operation": "write",
        "chunks": [chunk.model_dump() for chunk in proposal.chunks],
    }
    with PENDING_RESOURCES_LOCK:
        pending_writes[write_id] = entry
        pending_confirmations[write_id] = [elem.chunk_id for elem in proposal.chunks]

    # TODO: Implement proper response. We need to handle rejected proposed writes in case
    # the file already exists.
    return {"write_id": write_id}

@app.post("/confirm_write")
async def confirm_write(conf: WriteConfirmation):
    """
    The keys should be present by design.
    If the keys is missing, let the galaxy burn!
    """
    with PENDING_RESOURCES_LOCK:
        pending_confirmations[conf.write_id].remove(conf.chunk_id)
    if not len(pending_confirmations[conf.write_id]):
        with PENDING_RESOURCES_LOCK:
            entry = pending_writes.pop(conf.write_id)
        if conf.success:
            # Updates the catalog as well!
            node.append_confirmed_log_entry(entry)
    return Response(content="success", status_code=200)

@app.delete("/delete_file")
async def handle_delete(client, filename):
    global CURRENT_LOG_ID
    try:
        entry = node.catalog.get_entry(client, filename)
    except NoSuchClientError:
        return Response(content="No such client!", status_code=507)
    except NoSuchFileError:
        return Response(content="No such file!", status_code=508)
    node.catalog.delete_file(client, filename)
    with LOG_ID_LOCK:
        CURRENT_LOG_ID += 1
        log_id = CURRENT_LOG_ID
    log_entry = {
        "id": log_id,
        "client": client,
        "file_name": filename,
        "file_size": entry["file_size"],
        "num_chunks": entry["num_chunks"],
        "timestamp": entry["timestamp"],
        "operation": "delete",
        "chunks": entry["chunks"],
    }
    node.append_confirmed_log_entry(log_entry)
    return Response(content="File deleted successfully", status_code=200)

@app.get("/list_files")
async def handle_list_files(client: str) -> List[str]:
    if not client in node.catalog.index:
        return JSONResponse(status_code=504, content={"details": f"client not found: {client}"})
    return list(node.catalog.index[client].keys())

@app.get("/get_catalog_entry")
async def handle_get_file(client: str, filename: str) -> dict:
    try:
        entry = node.catalog.get_entry(client, filename)
    except NoSuchClientError:
        return Response(content="No such client!", status_code=557)
    except NoSuchFileError:
        return Response(content="No such file!", status_code=558)
    return entry

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=9000)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <selfAddress> <selfPort>")
        sys.exit(1)

    # Read the log snapshot and set to the latest log ID.
    CURRENT_LOG_ID = 1

    # Expect selfAddress in the format "master-1:8001" (for replication).
    selfAddress = ":".join([sys.argv[1], sys.argv[2]])

    # Define all nodes (replication addresses) and set partner addresses.
    all_nodes = ['master-1:8001', 'master-2:8002', 'master-3:8003']
    partnerAddrs = [addr for addr in all_nodes if addr != selfAddress]

    node = MasterNode(selfAddress, partnerAddrs)
    logging.info(f"Node {selfAddress} starting with partners {partnerAddrs}")

    # Start the status API server in a separate thread.
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    # Regularly print status information.
    while True:
        status = node.getStatus()
        leader = status.get("leader", None)
        if hasattr(node, '_isLeader'):
            leader_flag = node._isLeader()
        else:
            leader_flag = node.isLeader()
        if leader_flag:
            logging.info(f"{selfAddress} is the leader. (uptime: {status.get("uptime", None)})")
        else:
            logging.info(f"{selfAddress} is a follower. Current leader is {leader \
                } (uptime: {status.get("uptime", None)})")
        # Only snapshot the catalog once every cycle.
        node.catalog.take_snapshot()
        node.gc.run()
        time.sleep(10)
