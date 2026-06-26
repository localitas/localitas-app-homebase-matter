# homebase-matter — Matter sidecar
# Designed for Linux hosts with --network=host --privileged
# (required for BLE commissioning and mDNS multicast)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bluez \
    avahi-daemon \
    libnss-mdns \
    dbus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV STORAGE=/data/matter

VOLUME ["/data/matter"]

EXPOSE 9222

CMD ["python", "main.py", "--listen", ":9222", "--storage", "/data/matter"]
