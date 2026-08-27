ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
COPY skill-packages /workspace/skill-packages
RUN mkdir -p /workspace/work /workspace/output \
    && ln -s /workspace/skill-packages /skill-packages \
    && ln -s /workspace/work /work \
    && ln -s /workspace/output /output \
    && chown -R root:root /workspace/skill-packages \
    && chmod -R a-w /workspace/skill-packages \
    && chown -R 1000:1000 /workspace/work /workspace/output
ENV DEEPAGENT_WORKSPACE=/workspace
WORKDIR /workspace
USER 1000
