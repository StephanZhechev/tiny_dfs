from typing import List
from pydantic import BaseModel

class GetChunkAssignmentRequest(BaseModel):
    client_name: str
    file_name: str
    file_size: int

class ChunkAssignment(BaseModel):
    chunk_id: str
    primary: str
    replicas: List[str]

class ChunkAssignmentResponse(BaseModel):
    chunk_size: int
    chunk_assignment: List[ChunkAssignment]

class LogEntry(BaseModel):
    id: int
    client: str
    file_name: str
    file_size: int
    num_chunks: int
    timestamp: int
    operation: str
    chunks: List[ChunkAssignment]

class WriteConfirmation(BaseModel):
    write_id: int
    chunk_id: str
    success: bool

class DeleteRequest(BaseModel):
    client: str
    filename: str

class GCEntry(BaseModel):
    client: str
    filename: str
    chunks: List[ChunkAssignment]

class ListFilesRequest(BaseModel):
    client: str
