# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Secure OpenClaw Wrapper – Firecracker-ready + Headscale mesh

FROM node:20-slim
RUN apt-get update && apt-get install -y wireguard curl

WORKDIR /app
COPY main.js .
CMD ["node", "main.js"]
# Auto-joins private Headscale mesh on boot
# All actions routed through Dirijor safety gates
