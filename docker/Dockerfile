FROM debian:trixie

# Duplicate uid useradd option is necessary for people who run this as root.
ARG nipauid
RUN useradd -o -m -u $nipauid nipa

RUN apt-get update && apt-get install -y \
	procps \
	python3 \
	python3-venv \
	python3-pip \
	python3-dev \
	git \
	build-essential \
	ccache \
	flex \
	bison \
	gawk \
	libssl-dev \
	libelf-dev \
	clang lld llvm \
	bc \
	cpio \
	gdb \
	strace \
	vim \
	libpq-dev \
 && rm -rf /var/lib/apt/lists/*

USER nipa

# This fake email address is not completely arbitrary. Others will cause
# tests/patch/cc_maintainers/test.py to complain that we were not CCed.
RUN git config --global user.name "nipa"
RUN git config --global user.email "nipa@patchwork.hopto.org"

ENV VIRTUAL_ENV=/home/nipa/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:/home/nipa/bin:$PATH"

COPY --chown=nipa:nipa requirements.txt /home/nipa/requirements.txt

RUN pip install -r /home/nipa/requirements.txt

RUN mkdir -p /home/nipa/.local/share/patatt

RUN git clone --depth=1 https://git.kernel.org/pub/scm/devel/sparse/sparse.git /tmp/sparse && \
    cd /tmp/sparse && make -j $(nproc) && make install && \
    rm -rf /tmp/sparse
