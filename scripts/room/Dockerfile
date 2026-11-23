FROM mcr.microsoft.com/playwright/python:v1.56.0-noble@sha256:a7f6cf3ae520c9d670ad956572c13747ed5abdbba5123a01526f873ed1662528
RUN pip install --no-cache-dir playwright==1.56.0
COPY reader.py /room/reader.py
USER pwuser
ENTRYPOINT ["python", "-u", "/room/reader.py"]
