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
	curl \
	git \
	gnupg \
	build-essential \
	ccache \
	flex \
	bison \
	gawk \
	libssl-dev \
	libelf-dev \
	clang lld llvm llvm-dev \
	bc \
	cpio \
	gdb \
	strace \
	vim \
	libpq-dev \
	iputils-ping \
	iproute2 \
	perl \
	libdbd-sqlite3-perl \
	libsearch-xapian-perl \
	libmail-imapclient-perl \
	libterm-readkey-perl \
	libio-socket-ssl-perl \
	liburi-perl \
	swig \
	libnl-3-dev \
	shellcheck \
	libmnl-dev \
	libxml2-dev \
	libsqlite3-dev \
	coreutils \
	jq \
	codespell \
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

# This fake email address is not completely arbitrary. Others will cause
# tests/patch/cc_maintainers/test.py to complain that we were not CCed.
RUN git config --global user.name "nipa"
RUN git config --global user.email "nipa@patchwork.hopto.org"
RUN if [ -n "$HTTP_PROXY" ]; then \
	git config --global http.proxy "$HTTP_PROXY" && \
	git config --global https.proxy "${HTTPS_PROXY:-$HTTP_PROXY}"; \
    fi

ENV VIRTUAL_ENV=/home/nipa/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:/home/nipa/bin:$PATH"

COPY --chown=nipa:nipa requirements.txt /home/nipa/requirements.txt

RUN pip install -r /home/nipa/requirements.txt

# This is https://git.kernel.org/pub/scm/docs/kernel/pgpkeys.git,
# prefer to keep it checked out as separate volume for more control
RUN mkdir -p /home/nipa/.local/share/patatt/ && \
    ln -sf /pgpkeys/.keyring /home/nipa/.local/share/patatt/public

COPY --chown=nipa:nipa sparse-patches/ /home/nipa/sparse-patches/

RUN git clone https://git.kernel.org/pub/scm/devel/sparse/sparse.git /home/nipa/sparse && \
    cd /home/nipa/sparse && \
    if [ -d /home/nipa/sparse-patches ]; then \
        for p in /home/nipa/sparse-patches/*; do \
            git am "$p"; \
        done; \
    fi && \
    make -j $(nproc) && make install
