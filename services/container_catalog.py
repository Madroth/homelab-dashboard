"""What each container actually IS, in one sentence.

Docker cannot answer this. `docker inspect` tells you an image name and a compose
project, which answers "what is it called" and not "what is it for" -- staring at
`varthe/defaulterr:latest` tells you nothing about why it is on this host. The
OCI label that was meant to carry a description
(org.opencontainers.image.description) is empty on almost every image here, so it
is used where present and nothing is built on top of it.

RESOLUTION ORDER, most specific first:
  1. BY_NAME  -- exact container name. Needed where several containers share one
     image and do different jobs: five plane-app-* containers all run
     makeplane/plane-backend and are respectively the API, two workers, a
     scheduler and a one-shot migrator.
  2. BY_IMAGE -- normalized image repository, tag stripped. One entry covers that
     image wherever it runs, so a second Radarr somewhere else is described for
     free. This is the bulk of the catalog.
  3. The image's own OCI description label, if the image ships one.
  4. A structural summary derived purely from `docker inspect` -- compose stack,
     image, published ports, host mounts. Not what the software DOES, but it
     cannot be wrong, and it is real orientation for a container nobody has
     described yet. This is what makes a newly created container useful
     immediately with no human step.
  5. Nothing. The UI must then say it does not know.

NO GUESSING. An entry is written only where the purpose is actually known. A
plausible-sounding invention is worse than a blank here, because a blank prompts
someone to write the real answer while a confident wrong sentence never gets
corrected. Containers whose purpose is still unconfirmed are listed in UNDESCRIBED
below with what would settle them; they still render their structural summary.

GENERATING THESE WITH A LOCAL LLM WAS TESTED AND REJECTED (2026-09-01, phi3:mini
on this host's Ollama, Omega's GPU being down). Of five images it produced three
confident falsehoods: Radarr as handling "movies, TV shows, and music" (it is
films only -- Sonarr does TV), gluetun as "file management" (it is a VPN
gateway), and an invented purpose for a locally built image it could not
possibly know. It cost 12-46s per container on CPU to be wrong. The failure mode
is exactly the one this file is built around: fluent, confident, unverifiable,
and never corrected. Layer 4 exists because a derived fact beats a generated
guess.

To add one: put it in BY_IMAGE unless the image is ambiguous on this host, in
which case use BY_NAME. One sentence, present tense, says what it does and why
it is here.
"""

# Same image, different jobs -- these must beat the image-level entry.
BY_NAME: dict[str, str] = {
    'plane-app-api-1': 'Plane\'s Django backend: serves the REST API the web and mobile clients talk to.',
    'plane-app-worker-1': 'Plane\'s Celery worker: runs background jobs (notifications, exports, webhooks) off the queue.',
    'plane-app-beat-worker-1': 'Plane\'s Celery beat scheduler: the clock that enqueues Plane\'s recurring jobs.',
    'plane-app-migrator-1': 'One-shot Plane database migrator: runs schema migrations at deploy and exits. Exited(0) is success, not a fault.',
    'plane-app-web-1': 'Plane\'s main Next.js web UI -- the project/issue interface you actually use.',
    'plane-app-space-1': 'Plane\'s public "Spaces" front end for externally shared views. Unused here, part of the stock deployment.',
    'plane-app-admin-1': 'Plane\'s instance administration UI (god-mode settings), separate from the project UI.',
    'plane-app-live-1': 'Plane\'s realtime collaboration server, backing live cursors and collaborative document editing.',
    'plane-app-proxy-1': 'Plane\'s nginx entry point: terminates HTTP and routes to web, api, space and live. Known broken since 2026-08-24 -- running with no networks and no published ports, which is why "Send to HomeLab" fails.',
    'plane-app-plane-db-1': 'PostgreSQL 15 holding all Plane data -- projects, issues, and since 2026-08-18 the article-intake to-dos. RF-1: this database has never had a successful backup.',
    'plane-app-plane-redis-1': 'Valkey (Redis fork) used by Plane for caching and as the Celery broker\'s result backend.',
    'plane-app-plane-mq-1': 'RabbitMQ: the message queue Plane\'s Celery workers pull jobs from.',
    'plane-app-plane-minio-1': 'MinIO, S3-compatible object storage for Plane file attachments and avatars.',
    'ac-database': 'MySQL 8.4 holding the AzerothCore world, characters and auth databases for the WotLK server.',
}

