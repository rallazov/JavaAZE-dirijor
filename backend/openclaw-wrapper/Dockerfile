# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
# Secure OpenClaw Wrapper – Firecracker-ready + Headscale mesh

FROM node:20-slim
RUN apt-get update && apt-get install -y wireguard curl

WORKDIR /app
COPY package.json .
COPY main.js .
COPY lib ./lib
# Runtime env (Story 5.2 policy surface — secure defaults: empty allowlist denies all tools):
#   DIRIJOR_TOOL_ALLOWLIST — comma-separated; omit or empty = deny all on POST /v1/tools/invoke
#   DIRIJOR_WRAPPER_POLICY_PATH — optional JSON file; if set, must exist (else container exits)
#   DIRIJOR_EGRESS_MODE — deny_public | allowlist (default deny_public)
#   DIRIJOR_EGRESS_ALLOW_HOSTS — comma-separated hosts for allowlist egress mode
#   DIRIJOR_IMPLEMENTED_TOOLS — optional; restrict which allowlisted tools return stub 200 vs 501
#   DIRIJOR_WRAPPER_MAX_BODY_BYTES — optional cap on POST JSON body size (default 1 MiB)
#   DIRIJOR_WRAPPER_BUILD_ID — optional version string for GET /health
# Mesh / realm labels (Story 5.1 pattern): HEADSCALE_URL, REALM_NAME, PORT
CMD ["node", "main.js"]
