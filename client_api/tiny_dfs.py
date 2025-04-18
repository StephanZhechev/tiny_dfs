import base64
from typing import List
import httpx

class ChunkAssignmentFailError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class tinyGFSClient():
    """
    Client API for our tiny GFS distributed service.
    """

    def __init__(self, client_name: str, host: str="localhost", port: int=8000):
        """
        The setup is such that the rest API runs on localhost port 8000.
        """
        assert isinstance(client_name, str), "client_name must be a strting!"
        self.client_name = client_name
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{str(port)}/"
        assert self.getStatus().status_code == 200, "API status code not 200!"

    def getStatus(self):
        return httpx.get(self._buildURL("status"))
    
    def uploadFile(
            self,
            obj: str,
            file_name: str,
            retries: int=10
        ) -> bool:
        """
        Will retry the upload a few times.

        :param obj: valid json string.
        :param file_name:
        :param retries: how many times to retry if it receives status code 500.
        :return: status code of the final post request.
        """
        assert self.getStatus().status_code == 200, "API status code not 200!"
        serialized = self._serializeJSON(obj)
        for _ in range(retries):
            try:
                try:
                    chunk_assignment = self._getChunkAssignment(
                        file_name=file_name,
                        file_size=len(serialized),
                    )
                    assert chunk_assignment is not None, "Failed chunk assignment"
                    chunks = self._split_to_chunks(serialized, chunk_assignment["chunk_size"])
                    assert len(chunks)==len(chunk_assignment['chunk_assignment']), "Non-matching number of chunks!"
                    chunks_payload = []
                    for chunk, assign in zip(chunks, chunk_assignment['chunk_assignment']):
                        chunks_payload.append({
                            "chunk_id": assign["chunk_id"],
                            "primary": assign["primary"],
                            "replicas": assign["replicas"],
                            "data": chunk,
                        })
                    payload = {
                        "client": self.client_name,
                        "file_name": file_name,
                        "file_size": len(serialized),
                        "num_chunks": len(chunks),
                        "chunks": chunks_payload,
                    }
                    resp = httpx.post(self._buildURL("upload"), json=payload, timeout=1)
                    if resp.status_code != 200:
                        print("Upload failed:", resp.status_code, resp.text)
                    else:
                        print("Initial upload successful:", resp.text)
                        break
                except ChunkAssignmentFailError:
                    chunk_assignment = None
                    continue
            except httpx.ReadTimeout:
                continue
        for _ in range(retries):
            all_files = self.listFiles()
            if not file_name in all_files:
                continue
            else:
                print("Log replication successful.")
                return True
        print("Log replication failed. Write is rejected.")
        return False


    def listFiles(self):
        url = f"{self._buildURL("list_files")}?client={self.client_name}"
        response = httpx.get(url)
        response.raise_for_status()
        return response.json()
    
    def getCatalogEntry(self, filename: str):
        """
        This is for debugging purposes. Of course, in a real-world system,
        the user is not supposed to be able to query internal information like this.
        """
        url = f"{self._buildURL("get_catalog_entry")}?client={self.client_name}"
        url += f"&filename={filename}"
        response = httpx.get(url)
        response.raise_for_status()
        return response.json()

    def deleteFile(self, filename: str, retries: int=10) -> None:
        url = f"{self._buildURL("delete_file")}?client={self.client_name}&filename={filename}"
        response = httpx.delete(url)
        response.raise_for_status()
        for _ in range(retries):
            all_files = self.listFiles()
            if filename in all_files:
                continue
            else:
                print("Log replication successful.")
                return True
        print("Replication failed. Delete is rejected.")
        return False

    def getFile(self, filename: str):
        url = self._buildURL("get_file")
        url += f"?client={self.client_name}&filename={filename}"
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        return self._reconstruct_from_chunks(response.json())
        
    def _getChunkAssignment(
            self,
            file_name: str,
            file_size: int,
        ) -> List[dict]:
        """
        Args:

        :param file_name:
        :param file_size: file size in bytes.
        :param chunk_cnt:
        """
        response = httpx.post(
            url=self._buildURL("get_chunk_assignment"),
            json = {
                "client_name": self.client_name,
                "file_name": file_name,
                "file_size": file_size,
            }
        )
        assert response.status_code == 200, f"Bad response status code: {response.status_code} + {response.text}"
        return response.json()

    def _buildURL(self, endpoint):
        assert isinstance(endpoint, str), "endpoint must be a string!"
        return self.base_url + endpoint

    def _split_to_chunks(self, json_bytes: bytes, chunk_size: int):
        """
        Input must already be a valid JSON string.
        Chunk size is in bytes.
        """
        assert isinstance(json_bytes, str)
        chunks = [json_bytes[i:i+chunk_size] for i in range(0, len(json_bytes), chunk_size)]
        return chunks

    def _reconstruct_from_chunks(self, chunks):
        return "".join([self._unserializeJSON(elem) for elem in chunks])
    

    def _serializeJSON(self, s: str) -> str:
        """
        Use utf-8 and base64 serialization.
        """
        assert isinstance(s, str)
        return base64.b64encode(s.encode("utf-8")).decode("ascii")  # ASCII-safe string

    def _unserializeJSON(self, s: str) -> str:
        return base64.b64decode(s).decode("utf-8")