# Normalized image repository (registry host and tag stripped) -> description.
BY_IMAGE: dict[str, str] = {
    # --- homelab-monitoring: the observability stack ---
    'prom/prometheus': 'Time-series database and alert engine: scrapes metrics from the exporters, evaluates the Block 2 rules, and sends alerts to Alertmanager.',
    'prom/alertmanager': 'Routes alerts from Prometheus and Loki to the ntfy channel that reaches your phone -- the single place alert delivery is decided.',
    'grafana/loki': 'Log database. Its Ruler turns log queries into alerts, which is what fixed "the error was in journald for 28 hours and nothing read it".',
    'grafana/promtail': 'Ships this host\'s systemd journal into Loki. Relabels from UNIT/USER_UNIT, because almost everything here is a user unit.',
    'quay.io/prometheus/node-exporter': 'Host-level metrics: CPU, memory, filesystems, and the textfile collector carrying the failed-unit floor across both systemd managers.',
    'gcr.io/cadvisor/cadvisor': 'Per-container CPU, memory and restart counts. Needs v0.55.1 or newer on this host -- v0.52.1 silently reports zero containers under Docker\'s containerd snapshotter.',
    'louislam/uptime-kuma': 'Uptime status page and push-heartbeat receiver. Informational: it is a page you have to be looking at, not a detector.',
    'amir20/dozzle': 'Live container log viewer in the browser. Reaches Docker only through socket-proxy, never the raw socket.',
    'tecnativa/docker-socket-proxy': 'Read-only broker in front of the Docker API (POST=0). This is what stops a log viewer from being root on this host.',
    'willfarrell/autoheal': 'Restarts any container that reports its own healthcheck as unhealthy. Matches by the autoheal=true label, host-wide.',

    # --- media-curator: the media stack ---
    'lscr.io/linuxserver/plex': 'Plex Media Server: indexes /mnt/Multimedia and streams it to clients. Runs on host networking, so its ports are the host\'s.',
    'lscr.io/linuxserver/sonarr': 'Finds, downloads and renames TV episodes, then hands the files to Plex\'s library layout.',
    'lscr.io/linuxserver/radarr': 'The same job as Sonarr, for films.',
    'lscr.io/linuxserver/prowlarr': 'One place to manage indexers/trackers; pushes that configuration into Sonarr and Radarr so they are not configured separately.',
    'lscr.io/linuxserver/bazarr': 'Finds and downloads subtitles for what Sonarr and Radarr have already fetched.',
    'lscr.io/linuxserver/qbittorrent': 'The BitTorrent client the *arr apps hand downloads to. Routed through gluetun, so it has no direct internet path of its own.',
    'lscr.io/linuxserver/tautulli': 'Plex usage analytics and history -- who watched what, and whether a stream is transcoding.',
    'qmcgaw/gluetun': 'VPN gateway container. qbittorrent uses its network namespace, so if this stops, downloads lose connectivity rather than leaking.',
    'kometateam/kometa': 'Builds Plex collections and artwork from metadata rules. RF-3: needs a TMDB key and is deliberately stopped until it has one.',

    # --- plane-app ---
    'makeplane/plane-backend': 'Plane\'s Django backend image. Which job it does depends on the container -- see the per-container entries.',

    # --- asf-data-warehouse (local Supabase dev stack) ---
    'public.ecr.aws/supabase/postgres': 'PostgreSQL with Supabase extensions -- the actual database for the local asf-data-warehouse dev stack.',
    'public.ecr.aws/supabase/gotrue': 'Supabase Auth (GoTrue): signup, login and JWT issuance for the dev stack.',
    'public.ecr.aws/supabase/postgrest': 'PostgREST: turns the Postgres schema into a REST API. This is what enforces row-level security in practice.',
    'public.ecr.aws/supabase/realtime': 'Streams Postgres changes to subscribed clients over websockets.',
    'public.ecr.aws/supabase/storage-api': 'Supabase file/object storage API, backed by the same Postgres instance.',
    'public.ecr.aws/supabase/studio': 'The Supabase web admin UI for browsing and editing the dev database.',
    'public.ecr.aws/supabase/kong': 'API gateway routing every Supabase sub-service behind one port.',
    'public.ecr.aws/supabase/postgres-meta': 'Backend API that Studio uses to introspect and modify the database schema.',
    'public.ecr.aws/supabase/edge-runtime': 'Runs Supabase Edge Functions (Deno) locally.',
    'public.ecr.aws/supabase/logflare': 'Log ingestion and analytics for the local Supabase stack.',
    'public.ecr.aws/supabase/vector': 'Collects logs from the Supabase containers and forwards them to Logflare.',
    'public.ecr.aws/supabase/mailpit': 'Catches outbound email locally so signup and password-reset flows can be tested without sending anything.',

    # --- gamelab ---
    'acore/ac-wotlk-worldserver': 'AzerothCore world server: the actual World of Warcraft (WotLK) game world players connect into.',
    'acore/ac-wotlk-authserver': 'AzerothCore auth server: handles login and hands clients off to the world server.',
    'acore/ac-wotlk-db-import': 'One-shot job that imports and updates the AzerothCore database schema, then exits.',
    'acore/ac-wotlk-client-data': 'One-shot job that downloads the WotLK client data files the world server needs, then exits.',
    'registry.gitlab.com/crafty-controller/crafty-4': 'Crafty Controller: web UI for creating and administering Minecraft servers.',

    # --- standalone services ---
    'nocodb/nocodb': 'NocoDB: spreadsheet-style UI over a database. Backs the job-hunter project\'s application tracking.',
    'binwiederhier/ntfy': 'Self-hosted ntfy server -- the push-notification channel every alert on this host ultimately reaches your phone through.',
    'ghcr.io/gethomepage/homepage': 'Homepage: a static dashboard of links and service status tiles.',
    'ghcr.io/open-webui/open-webui': 'Open WebUI: a browser chat front end for local LLMs served by Ollama.',
    'freqtradeorg/freqtrade': 'Freqtrade crypto trading bot in dry-run mode. The ai-quant-trader project was hibernated 2026-07-26; this is deliberately stopped.',
    'moby/buildkit': 'BuildKit builder instance created by `docker buildx`. Infrastructure for building images, not a service.',

    # --- shared infrastructure images ---
    'postgres': 'PostgreSQL database server.',
    'mysql': 'MySQL database server.',
    'redis': 'Redis in-memory data store, typically used as a cache or job queue.',
    'valkey/valkey': 'Valkey, the open-source Redis fork, used as a cache or queue.',
    'rabbitmq': 'RabbitMQ message broker.',
    'minio/minio': 'MinIO S3-compatible object storage.',
}

