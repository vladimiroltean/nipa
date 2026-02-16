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
	perl \
	libdbd-sqlite3-perl \
	libsearch-xapian-perl \
	libmail-imapclient-perl \
	libterm-readkey-perl \
	libio-socket-ssl-perl \
	liburi-perl \
 && rm -rf /var/lib/apt/lists/*

# Clone and install public-inbox
# The upstream source (https://public-inbox.org/public-inbox.git) is unreliable,
# often returning "Failed to connect to public-inbox.org port 443 after 464 ms: Connection refused".
# Use a mirror when available, otherwise fallback to upstream.
ARG PUBLIC_INBOX_MIRROR
RUN PUBLIC_INBOX_REPO="${PUBLIC_INBOX_MIRROR:-https://public-inbox.org/public-inbox.git}" && \
    git clone "$PUBLIC_INBOX_REPO" /tmp/public-inbox && \
    cd /tmp/public-inbox && perl Makefile.PL && make && \
    make install && rm -rf /tmp/public-inbox

USER nipa

RUN git config --global user.name "NIPA"
RUN git config --global user.email "tester@nipa.org"

ENV VIRTUAL_ENV=/home/nipa/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:/home/nipa/bin:$PATH"

COPY --chown=nipa:nipa requirements.txt /home/nipa/requirements.txt

RUN pip install -r /home/nipa/requirements.txt

RUN mkdir -p /home/nipa/.local/share/patatt

RUN git clone https://git.kernel.org/pub/scm/devel/sparse/sparse.git /tmp/sparse && \
    cd /tmp/sparse && make -j $(nproc) && make install && \
    rm -rf /tmp/sparse
