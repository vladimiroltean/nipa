# Mailbox poller

The mailbox poller is a NIPA component specifically designed for
relatively infrequent use of a single or a small number of developers.

As opposed to deploying a Patchwork instances, the mailbox poller
listens using IMAP for new emails containing patches sent to an email
address, and interacts with the sender and the other email recipients by
replying, using SMTP, with build results for those patches.

Internally, the mailbox poller is a wrapper over the `ingest_mdir.py`
script which can also be run standalone. By using the mailbox poller,
developers can walk through more elements of the patch submission
process, and isolate the build machine from the development machine.

## Roles

The mailbox poller can be split in two roles:

1. **Worker**: Downloads patches over IMAP, applies them to the git
   tree, tests them and sends email notifications.
2. **Manager**: Polls the IMAP inbox for new emails. When it finds a
   patch series assigned to a specific worker, it ensures the
   corresponding worker machine is running.

The worker is a required component and the manager is an optional
component. The role of the manager is to make economical use of CPU time
on build machines when they mostly sit idle. It can automatically power
on and off the machines on which workers are running. Since the manager
does not need to perform many computations, it can run on comparatively
low powered hardware.

The mailbox poller also supports scaling to multiple workers. The work
distribution is completely parallel. Each worker performs a hash of the
patch series it needs to build, and it compares it with its preassigned
ID. If there is a match, it picks up the job, otherwise it ignores it.

## Mail box interaction

The mailbox poller can be made to listen either to a personal or
dedicated email address. It is given the name of a subfolder to monitor
for new emails. It will mark emails as seen as it processes them.

For personal emails, it is best to create rules that filter for a
certain pattern in the email title, like "PATCH net-next", and send
these emails to the subfolder that the mailbox poller will be monitoring.

A blacklist file is supported, through which certain email senders
(abusers) will be ignored when their emails are found in this mail box.

## Docker usage

The intended use is through docker-compose.

### Manager configuration

```bash
cat > /srv/docker/docker-compose.yml <<- 'EOF'
x-mbox-poller-base: &mbox-poller-base
  image: nipa-mbox-poller:latest
  build:
    context: ./nipa/docker
    args:
      # These need to match the owner of the volume of the Linux kernel git tree.
      nipauid: ...
      PUBLIC_INBOX_MIRROR: ...
  environment: &mbox-poller-env
    TZ: ...
    IMAP_SERVER_FILE: /run/secrets/imap_server
    IMAP_USER_FILE: /run/secrets/imap_user
    IMAP_PASS_CMD: "python3 /oauth2/device_code.py /oauth2/parameters.json"
    LOG_LEVEL: DEBUG
    HASH_SIZE: 1
    PYTHONUNBUFFERED: 1
    NIPA_WORK_DIR: /data
    ROLE: manager
    MANAGER_CONFIG_FILE: /data/manager.json
  volumes:
    - ./nipa:/nipa
    - /opt/nipa-ccache:/home/nipa/.cache/ccache
    - /opt/oauth2:/oauth2
    - ./nipa-data:/data
  restart: unless-stopped
  working_dir: /nipa
  secrets:
    - imap_server
    - imap_user
    - smtp_server
    - smtp_port
    - smtp_user
    - smtp_password
    - smtp_from_address

services:
  mbox-poller-manager:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa
    restart: always

  mbox-poller-manager-drm-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/drm-next
    restart: always

  mbox-poller-manager-linux-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/linux-next
    restart: always

  mbox-poller-manager-linux-phy:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/linux-phy
    restart: always

  mbox-poller-manager-net-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/net-next
    restart: always

secrets:
  imap_server:
    file: ./nipa-secrets/imap_server
  imap_user:
    file: ./nipa-secrets/imap_user
  smtp_server:
    file: ./nipa-secrets/smtp_server
  smtp_port:
    file: ./nipa-secrets/smtp_port
  smtp_user:
    file: ./nipa-secrets/smtp_user
  smtp_password:
    file: ./nipa-secrets/smtp_password
  smtp_from_address:
    file: ./nipa-secrets/smtp_from_address
EOF
cat > ./nipa-data/manager.json <<-'EOF'
[
    {
        "start": "...",
        "stop": "...",
        "status": "...",
        "workers": {
            "main": {
                "idle-check": "curl --connect-timeout 3 -s http://...:8080/idle-check"
            },
            "drm-next": {
                "idle-check": "curl --connect-timeout 3 -s http://...:8081/idle-check"
            },
            "linux-next": {
                "idle-check": "curl --connect-timeout 3 -s http://...:8082/idle-check"
            },
            "linux-phy": {
                "idle-check": "curl --connect-timeout 3 -s http://...:8083/idle-check"
            },
            "net-next": {
                "idle-check": "curl --connect-timeout 3 -s http://...:8084/idle-check"
            }
        }
    }
]
EOF
```

### Worker configuration

#### Worker API ports

The worker needs to be accessible on a TCP port for the manager to know
whether it is still running, or it has become idle. These ports need to
be opened on the host machine.