# Deliberately NOT described, because the purpose is not actually known. Each line
# says what would settle it. Fill one in only after confirming, never by guessing.
UNDESCRIBED: dict[str, str] = {
    'context-server': 'Locally built image (context-server-context-server) with no compose project on disk -- check where it was built from before describing it.',
    'defaulterr': 'varthe/defaulterr, in the media stack. Believed to set default audio/subtitle tracks in Plex by rule -- confirm against its config before writing that down.',
}


def normalize_image(image: str) -> str:
    """Strip the tag and any digest, keeping the registry-qualified repository.

    Docker reports images inconsistently (`redis:alpine`, `lscr.io/linuxserver/radarr:latest`,
    `postgres:15.7-alpine`), and the tag is never what identifies the software.
    A digest is stripped first because `repo@sha256:...` would otherwise survive
    the tag split.
    """
    if not image:
        return ''
    image = image.split('@', 1)[0]
    # Only the final path segment may carry a tag; a registry host may carry a port.
    head, _, tail = image.rpartition('/')
    tail = tail.split(':', 1)[0]
    return f'{head}/{tail}' if head else tail


def derive_structural(name: str, image: str, project: str | None = None,
                      service: str | None = None, ports: list | None = None,
                      mounts: list | None = None) -> str | None:
    """A sentence built only from what Docker already knows.

    This is NOT a description of what the software does -- nothing here can know
    that. It is orientation: which stack this belongs to, what image it came from,
    and what it is wired to. That is genuinely useful for a container nobody has
    described yet, and it has the property the catalog cares most about: it cannot
    be wrong, because every clause is read from `docker inspect` rather than
    recalled from anywhere.

    Returns None when Docker knows nothing beyond the name, so the caller can fall
    through to saying it does not know rather than emitting a sentence with no
    content in it.
    """
    parts: list[str] = []

    if project and service:
        parts.append(f'The `{service}` service of the `{project}` compose stack')
    elif project:
        parts.append(f'Part of the `{project}` compose stack')
    elif service:
        parts.append(f'The `{service}` service')

    repo = normalize_image(image)
    if repo:
        parts.append(f'runs image `{repo}`' if parts else f'Runs image `{repo}`')

    if not parts:
        return None

    sentence = ', '.join(parts) + '.'

    # Published ports and host mounts are the two things that say what a container
    # is actually wired into, which is usually the fastest route to recognising it.
    host_ports = [p for p in (ports or []) if p]
    if host_ports:
        shown = ', '.join(host_ports[:3])
        more = f' (+{len(host_ports) - 3} more)' if len(host_ports) > 3 else ''
        sentence += f' Publishes {shown}{more}.'

    host_paths = [m.split(' -> ')[0] for m in (mounts or []) if m and not m.startswith('/var/lib/docker')]
    host_paths = [h for h in host_paths if h.startswith('/')]
    if host_paths:
        shown = ', '.join(host_paths[:3])
        more = f' (+{len(host_paths) - 3} more)' if len(host_paths) > 3 else ''
        sentence += f' Mounts {shown}{more}.'

    return sentence


