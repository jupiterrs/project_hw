FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    wget \
    ca-certificates \
    vim \
    less \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Miniconda3
ENV CONDA_DIR=/opt/conda
RUN curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p $CONDA_DIR \
    && rm /tmp/miniconda.sh
ENV PATH=$CONDA_DIR/bin:$PATH

# Initialize conda for all shells (bash login + non-login)
RUN $CONDA_DIR/bin/conda init bash 2>/dev/null || true
# Make conda available in non-interactive bash sessions (docker exec uses bash -lc)
RUN echo 'source /opt/conda/etc/profile.d/conda.sh && conda activate base' >> /etc/bash.bashrc

# Verify conda works in a login shell
RUN bash -lc "conda --version && python --version && pip --version"

# Workspace for cloned repos
RUN mkdir -p /workspace
WORKDIR /workspace

# Default shell
CMD ["/bin/bash"]