```bash
sudo vim /etc/iptables/rules.v4
Add:
-A INPUT -p tcp -m tcp --dport 8080 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 8081 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 8082 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 8083 -j ACCEPT
-A INPUT -p tcp -m tcp --dport 8084 -j ACCEPT
```
Must reboot.


```bash
cat > docker-compose.yml <<- 'EOF'
x-mbox-poller-base: &mbox-poller-base
  image: nipa-mbox-poller:latest
  build:
    context: ./nipa/docker
    args:
      # These need to match the owner of the volume of the Linux kernel git tree.
      nipauid: ...
      PUBLIC_INBOX_MIRROR: ...
  environment: &mbox-poller-env
    TZ: Europe/Bucharest
    IMAP_SERVER_FILE: /run/secrets/imap_server
    IMAP_USER_FILE: /run/secrets/imap_user
    IMAP_PASS_CMD: "python3 /oauth2/device_code.py /oauth2/parameters.json"
    SMTP_SERVER_FILE: /run/secrets/smtp_server
    SMTP_PORT_FILE: /run/secrets/smtp_port
    SMTP_USER_FILE: /run/secrets/smtp_user
    SMTP_PASSWORD_FILE: /run/secrets/smtp_password
    SMTP_FROM_ADDRESS_FILE: /run/secrets/smtp_from_address
    LOG_LEVEL: DEBUG
    HASH_SIZE: 1
    WORKER_INDEX: 0
    PYTHONUNBUFFERED: 1
    NIPA_WORK_DIR: /data
    ROLE: worker
    WORKER_CONFIG_FILE: /data/worker.json
  restart: unless-stopped
  working_dir: /nipa
  secrets:
    - imap_server
    - imap_user
    - smtp_server
    - smtp_port
    - smtp_user
    - smtp_password
    - smtp_from_address

services:
  mbox-poller-worker:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa
    ports:
      - 8080:8080
    volumes:
      - ./pgpkeys:/pgpkeys
      - ./nipa:/nipa
      - /opt/nipa-ccache:/home/nipa/.cache/ccache
      - /opt/linux:/linux
      - /opt/oauth2:/oauth2
      - ./nipa-data:/data
    restart: always

  mbox-poller-worker-drm-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/drm-next
    ports:
      - 8081:8080
    volumes:
      - ./pgpkeys:/pgpkeys
      - ./nipa:/nipa
      - /opt/nipa-ccache:/home/nipa/.cache/ccache
      - /opt/linux:/linux
      - /opt/oauth2:/oauth2
      - ./nipa-data-drm-next:/data
    restart: always

  mbox-poller-worker-linux-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/linux-next
    ports:
      - 8082:8080
    volumes:
      - ./pgpkeys:/pgpkeys
      - ./nipa:/nipa
      - /opt/nipa-ccache:/home/nipa/.cache/ccache
      - /opt/linux:/linux
      - /opt/oauth2:/oauth2
      - ./nipa-data-linux-next:/data
    restart: always

  mbox-poller-worker-linux-phy:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/linux-phy
    ports:
      - 8083:8080
    volumes:
      - ./pgpkeys:/pgpkeys
      - ./nipa:/nipa
      - /opt/nipa-ccache:/home/nipa/.cache/ccache
      - /opt/linux:/linux
      - /opt/oauth2:/oauth2
      - ./nipa-data-linux-phy:/data
    restart: always

  mbox-poller-worker-net-next:
    <<: *mbox-poller-base
    environment:
      <<: *mbox-poller-env
      IMAP_INBOX_FOLDER: inbox/nipa/net-next
    ports:
      - 8084:8080
    volumes:
      - ./pgpkeys:/pgpkeys
      - ./nipa:/nipa
      - /opt/nipa-ccache:/home/nipa/.cache/ccache
      - /opt/linux:/linux
      - /opt/oauth2:/oauth2
      - ./nipa-data-net-next:/data
    restart: always

secrets:
  imap_server:
    file: ./nipa-secrets/imap_server
  imap_user:
    file: ./nipa-secrets/imap_user
  smtp_server:
    file: ./nipa-secrets/smtp_server
  smtp_port:
    file: ./nipa-secrets/smtp_port
  smtp_user:
    file: ./nipa-secrets/smtp_user
  smtp_password:
    file: ./nipa-secrets/smtp_password
  smtp_from_address:
    file: ./nipa-secrets/smtp_from_address
EOF
```

There are two stages of git tree selection.

First are the rules which can be applied at the email server itself,
based on which email titles are steered to particular subfolders
assigned to workers.

Second are rules described in JSON configuration files by which workers
match git subject prefixes to git trees.

For example, if a patch is received having the "PATCH nipa-drm-next"
git subject prefix (see `man git-format-patch`), it can be configured to
build the patches on top of the "drm-next" branch of a remote called
"drm-next". The names are arbitrary, but the remote must have previously
been set up with `git remote add` when starting the worker.

