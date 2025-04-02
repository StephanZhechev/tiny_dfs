from typing import List
import json, os, logging, random, json, threading
import httpx
from fastapi import HTTPException
from pysyncobj import SyncObj, SyncObjConf, replicated

from .schemas import ChunkAssignment, LogEntry

class NoSuchClientError(Exception):
    def __init__(self, client: str):
        message = f"No such client: {client}"
        super().__init__(message)
        self.message = message

class NoSuchFileError(Exception):
    def __init__(self, filename: str):
        message = f"No such file: {filename}"
        super().__init__(message)
        self.message = message

class InMemoryCatalog:
    snapshot_file_path: str="/home/data/in_memory_catalog_snapshot.json"

    def __init__(self):
        try:
            with open(self.snapshot_file_path, "r") as fp:
                self.index = json.load(fp)
        except:
            self.index = {}

    def add_file(self, log_entry: LogEntry):
        if log_entry.client not in self.index:
            self.index[log_entry.client] = {}
        self.index[log_entry.client][log_entry.file_name] = {
            "file_size": log_entry.file_size,
            "num_chunks": log_entry.num_chunks,
            "timestamp": log_entry.timestamp,
            "chunks": [elem.model_dump() for elem in log_entry.chunks],
        }

    def delete_file(self, client, filename) -> None:
        if not client in self.index:
            self.index[client] = {}
            raise NoSuchClientError(client)
        if not filename in self.index[client]:
            raise NoSuchFileError(filename)
        del self.index[client][filename]
        return None

    def list_files(self, client):
        """Return a list of file metadata for a given owner."""
        if client in self.index:
            return self.index[client].keys()
        raise NoSuchClientError(client)

    def take_snapshot(self):
        """
        Take a snapshot of the whole in-memory file index and record the latest log index.
        After writing the snapshot to disk, compact the log up to the last committed index.
        """
        with open(self.snapshot_file_path, "w") as f:
            json.dump(self.index, f)
        logging.info("In-memory catalog snapshot taken.")

async def get_chunk_assignment(
        chunk_cnt:int,
        client_name: str,
        file_name: str,
    ) -> List[ChunkAssignment]:
    assignments = []
    try:
        servers = await sample_healthy_chunk_servers(chunk_cnt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    for i in range(chunk_cnt):
        chunk_id = f"{client_name}_{file_name}_chunk_{i}"
        if len(servers[i]) < 2:
            raise ValueError(f"Too few chunk servers assigned for file {chunk_id}!")
        assignment = ChunkAssignment(
            chunk_id=chunk_id,
            primary=servers[i][0],
            replicas=servers[i][1:],
        )
        assignments.append(assignment)
    return assignments

async def sample_healthy_chunk_servers(num_samples: int, count: int=3) -> List[str]:
    """
    Just a test for now. We will use get_chunk_assignment later.
    Check what chunk servers are healthy and select count many of them uniformly at random.

    Chunk servers are hardcoded!
    """
    res = {}
    chunk_health_routes = {f"chunk-{i}":f"http://chunk-{i}:1000{i}/health" for i in range(1, 8)}
    async with httpx.AsyncClient() as client:
        for chunk in chunk_health_routes.keys():
            url = chunk_health_routes[chunk]
            try:
                resp = await client.get(url, timeout=1.0)
                data = resp.json()
                logging.debug(f"Got response from {url}: {data}")
                res[chunk] = data.get("status", "not_ok")
            except Exception as e:
                logging.debug(f"Error contacting {url}: {e}")
                continue
        res = [key for key, val in res.items() if val=="ok"]
        if len(res)<count:
            raise ValueError(f"Too few healthy chunk servers {len(res)} for required count {count}!")
    return [random.sample(res, count) for _ in range(num_samples)]

class MasterNode(SyncObj):
    def __init__(
            self,
            selfAddress,
            partnerAddrs,
            log_file="/home/data/log.jsonl"
        ):
        conf = SyncObjConf(dynamicMembershipChange=True)
        super(MasterNode, self).__init__(selfAddress, partnerAddrs, conf=conf)
        self.counter = 0
        self.master_log_path = log_file
        self.active_files = {} # Not used at the moment
        self.catalog = InMemoryCatalog()
        self.gc = GarbageCollector()

        # This is already done in the beginning of the master script
        # but keep it also here in case we delete it there.
        if not os.path.exists(log_file):
            open(log_file, 'w').close()

    @replicated
    def append_confirmed_log_entry(self, entry):
        """
        This method appends a confirmed log entry to the in-memory log
        and writes it to the persistent JSONL file.
        The @replicated decorator ensures that the operation is applied
        consistently across all nodes in the RAFT cluster.
        
        :param entry: A dictionary representing the confirmed log entry.
        """
        with open(self.master_log_path, 'a') as f:
            f.write(json.dumps(entry) + "\n")
        # Alters the catalog!
        self.catalog.add_file(LogEntry.model_validate(entry))


class GarbageCollector:

    def __init__(self):
        self.gc_queue = self._init_queue()
        self.lock = threading.Lock()

    def add_to_gc(self, chunk_server: str, chunk_id: str):
        """
        No error handling in case a wrong chunk server is passed.
        """
        with self.lock:
            self.gc_queue[chunk_server].append(chunk_id)

    def run(self):
        """
        Iterate over the tasks in the GC queue and try to delete the chunk
        from the corresponding chunk server.
        We don't check whether the deletes were successful.
        """
        logging.info("Running GC...")
        for task in self.gc_queue:
            with self.lock:
                try:
                    r = httpx.delete(
                        task["url"],
                        json={"files": task["files"]},
                        timeout=5
                    )
                    self.gc_queue.remove(task)
                except:
                    pass

    def _init_queue(self):
        """
        Hardcoded is my middle name.
        """
        res = {}
        for i in range(1, 8):
            res[f"chunk-{i}"] = {
                "url": f"http://chunk-{i}:1000{i}/delete-chunks",
                "files": []                
            }
        return res
