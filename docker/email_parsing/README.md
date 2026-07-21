* Build docker image (from the docker/email_parsing directory):
```bash
docker build --platform linux/amd64 -t docker-image:test .
```

* Run docker image as a container:
```bash
docker run -it --rm docker-image:test
```

    ... or run the conatiner with an assigned name:
```bash
docker run --name lambda-func -d docker-image:test
# -d is for detached mode
```

* Start a stopped container:
```bash
docker start <container_id>
```

* Open up running container in another terminal:
```bash
docker exec -it <container_id> /bin/bash
```