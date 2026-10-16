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
    draft = models.CarouselDraft(id=1, user_id=2, project_id=3, status='generating', master_text='Полезный текст о привычках',
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
    tasks.generate_carousel_task(SimpleNamespace(request=SimpleNamespace(retries=0)), 1)
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


@pytest.fixture
def generation(tasks, monkeypatch):
    draft = models.CarouselDraft(id=106, user_id=2, project_id=3, status='generating',
                                 master_text='Полезный текст о привычках',
                                 platform_accounts={'vk': [10]}, ctas={}, story_ctas={})
    user = SimpleNamespace(auto_schedule_enabled=True, training_source=None)
    db = MagicMock()
    def query(model):
        result = MagicMock()
        result.filter.return_value = result
        result.first.return_value = {models.CarouselDraft: draft, models.User: user}.get(model)
        result.all.return_value = []
        return result
    db.query.side_effect = query
    tasks.SessionLocal.return_value = db
    monkeypatch.setenv('CAROUSEL_ENGINE', 'blocks')
    monkeypatch.setattr(tasks, 'resolve_project_account_handles', MagicMock(return_value={}))
    monkeypatch.setattr(tasks, 'sync_missing_account_avatars', MagicMock(return_value={}))
    render = MagicMock(return_value=({'vk': ['slide.png']}, {}, {'vk': {}}))
    monkeypatch.setattr(tasks, '_generate_blocks_draft', render)
    monkeypatch.setattr(tasks, 'send_carousel_ready_to_telegram', MagicMock())
    monkeypatch.setattr(tasks, 'send_carousel_generation_failed_to_telegram', MagicMock())
    monkeypatch.setattr(tasks, 'send_carousel_openrouter_funding_to_telegram', MagicMock())
    task = SimpleNamespace(request=SimpleNamespace(retries=0),
                           max_retries=len(tasks.CREDIT_AUTO_RETRY_DELAYS),
                           retry=MagicMock(side_effect=RuntimeError('retry queued')))
    return SimpleNamespace(draft=draft, db=db, render=render, task=task)


@pytest.mark.parametrize('status', ['ready', 'scheduled', 'published', 'rejected', 'failed', 'awaiting_approval'])
def test_stale_generation_tasks_do_not_overwrite_drafts(tasks, generation, status):
    generation.draft.status = status
    tasks.generate_carousel_task(generation.task, 106)
    generation.render.assert_not_called()
    assert generation.draft.status == status
    generation.db.close.assert_called_once()


def test_notification_failure_preserves_ready_deck_and_still_queues_schedule(tasks, generation):
    tasks.send_carousel_ready_to_telegram.side_effect = RuntimeError('Telegram unavailable')
    tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'ready'
    assert generation.draft.slides == {'vk': ['slide.png']}
    tasks.celery_app.send_task.assert_called_once()
    tasks.send_carousel_generation_failed_to_telegram.assert_not_called()


def test_schedule_queue_failure_preserves_ready_deck(tasks, generation):
    tasks.celery_app.send_task.side_effect = RuntimeError('Redis unavailable')
    tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'ready'
    assert generation.draft.error is None
    tasks.send_carousel_generation_failed_to_telegram.assert_not_called()


def test_manual_recovery_can_disable_auto_schedule(tasks, generation):
    tasks.generate_carousel_task(generation.task, 106, schedule_after=False)
    assert generation.draft.status == 'ready'
    tasks.celery_app.send_task.assert_not_called()


def test_generation_failure_rolls_back_before_saving_error(tasks, generation):
    generation.render.side_effect = ValueError('Broken plan')
    with pytest.raises(ValueError, match='Broken plan'):
        tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'failed'
    assert generation.draft.error == 'Broken plan'
    generation.db.rollback.assert_called_once()
    tasks.celery_app.send_task.assert_not_called()
    tasks.send_carousel_ready_to_telegram.assert_not_called()
    generation.db.close.assert_called_once()


def test_credit_failure_schedules_retry_and_successful_retry_recovers(tasks, generation):
    generation.render.side_effect = tasks.OpenRouterInsufficientCreditsError()
    with pytest.raises(RuntimeError, match='retry queued'):
        tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'waiting_for_credits'
    assert generation.task.retry.call_args.kwargs['countdown'] == 900
    tasks.send_carousel_openrouter_funding_to_telegram.assert_called_once()
    generation.render.side_effect = None
    tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'ready'
    assert generation.draft.error is None


def test_credit_retry_budget_exhaustion_stops_and_marks_failed(tasks, generation):
    generation.task.request.retries = generation.task.max_retries
    generation.render.side_effect = tasks.OpenRouterInsufficientCreditsError()
    with pytest.raises(tasks.OpenRouterInsufficientCreditsError):
        tasks.generate_carousel_task(generation.task, 106)
    assert generation.draft.status == 'failed'
    generation.task.retry.assert_not_called()
    tasks.send_carousel_generation_failed_to_telegram.assert_called_once()