def describe(name: str, image: str, oci_description: str | None = None,
             project: str | None = None, service: str | None = None,
             ports: list | None = None, mounts: list | None = None) -> dict:
    """Resolve one container's description.

    Returns {'text': str|None, 'source': str}. `source` is part of the contract, not
    decoration: a curated sentence, a vendor's marketing blurb and a summary derived
    from `docker inspect` are three different kinds of claim, and a UI that presents
    them identically is quietly lying about how much anyone actually knows. `text` of
    None means nobody has written one and Docker knew nothing either -- say so rather
    than rendering an empty space that reads as "nothing to report".

    The structural layer is what makes this self-maintaining: a container created a
    minute ago, that no human has ever heard of, still describes which stack it
    belongs to and what it is wired to, with no catalog entry and no human step.
    """
    if name in BY_NAME:
        return {'text': BY_NAME[name], 'source': 'catalog'}

    by_image = BY_IMAGE.get(normalize_image(image))
    if by_image:
        return {'text': by_image, 'source': 'catalog'}

    if oci_description and oci_description.strip():
        return {'text': oci_description.strip(), 'source': 'image label'}

    structural = derive_structural(name, image, project, service, ports, mounts)
    if structural:
        result = {'text': structural, 'source': 'structural'}
        if name in UNDESCRIBED:
            result['hint'] = UNDESCRIBED[name]
        return result

    if name in UNDESCRIBED:
        return {'text': None, 'source': 'unknown', 'hint': UNDESCRIBED[name]}

    return {'text': None, 'source': 'unknown'}