For the second stage of the tree selection process, the keyword
`default` means a match regardless of the email subject prefix (title).

Multiple workers can coexist on the same machine as separate containers.
One worker can test-build against multiple git trees, or against a
single tree.

```bash
cat > nipa-data/worker.json <<-'EOF'
{
    "tree_selection": {
        "nipa-drm-next": {
            "remote": "drm-next",
            "branch": "drm-next"
        },
        "nipa-linux-next": {
            "remote": "linux-next",
            "branch": "master"
        },
        "nipa-linux-phy": {
            "remote": "linux-phy",
            "branch": "next"
        },
        "nipa-net-next": {
            "remote": "net-next",
            "branch": "main"
        }
    }
}
EOF
cat > nipa-data-drm-next/worker.json <<-'EOF'
{
    "tree_selection": {
        "default": {
            "remote": "drm-next",
            "branch": "drm-next"
        }
    }
}
EOF
cat > nipa-data-linux-next/worker.json <<-'EOF'
{
    "tree_selection": {
        "default": {
            "remote": "linux-next",
            "branch": "master"
        }
    }
}
EOF
cat > nipa-data-linux-phy/worker.json <<-'EOF'
{
    "tree_selection": {
        "default": {
            "remote": "linux-phy",
            "branch": "next"
        }
    }
}
EOF
cat > nipa-data-net-next/worker.json <<-'EOF'
{
    "tree_selection": {
        "default": {
            "remote": "net-next",
            "branch": "main"
        }
    }
}
EOF
```

Apart from the worker API ports for idle checking, there is no explicit
communication between the manager and the workers.

If there is no network communication at all between the manager and
workers, the workers can be configured to automatically shut down by
themselves.

```bash
cat <<- 'EOF' | sudo tee /usr/local/bin/autoshutdown > /dev/null
#!/bin/bash

set -euo pipefail

# Check if JSON file argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <workers.json>" >&2
    exit 1
fi

JSON_FILE="$1"

# Check if JSON file exists
if [ ! -f "$JSON_FILE" ]; then
    echo "Error: JSON file '$JSON_FILE' not found" >&2
    exit 1
fi

# Function to check if a single worker is idle
check_worker_idle() {
    local port="$1"
    local response

    # Make HTTP request with timeout
    if response=$(curl --connect-timeout 3 -s "http://localhost:${port}/idle-check" 2>/dev/null); then
        # Parse JSON response to get idle status
        local idle_status
        idle_status=$(echo "$response" | jq -r '.idle // false')

        if [ "$idle_status" = "true" ]; then
            return 0  # Worker is idle
        else
            return 1  # Worker is busy
        fi
    else
        echo "Warning: Failed to connect to worker on port $port" >&2
        return 1  # Treat connection failure as busy (safe default)
    fi
}

# Parse JSON file to extract worker ports
# Assuming JSON structure like: [{"port": 8081}, {"port": 8082}, ...]
# or commands like: ["curl ... http://localhost:8081/idle-check", ...]
workers_ports=$(jq -r '.[] | if type == "object" then .port else . end | if type == "string" then match("localhost:([0-9]+)").captures[0].string else . end' "$JSON_FILE")

if [ -z "$workers_ports" ]; then
    echo "Error: No worker ports found in JSON file" >&2
    exit 1
fi

echo "Checking idle status for workers..."

all_idle=true

# Check each worker
while IFS= read -r port; do
    if [ -n "$port" ]; then
        echo "Checking worker on port $port..."
        if check_worker_idle "$port"; then
            echo "  Worker on port $port is idle"
        else
            echo "  Worker on port $port is busy"
            all_idle=false
        fi
    fi
done <<< "$workers_ports"

# If all workers are idle, shut down the machine
if [ "$all_idle" = "true" ]; then
    echo "All workers are idle. Initiating shutdown..."
    logger "autoshutdown-check: All workers idle, shutting down system"
    shutdown -h now
else
    echo "Some workers are still busy. Shutdown cancelled."
fi
EOF
sudo chmod +x /usr/local/bin/autoshutdown
cat <<- 'EOF' | sudo tee /etc/autoshutdown-workers.json > /dev/null
[
  {"port": 8080},
  {"port": 8081},
  {"port": 8082},
  {"port": 8083},
  {"port": 8084}
]
EOF

cat <<- 'EOF' | sudo tee /etc/systemd/system/autoshutdown.service > /dev/null
[Unit]
Description=Check if all workers are idle and shutdown if so
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/autoshutdown /etc/autoshutdown-workers.json
User=root
StandardOutput=journal
StandardError=journal
EOF

cat <<- 'EOF' | sudo tee /etc/systemd/system/autoshutdown.timer > /dev/null
[Unit]
Description=Run idle shutdown check every 3 minutes
Requires=autoshutdown.service

[Timer]
OnCalendar=*:0/3
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable autoshutdown.timer
sudo systemctl start autoshutdown.timer
```
