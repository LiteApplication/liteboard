FROM python:3.12-slim

# psutil needs no build tools on slim for recent wheels; keep image minimal.
WORKDIR /opt/liteboard

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY liteboard_daemon.py protocol.py metrics.py netinspect.py dockerapi.py images.py netlink.py fabric.py ./

ENV LITEBOARD_DAEMON_PORT=9187 \
    LITEBOARD_DAEMON_BIND=0.0.0.0 \
    LITEBOARD_DOCKER_SOCK=/var/run/docker.sock

EXPOSE 9187

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9187/health',timeout=2).status==200 else 1)"

CMD ["python", "liteboard_daemon.py"]
