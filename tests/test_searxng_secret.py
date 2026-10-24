"""The optional search service must reject missing secrets before its process starts."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ENTRYPOINT = Path(__file__).parents[1] / 'docker/searxng/require-secret.sh'


@pytest.mark.parametrize('secret', [None, ''])
def test_missing_search_secret_never_starts_the_service(tmp_path, secret):
    marker = tmp_path / 'started'
    env = dict(os.environ)
    env.pop('SEARXNG_SECRET', None)
    if secret is not None:
        env['SEARXNG_SECRET'] = secret
    process = subprocess.run(['sh', str(ENTRYPOINT), sys.executable, '-c',
        'from pathlib import Path; import sys; Path(sys.argv[1]).touch()', str(marker)],
        env=env, capture_output=True, text=True)
    assert process.returncode != 0
    assert 'SEARXNG_SECRET' in process.stderr
    assert not marker.exists()


def test_configured_search_secret_starts_original_process_with_its_arguments(tmp_path):
    marker = tmp_path / 'started'
    process = subprocess.run(['sh', str(ENTRYPOINT), sys.executable, '-c',
        'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])', str(marker), 'synthetic-ready'],
        env={**os.environ, 'SEARXNG_SECRET': 'synthetic-test-only-secret'}, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert marker.read_text() == 'synthetic-ready'
