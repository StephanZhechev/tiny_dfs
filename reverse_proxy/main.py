import logging
from typing import List
import httpx
from pydantic import BaseModel
from fastapi import FastAPI, Request, Response
import aiohttp
import asyncio

logging.basicConfig(level=logging.DEBUG)

class ChunkUpload(BaseModel):
    chunk_id: str
    primary: str
    replicas: List[str]
    data: str  # UTF-8 JSON string

class UploadRequest(BaseModel):
    client: str
    file_name: str
    file_size: int
    num_chunks: int
    chunks: List[ChunkUpload]

class FileRequest(BaseModel):
    client: str
    filename: str

app = FastAPI(docs_url=None, openapi_url=None)

CHUNK_SERVERS = [
    "http://chunk-1:10001",
    "http://chunk-2:10002",
    "http://chunk-3:10003",
    "http://chunk-4:10004",
    "http://chunk-5:10005",
    "http://chunk-6:10006",
    "http://chunk-7:10007",
]

def matchChunkServer(chunk_id, chunk_servers=CHUNK_SERVERS):
    urls = [elem for elem in chunk_servers if chunk_id in elem]
    assert len(urls), f"chunk_id does not correspond to a server: {chunk_id}"
    return urls[0]

async def get_leader():
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
                logging.debug(f"Got response from {url}: {data}")
                if data.get("isLeader", False):
                    # Return the master's API address (port 9000) for forwarding.
                    if "master-1" in url:
                        return "master-1:9000"
                    elif "master-2" in url:
                        return "master-2:9000"
                    elif "master-3" in url:
                        return "master-3:9000"
            except Exception as e:
                logging.debug(f"Error contacting {url}: {e}")
                continue
    return None

# Important to place this before the endpoint that redirects everything to the leader master nodes.
@app.post("/upload")
async def handle_upload(upload: UploadRequest):
    """
    Send the write proposal to the master first. If the write request fails, abort.
    If anything else fails, the master will already have the information about what chunks
    got potentially partially written and need to be discarded.
    """
    leader_address = await get_leader()
    if leader_address is None:
        return Response("No leader elected yet", status_code=503)
    leader_url = f"http://{leader_address}/propose_write"
    chunk_assignment = []
    for elem in upload.chunks:
        chunk_assignment.append({
            "chunk_id": elem.chunk_id,
            "primary": elem.primary,
            "replicas": elem.replicas,
        })
    write_proposal = {
        "id": -1, # This will be overwritten by the master
        "client": upload.client,
        "file_name": upload.file_name,
        "file_size": upload.file_size,
        "num_chunks": upload.num_chunks,
        "timestamp": -1, # This will be overwritten by the master
        "operation": "write",
        "chunks": chunk_assignment,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(leader_url, json=write_proposal)
        except Exception as e:
            logging.exception("Error forwarding request")
            return Response(f"Error forwarding request: {e}", status_code=500)
    write_id = resp.json()['write_id']
    tasks = []
    async with aiohttp.ClientSession() as session:
        for chunk in upload.chunks:
            payload = {
                "chunk_id": chunk.chunk_id,
                "write_id": write_id,
                "replicas": [matchChunkServer(elem) for elem in chunk.replicas],
                "data": chunk.data
            }
            tasks.append(session.post(
                f"{matchChunkServer(chunk.primary)}/store_chunk",
                json=payload
            ))
        results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or r.status != 200]
    if errors:
        for e in errors:
            print(await e.text())
        return Response(
            content=f"failed chunk uploads: {len(errors)}/{len(upload.chunks)}",
            status_code=500
        )
    return Response(content="success", status_code=200)

@app.get("/list_files")
async def list_files_handler(client: str):
    leader_address = await get_leader()
    if leader_address is None:
        return Response("No leader elected yet", status_code=503)
    res = httpx.get(f"http://{leader_address}/list_files?client={client}")
    return res.json()

@app.get("/get_file")
async def handler_get_file(client: str, filename: str) -> dict:
    """
    We only query primary chunk servers because we are lazy at this point.
    """
    leader_address = await get_leader()
    if leader_address is None:
        return Response("No leader elected yet", status_code=503)
    get_req = f"http://{leader_address}/{"get_catalog_entry"}"
    get_req += f"?client={client}&filename={filename}"
    response = httpx.get(get_req)
    if not response.json()["chunks"]:
        return Response(content="No chunks detected", status_code=404)
    res = {}
    for chunk in response.json()["chunks"]:
        print("First query chunk servers for their health and send request to the first one")
        get_url = f"{matchChunkServer(chunk["primary"])}/get_chunk"
        get_url += f"?chunk_id={chunk["chunk_id"]}"
        fetched = httpx.get(get_url)
        res[fetched["chunk_id"]] = fetched["data"]
    return res

@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
async def proxy(path: str, request: Request):
    leader_address = await get_leader()
    if leader_address is None:
        return Response("No leader elected yet", status_code=503)
    
    target_url = f"http://{leader_address}/{path}"
    logging.debug(f"Forwarding request for /{path} to {target_url}")
    
    async with httpx.AsyncClient() as client:
        try:
            if request.method == "GET":
                resp = await client.get(target_url, params=request.query_params)
            elif request.method == "POST":
                try:
                    body = await request.json()
                except Exception:
                    body = None
                resp = await client.post(target_url, json=body)
            else:
                return Response("Method Not Allowed", status_code=405)
        except Exception as e:
            logging.exception("Error forwarding request")
            return Response(f"Error forwarding request: {e}", status_code=500)
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
