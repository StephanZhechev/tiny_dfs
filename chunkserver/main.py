import os, sys, logging
import httpx
from typing import List
from pydantic import BaseModel
from fastapi import FastAPI, Response
import uvicorn
import aiohttp
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO)

async def create_session():
    """
    Create a juiced-up aiohttp connection that will be shared across chunk storage tasks.
    """
    connector = aiohttp.TCPConnector(limit=30)
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), connector=connector)

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=10))
async def replicate_data(replica, chunk_id, data):
    async with await create_session() as session:
        res = await session.post(
            f"{replica}/store_replica",
            json={"chunk_id": chunk_id, "data": data}
        )
        return res

# /home/data is where we mount the volume
DATA_DIR = "/home/data"
if not os.path.exists(DATA_DIR):
    raise ValueError(r"/home/data does not exist!")

async def get_leader():
    """
    Duplicated function.
    """
    # List of master nodes' status endpoints (running on port 9000)
    masters = [
        "http://master-1:9000/status",
        "http://master-2:9000/status",
        "http://master-3:9000/status"
    ]
    async with httpx.AsyncClient() as client:
        for url in masters:
            try:
                resp = await client.get(url, timeout=1.0)
                data = resp.json()
                logging.info(f"Got response from {url}: {data}")
                if data.get("isLeader", False):
                    # Return the master's API address (port 9000) for forwarding.
                    if "master-1" in url:
                        return "master-1:9000"
                    elif "master-2" in url:
                        return "master-2:9000"
                    elif "master-3" in url:
                        return "master-3:9000"
            except Exception as e:
                logging.info(f"Error contacting {url}: {e}")
                continue
    return None

class StoreChunkRequest(BaseModel):
    chunk_id: str
    write_id: int
    replicas: List[str]
    data: str  # base64 string

class ReplicaChunk(BaseModel):
    chunk_id: str
    data: str

class FileDeleteRequest(BaseModel):
    files: List[str]

app = FastAPI()

@app.get("/health")
def health():
    """
    Health check endpoint for monitoring.
    """
    return {"status": "ok"}

@app.post("/store_chunk")
async def store_chunk(req: StoreChunkRequest):
    """
    Endpoint to store a file chunk.
    
    The reverse proxy sends a file upload here. The chunk server saves the chunk
    under DATA_DIR using the provided filename (which should be unique).

    This is the endpoint for a principal chunk server. In particular, being the principal
    is responsible for forwarding the chunk to the replicas, collecting the information whether
    the replication was successful, and forwarding this information to the master.

    NB: Does not allow for partial replication of chunks. If anything fails, it fails too.
    """
    path = os.path.join(DATA_DIR, req.chunk_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(req.data)
    # Replicate
    async with await create_session() as session:
        tasks = [
            session.post(
                f"{replica}/store_replica",
                json={"chunk_id": req.chunk_id, "data": req.data}
            )
            for replica in req.replicas
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    master_confirmation_payload = {
        "write_id": req.write_id,
        "chunk_id": req.chunk_id,
        "success": True,
    }
    leader_address = await get_leader()
    if leader_address is None:
        return Response("No leader elected yet", status_code=503)
    leader_url = f"http://{leader_address}"

    async with await create_session() as session:
        if any(isinstance(r, Exception) or r.status != 200 for r in results):
            for r in results:
                if isinstance(r, Exception):
                    logging.error("ClientConnectorError occurred: %s", r)
                else:
                    if r.status != 200:
                        logging.error(f"Replication failed: {await r.text()}")                    
            master_confirmation_payload["success"] = False
            await session.post(
                f"{leader_url}{"/confirm_write"}",
                json=master_confirmation_payload
            )
            return Response(content="replication_failed", status_code=500)
        else:
            confirmation_response = await session.post(
                f"{leader_url}{"/confirm_write"}",
                json=master_confirmation_payload
            )
            if confirmation_response.status == 200:
                return Response(content="success", status_code=200)
            else:
                return Response(content="failed", status_code=500)

@app.post("/store_replica")
async def store_replica(chunk: ReplicaChunk):
    """
    Endpoint for storing a chunk replica.
    
    Details: store requests come from the principal chunk server for the chunk in question.
        Therefore, the chunk only gets stored and a generic status is sent back.
    """
    path = os.path.join(DATA_DIR, chunk.chunk_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(chunk.data)
    return Response(content="success", status_code=200)

@app.get("/get_chunk")
async def handler_get_chunk(chunk_id) -> dict:
    path = os.path.join(DATA_DIR, chunk_id)
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    return {
        "chunk_id": chunk_id,
        "data": data,
    }
    

@app.delete("/delete-chunks")
async def delete_chunks(request: FileDeleteRequest):
    """
    We are not too pedantic about failed deletions.
    """
    for file in request.files:
        if os.path.exists(f"{DATA_DIR}/{file}"):
            os.remove(file)
    return Response(content="success", status_code=200)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <selfAddress> <selfPort>")
        sys.exit(1)
    uvicorn.run(app, host=sys.argv[1], port=int(sys.argv[2]))
