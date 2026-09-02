"""Resolution order and honesty of the container description catalog."""
from services import container_catalog as cc


def test_normalize_strips_tags_but_keeps_the_registry_path():
    # The tag is never what identifies the software, and a registry host may carry
    # a port -- so only the final segment may be split on ':'.
    assert cc.normalize_image('redis:alpine') == 'redis'
    assert cc.normalize_image('lscr.io/linuxserver/radarr:latest') == 'lscr.io/linuxserver/radarr'
    assert cc.normalize_image('public.ecr.aws/supabase/postgres:17.6.1.127') == \
        'public.ecr.aws/supabase/postgres'
    assert cc.normalize_image('') == ''


def test_normalize_strips_a_digest_before_the_tag():
    # repo@sha256:... would otherwise survive the tag split and never match.
    assert cc.normalize_image('postgres@sha256:deadbeef') == 'postgres'


def test_name_entry_beats_the_image_entry():
    """Five plane-app containers share one image and do different jobs, so the
    per-name entry has to win or they would all describe themselves as 'the Django
    backend image'."""
    api = cc.describe('plane-app-api-1', 'makeplane/plane-backend:v1.3.1')
    worker = cc.describe('plane-app-worker-1', 'makeplane/plane-backend:v1.3.1')
    assert api['source'] == worker['source'] == 'catalog'
    assert api['text'] != worker['text']
    assert 'API' in api['text']
    assert 'Celery worker' in worker['text']


def test_image_entry_covers_a_container_the_catalog_has_never_seen_by_name():
    # A second Radarr under any name is described for free.
    d = cc.describe('radarr-second-instance', 'lscr.io/linuxserver/radarr:latest')
    assert d['source'] == 'catalog'
    assert 'films' in d['text']


def test_oci_label_is_used_only_when_the_catalog_has_nothing():
    d = cc.describe('mystery', 'some/unknown-image:1', 'Vendor blurb about the thing.')
    assert d == {'text': 'Vendor blurb about the thing.', 'source': 'image label'}

    # ...and never overrides a curated entry, because they are different claims.
    d = cc.describe('prometheus', 'prom/prometheus:v3.5.0', 'Vendor blurb.')
    assert d['source'] == 'catalog'


def test_a_blank_oci_label_is_not_a_description():
    # A whitespace label must not be mistaken for a description: the resolver
    # falls through past it rather than rendering an empty claim.
    d = cc.describe('mystery', 'some/unknown:1', '   ')
    assert d['source'] != 'image label'


def test_an_uncatalogued_container_derives_but_never_invents():
    # The catalog must never invent a PURPOSE. For an image nobody has described,
    # it falls through to the structural layer, whose every clause is read from
    # docker rather than recalled -- and labels it as such, so it cannot pass for
    # knowledge. Generating this with a local LLM was tested and rejected (see the
    # module docstring): it called gluetun a file manager.
    d = cc.describe('something-nobody-documented', 'weird/image:1')
    assert d['source'] == 'structural'
    assert 'weird/image' in d['text']


def test_a_deliberately_undescribed_container_carries_what_would_settle_it():
    """It still gets a structural summary -- the hint rides alongside, so the UI can
    show what IS known while being explicit that the purpose is not."""
    d = cc.describe('context-server', 'context-server-context-server',
                    project='context-server', service='context-server')
    assert d['source'] == 'structural'
    assert 'hint' in d and d['hint']


def test_structural_summary_makes_an_unknown_container_useful_with_no_human_step():
    """The self-maintaining half: a container created a minute ago that nobody has
    ever catalogued still says which stack it belongs to and what it is wired to."""
    d = cc.describe('brand-new-thing', 'someone/never-seen:1',
                    project='newstack', service='api',
                    ports=['127.0.0.1:9999 -> 9999/tcp'], mounts=['/srv/data -> /data'])
    assert d['source'] == 'structural'
    assert 'newstack' in d['text'] and 'api' in d['text']
    assert '9999' in d['text'] and '/srv/data' in d['text']


def test_structural_never_beats_a_curated_entry():
    d = cc.describe('prometheus', 'prom/prometheus:v3.5.0',
                    project='homelab-monitoring', service='prometheus')
    assert d['source'] == 'catalog'


def test_structural_returns_nothing_when_docker_knows_nothing():
    """A sentence with no content in it is worse than admitting ignorance."""
    assert cc.derive_structural('x', '') is None
    assert cc.describe('x', '')['source'] == 'unknown'


def test_docker_internal_mounts_are_not_presented_as_meaningful_paths():
    d = cc.derive_structural('c', 'img:1', 'p', 's',
                             mounts=['/var/lib/docker/volumes/abc/_data -> /data',
                                     '/srv/real -> /real'])
    assert '/srv/real' in d
    assert '/var/lib/docker' not in d


def test_no_container_is_listed_as_undescribed_while_also_being_described():
    """Dead config: an UNDESCRIBED hint that can never surface because an image
    entry already matches is worse than no entry -- it reads as an open question
    that is actually already answered."""
    for name, in ((n,) for n in cc.UNDESCRIBED):
        assert name not in cc.BY_NAME, f'{name} is both described by name and listed as undescribed'
