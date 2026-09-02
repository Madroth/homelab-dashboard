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
    assert cc.describe('mystery', 'some/unknown:1', '   ')['text'] is None


def test_an_unknown_container_returns_none_rather_than_a_guess():
    """The catalog must never invent. None is what makes the UI say it does not know."""
    d = cc.describe('something-nobody-documented', 'weird/image:1')
    assert d['text'] is None
    assert d['source'] == 'unknown'


def test_a_deliberately_undescribed_container_carries_what_would_settle_it():
    d = cc.describe('context-server', 'context-server-context-server')
    assert d['text'] is None
    assert 'hint' in d and d['hint']


def test_no_container_is_listed_as_undescribed_while_also_being_described():
    """Dead config: an UNDESCRIBED hint that can never surface because an image
    entry already matches is worse than no entry -- it reads as an open question
    that is actually already answered."""
    for name, in ((n,) for n in cc.UNDESCRIBED):
        assert name not in cc.BY_NAME, f'{name} is both described by name and listed as undescribed'
