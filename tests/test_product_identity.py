from pathlib import Path
import tomllib

from click.testing import CliRunner

from replicants.config import HarnessConfig, apply_harness_env_overrides, entity_from_dict
from replicants.identity.personality import PersonalityEngine
from replicants.main import cli
from replicants.utils import self_update


def test_package_and_cli_identity():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
    assert metadata['name'] == 'replicants'
    assert metadata['scripts'] == {'replicant': 'replicants.main:main'}
    result = CliRunner().invoke(cli, ['--version'])
    assert result.exit_code == 0
    assert result.output.startswith('replicant, version ')
    assert CliRunner().invoke(cli, ['--help']).exit_code == 0


def test_data_home_and_prompt_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    cfg = entity_from_dict(HarnessConfig(), {'name': 'test'})
    for path in (cfg.db_path(), cfg.journal_path(), cfg.soma_dir(), cfg.log_path()):
        assert Path(path).is_relative_to(tmp_path / '.replicants')
    assert 'Replicants species' in PersonalityEngine(cfg)._identity_hard_constraints()


def test_environment_prefix_is_replicants(monkeypatch):
    monkeypatch.delenv('REPLICANTS_DEPLOYMENT_MODE', raising=False)
    cfg = HarnessConfig()
    apply_harness_env_overrides(cfg)
    assert cfg.deployment.mode == 'local'
    monkeypatch.setenv('REPLICANTS_DEPLOYMENT_MODE', 'hybrid_railway')
    apply_harness_env_overrides(cfg)
    assert cfg.deployment.mode == 'hybrid_railway'


def test_update_requires_explicit_repo_url(monkeypatch):
    monkeypatch.setattr(self_update, 'PUBLIC_REPO_GIT', '')
    monkeypatch.setattr(self_update, '_run_git', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No network allowed')))
    result = self_update.perform_self_update()
    assert result['ok'] is False
    assert 'REPLICANTS_UPDATE_REPO' in result['error']


def test_entity_import_and_tools_work_without_ar(tmp_path, monkeypatch):
    from replicants.entity import Entity
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.delenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', raising=False)
    cfg = entity_from_dict(HarnessConfig(), {'name': 'test'})
    entity = Entity(cfg)
    assert entity.tools.list_tools()
    assert all(not name.startswith('ar_') for name, _ in entity.tools.list_tools())
