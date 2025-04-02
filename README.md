# Tiny Spark

This is a functional stripped down distributed file system with many similarities to GFS and HDFS written in python for educational purpose.

### Goal

1. To get a taste of the complexity and details of a real-world distributed system.

2. To better understand how distributed file systems work under the hood.

3. To have fun.

### Motivation

Distributed systems are complicated and there is no better way to understand a piece of software than to try to re-implement it.

# Installation details

I work in Ubuntu 24.04 and manage all deployments using docker compose. Install `docker compose` (not the obsolete `docker-compose`) using:

```
sudo apt install docker-compose-plugin
```


# tinyDFS: Notes about implementation detais and desingn shortcomings

1. The reverse proxy handles chunk replication instead of the principal chunk server (principal for the chunk) to the chunk replicas. This adds considerable load to the reverse proxy.

2. In our design, the upload process works as follows:
    - the client splits the file into chunks and collects general metadata.
    - the client sends a get request to the reverse proxy, forwarded to the current master.
    - the master checks in its in-memory catalog to see if the file already exists. We can control for this with an additional
        request field that indicates whether to allow for overwriting a file.
    - if the file does not exist, the master queries the chunk servers and gets a list of chunk servers that will stor the file in a three-way replicated scheme.
    - the master sends the client a response containing the chunk assignment metadata.
    - the client sends a separate post request with the actual chunks and the metadata.
    - the reverse proxy handles routing to chunk servers.


    In particular, we expose internal information to the client. Also, as mentioned in the previous point, we add load on the reverse proxy.

3. We might, actually, make the principal chunk server to replicate the chunk to the replica chunk servers. Why not, it is actually trivial.

4. Major shortcoming: we ensure ABSOLUTELY NO security (TLS, SSL, whatever).

5. We do not allow for file overwriting. If a client wishes to overwrite a file, the client must first delete the old file of the same name, then write the new file. The reason for this is that the two files will typically have a different size leading to potentially different chunk counts. Alternatively, we could internally trigger an atomic delete, followed by a write. This complication would totally make sense in a real system but in our case, it is not needed at all.

6. We don't bother splitting stored chunks into folders. Keeping all chunks in the same folder will eventually slow down searching for chunks names due to the way the linux file system works. One solution is to maintain a set of generic folders and split files by hashing their names. However, we don't bother with this, only list it as a potential improvement.

7. For simplicity, we do the chunk splitting on the client side, including the specification of the chunk sizes. Of course, in a real system this wouldn't make any sense. We could move this into the reverse proxy or the master, for example.

8. The client is aware of some of the data structures on the server side, e.g., the chunk assignment metadata structure. This could be handled better but we don't have to bother here.

9. Implementation detail: the reverse proxy is stateless, it only handles re-routing.

10. IMPORTANT implementation detail: We are NOT implementing a procedure to clean up partial writes. A general solution for cleaning up partial writes is to have an extended GC procedure (in addition to our GC procedure) that periodically scans all active chunk servers and deletes dead chunks. The problems here is that a chunk server might not be reachable when our GC removes partial writes, therefore leaving a trail of dead chunks. This can and will cause storage problems and one needs to deal with it in a real system. We won't bother with it, though.

11. The networking is a disaster and requires a major rewrite. There are serveral bugs left, primarily, network congestion when the primary chunk servers replicate. Probably, this is due to the fact that the reverse proxy makes "store_chunks" POST requests concurrently and all the chunk servers start pinging other chunk servers all at once. We need to fix this.

12. The snapshotting will get abandoned altogether. In general, a smart log snapshotting strategy is needed. However, we are not going to snapshot the log at all, only the in-memory data store. We only need to ensure that the in-memory storage changes get replicated. Then, we could simply snapshot after each write/delete. This is INCREDIBLY wasteful when it comes to disk I/O but it is not so important at the moment. Smart snapshotting strategies are a whole other topic.

13. The listFiles function does not provide any metadata. It is easy to add metadata but we don't really care.

14. The openAPI documentation is also totally messed up. We are currently showing the full suite of endpoints of the master, including the internal ones :D

# TODO:

1. Fix this encoding drama of the client-side json files. It works now if we don't encode them at all and just let fastAPI encode them as part of the payload. However, it is not clear whether the original metadata about the length of the serialized string is the same as the length of the string serialized by fastAPI. Overflowing a chunk would cause MAJOR issues.

2. We don't encrypt the data at all, simply do utf-8 encoding followed by base64 encoding. This seems to be typical encoding for REST APIs passing data payloads around. However, encryption would be absolutely paramount in a real world application.

