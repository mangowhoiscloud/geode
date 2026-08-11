FROM python:3.12-bookworm

ARG HERMES_REVISION=c0106e50e7ecedb3ce34e785d949725dc4e0e457

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN git init /opt/hermes \
    && git -C /opt/hermes remote add origin https://github.com/NousResearch/hermes-agent.git \
    && git -C /opt/hermes fetch --depth=1 origin "${HERMES_REVISION}" \
    && git -C /opt/hermes checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/hermes rev-parse HEAD)" = "${HERMES_REVISION}" \
    && python -m pip install --no-cache-dir -e '/opt/hermes[acp,mcp]' \
    && python -c 'import acp, mcp, tools.mcp_tool as t; assert t._MCP_AVAILABLE'

RUN mkdir -p /home/user/.hermes \
    && echo '{"hasCompletedOnboarding":true,"bypassPermissionsModeAccepted":true}' \
       > /home/user/.claude.json

LABEL org.opencontainers.image.source="https://github.com/NousResearch/hermes-agent" \
      org.opencontainers.image.revision="${HERMES_REVISION}"

CMD ["tail", "-f", "/dev/null"]
