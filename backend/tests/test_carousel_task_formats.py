"""Exercise the worker entry point with only external infrastructure replaced."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app import models


@pytest.fixture
def tasks(monkeypatch):
    celery = SimpleNamespace(task=lambda **kw: lambda fn: fn, send_task=MagicMock())
    monkeypatch.setitem(sys.modules, 'app.worker', SimpleNamespace(celery_app=celery))
    monkeypatch.setitem(sys.modules, 'app.core.config', SimpleNamespace(llm=object(), pmp_client=MagicMock(), scraper=object()))
    monkeypatch.setitem(sys.modules, 'app.database', SimpleNamespace(SessionLocal=MagicMock()))
    spec = importlib.util.spec_from_file_location('app._carousel_tasks_test', Path(__file__).parents[1] / 'app/carousel_tasks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_passes_current_project_preferences_to_renderer(tasks, monkeypatch, tmp_path):
    draft = models.CarouselDraft(id=1, user_id=2, project_id=3, master_text='Полезный текст о привычках',
                                 platform_accounts={'telegram': [10]}, ctas={'telegram': 'Подпишись'}, story_ctas={})
    settings = models.PostMyPostProjectSetting(carousel_formats={'telegram': {'story': False}})
    db = MagicMock()
    def query(model):
        result = MagicMock()
        result.filter.return_value = result
        result.first.return_value = {models.CarouselDraft: draft, models.PostMyPostProjectSetting: settings}.get(model)
        result.all.return_value = []
        return result
    db.query.side_effect = query
    tasks.SessionLocal.return_value = db
    monkeypatch.setenv('CAROUSEL_ENGINE', 'blocks')
    monkeypatch.setattr(tasks, 'resolve_project_account_handles', lambda *a, **kw: {})
    monkeypatch.setattr(tasks, 'sync_missing_account_avatars', lambda *a, **kw: {})
    monkeypatch.setattr(tasks, 'output_dir', lambda *a: tmp_path)
    renderer = MagicMock(return_value=({'telegram': ['carousel.png']}, {}, {}))
    monkeypatch.setattr(tasks, 'generate_blocks_outputs', renderer)
    monkeypatch.setattr(tasks, 'send_carousel_ready_to_telegram', MagicMock())
    tasks.generate_carousel_task(1)
    assert renderer.call_args.kwargs['carousel_formats']['telegram'] == {'carousel': True, 'story': False}
    assert draft.status == 'ready'
    assert draft.story_slides == {}
    assert draft.story_slide_count == 0


def test_legacy_story_only_does_not_load_or_render_carousel(tasks, monkeypatch, tmp_path):
    draft = models.CarouselDraft(id=1, platform_accounts={'telegram': [10]}, ctas={},
                                 story_ctas={'telegram': 'Напишите нам'}, slide_count=3, story_slide_count=3)
    templates = MagicMock(return_value={})
    render = MagicMock(return_value=['story.png'])
    monkeypatch.setattr(tasks, 'load_template_set', templates)
    monkeypatch.setattr(tasks, 'build_template_package', MagicMock(return_value={}))
    monkeypatch.setattr(tasks, 'render_account_carousel', render)
    monkeypatch.setattr(tasks, 'output_dir', lambda *a: tmp_path)
    carousel, stories, _ = tasks._generate_karpix_draft(
        draft, 'Текст', ['telegram'], {}, {}, {'telegram': {'carousel': False, 'story': True}},
    )
    assert carousel == {}
    assert stories == {'telegram': ['story.png']}
    assert [call.args[1] for call in templates.call_args_list] == ['story']
    assert render.call_args.args[7] == 'story'
