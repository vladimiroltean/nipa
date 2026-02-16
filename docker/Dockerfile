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
	sparse \
	bc \
	cpio \
	gdb \
	strace \
	vim \
	libpq-dev \
 && rm -rf /var/lib/apt/lists/*

USER nipa

RUN git config --global user.name "NIPA"
RUN git config --global user.email "tester@nipa.org"

ENV VIRTUAL_ENV=/home/nipa/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --chown=nipa:nipa requirements.txt /home/nipa/requirements.txt

RUN pip install -r /home/nipa/requirements.txt

RUN mkdir -p /home/nipa/.local/share/patatt
