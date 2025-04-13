# TinyDFS

This is a functional stripped down distributed file system with many similarities to GFS and HDFS written in python for educational purpose.
You can find a detailed explanation of the system here: [medium article](https://medium.com/@stephan.zhechev/tinydfs-an-educational-distributed-file-system-3892c3069030)

**Disclaimer:** The code is messy but I couldn't gather enough motivation to polish it.

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

Create the docker network separately:

```
docker network create --driver=bridge --opt com.docker.network.driver.mtu=1450 tiny_dfs_internal_network
```

Spint docker compose. It is informative to keep it attached to the terminal (no ```-d```) so you could see the logs as you use the system.

```
docker compose up --build
```

# Usage

You should create a venv with the requirements for the client API and once activated, you can run the ```demo.py``` file to see the basic functionalities.
