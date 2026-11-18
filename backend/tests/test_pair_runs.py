"""配对对照受理、冻结、断点恢复与发布闸门。"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.database import Base
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.pair_run import PairRun
from src.services import pair_runs
from src.services.pairing import compute_estimate
from src.services.export import pair_run_csv


class FakeQueue:
    def __init__(self):
        self.pushed = []

    def rpush(self, name, value):
        self.pushed.append((name, value))


@pytest.fixture()
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture()
def world(db, monkeypatch):
    queue = FakeQueue()
    monkeypatch.setattr(pair_runs, 'queue', queue)
    user = User(email='analyst@drying-forest.demo', password_hash='x', role='analyst')
    source_a = Source(key='HX-A', name='现用工艺', filename='a.csv', description='')
    source_b = Source(key='HX-B', name='备用工艺', filename='b.csv', description='')
    db.add_all([user, source_a, source_b])
    db.flush()
    for index in range(6):
        db.add(Record(source_id=source_a.id, reference=f'A-{index + 1:03d}', values={
            'moisture': 30 + index, 'thickness': 4 + index * 0.1, 'temperature': 75, 'airflow': 3, 'minutes': 90 + index}))
        db.add(Record(source_id=source_b.id, reference=f'B-{index + 1:03d}', values={
            'moisture': 30 + index, 'thickness': 4 + index * 0.1, 'temperature': 70, 'airflow': 3, 'minutes': 80 + index}))
    db.commit()
    return {'db': db, 'queue': queue, 'user': user, 'a': source_a, 'b': source_b}


class Input:
    def __init__(self, **kwargs):
        self.name = kwargs['name']
        self.source_a_id = kwargs['source_a_id']
        self.source_b_id = kwargs['source_b_id']
        self.label_a = kwargs.get('label_a', 'A组')
        self.label_b = kwargs.get('label_b', 'B组')
        self.tolerance_humidity = kwargs['tolerance_humidity']
        self.tolerance_thickness = kwargs['tolerance_thickness']


def accept(world, name='配对复核', humidity=0.5, thickness=0.5):
    return pair_runs.create_pair_run(world['db'], world['user'], Input(
        name=name, source_a_id=world['a'].id, source_b_id=world['b'].id,
        tolerance_humidity=humidity, tolerance_thickness=thickness))


def test_acceptance_freezes_records_and_tolerances(world):
    created = accept(world)
    db = world['db']
    stored = db.get(PairRun, created['id'])
    assert stored.snapshot['frozen_counts'] == {'a': 6, 'b': 6}
    assert stored.snapshot['tolerance_humidity'] == '0.5'
    assert stored.snapshot['records_a'][0]['values']['moisture'] == 30
    assert world['queue'].pushed == [(pair_runs.QUEUE_NAME, created['id'])]
    # 直接按明细读取：未发布前不应有配对或区间
    detail = pair_runs.detail(db, created['id'])
    assert detail['pairs'] is None and detail['result'] is None and detail['rows'] is None


def test_late_records_do_not_enter_frozen_pairing(world):
    created = accept(world)
    db = world['db']
    db.add(Record(source_id=world['a'].id, reference='A-999', values={
        'moisture': 30, 'thickness': 4, 'temperature': 75, 'airflow': 3, 'minutes': 10}))
    db.commit()
    stored = db.get(PairRun, created['id'])
    assert len(stored.snapshot['records_a']) == 6
    assert all(row['reference'] != 'A-999' for row in stored.snapshot['records_a'])


def test_completion_publishes_pairs_and_interval(world):
    created = accept(world)
    db = world['db']
    run = pair_runs.claim(db, created['id'])
    assert run is not None and run.state == 'running'
    pair_runs.complete(db, run)
    published = pair_runs.detail(db, created['id'])
    assert published['state'] == 'completed'
    assert published['pairs'] and len(published['pairs']) == 6
    assert published['result']['estimate']['pair_count'] == 6
    assert all(row['diff_minutes'] == pytest.approx(10) for row in published['rows'])
    assert published['published_at']


def test_resume_after_saved_pair_list_reuses_it(world, monkeypatch):
    created = accept(world)
    db = world['db']
    run = pair_runs.claim(db, created['id'])
    # 模拟“配对名单已保存、区间尚未完成”的中断点
    stepped = pair_runs.compute_pairing(
        run.snapshot['records_a'], run.snapshot['records_b'],
        run.snapshot['tolerance_humidity'], run.snapshot['tolerance_thickness'])
    run.pairs = stepped['pairs']
    run.unmatched = stepped['unmatched']
    run.result = {'pairing_meta': {'candidate_pairs': stepped['candidate_pairs'], 'total_normalized_cost': stepped['total_normalized_cost'],
                                   'tolerance_humidity': stepped['tolerance_humidity'], 'tolerance_thickness': stepped['tolerance_thickness'],
                                   'tiebreak': stepped['tiebreak']}}
    run.state = 'estimating'
    db.commit()
    saved = [dict(pair) for pair in run.pairs]

    def forbidden(*args, **kwargs):
        raise AssertionError('已保存配对名单时不应重新选对')

    monkeypatch.setattr(pair_runs, 'compute_pairing', forbidden)
    pair_runs.retry_pair_run(db, world['user'], created['id'])
    retried = pair_runs.claim(db, created['id'])
    pair_runs.complete(db, retried)
    finished = pair_runs.detail(db, created['id'])
    assert finished['state'] == 'completed'
    assert finished['pairs'] == saved
    assert finished['result']['estimate']['pair_count'] == len(saved)


def test_completed_run_cannot_be_retried(world):
    created = accept(world)
    db = world['db']
    pair_runs.complete(db, pair_runs.claim(db, created['id']))
    with pytest.raises(HTTPException) as error:
        pair_runs.retry_pair_run(db, world['user'], created['id'])
    assert error.value.status_code == 409


def test_double_queue_message_does_not_recompute(world):
    created = accept(world)
    db = world['db']
    pair_runs.complete(db, pair_runs.claim(db, created['id']))
    published_at = db.get(PairRun, created['id']).published_at
    assert pair_runs.claim(db, created['id']) is None
    assert db.get(PairRun, created['id']).published_at == published_at


def test_failed_run_can_retry_with_same_snapshot(world):
    created = accept(world)
    db = world['db']
    run = pair_runs.claim(db, created['id'])
    checksum = run.snapshot['checksum']
    pair_runs.fail(db, run, '模拟中断')
    assert pair_runs.detail(db, created['id'])['state'] == 'failed'
    pair_runs.retry_pair_run(db, world['user'], created['id'])
    retried = pair_runs.claim(db, created['id'])
    assert retried.snapshot['checksum'] == checksum
    pair_runs.complete(db, retried)
    assert pair_runs.detail(db, created['id'])['state'] == 'completed'


def test_export_blocked_until_published(world):
    created = accept(world)
    db = world['db']
    with pytest.raises(HTTPException) as error:
        pair_run_csv(db, created['id'])
    assert error.value.status_code == 409
    run = pair_runs.claim(db, created['id'])
    run.pairs = []  # 只有名单、没有区间
    run.result = {'pairing_meta': {}}
    db.commit()
    with pytest.raises(HTTPException):
        pair_run_csv(db, created['id'])
    run.pairs = None  # 回到只有待选对的断点
    run.result = None
    db.commit()
    pair_runs.complete(db, run)
    response = pair_run_csv(db, created['id'])
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/csv')


def test_estimate_survives_reload(world):
    created = accept(world)
    db = world['db']
    pair_runs.complete(db, pair_runs.claim(db, created['id']))
    db.expire_all()
    stored = db.get(PairRun, created['id'])
    assert stored.result['estimate']['pair_count'] == len(stored.pairs)
    assert stored.result['counts']['paired'] == len(stored.pairs)


def test_same_source_rejected(world):
    db = world['db']
    with pytest.raises(HTTPException) as error:
        pair_runs.create_pair_run(db, world['user'], Input(
            name='同源对照', source_a_id=world['a'].id, source_b_id=world['a'].id,
            tolerance_humidity=1, tolerance_thickness=1))
    assert error.value.status_code == 422


def test_invalid_tolerance_rejected(world):
    for humidity, thickness in ((0, 1), (-1, 1), (1, 0), (1000, 1)):
        with pytest.raises(HTTPException) as error:
            accept(world, humidity=humidity, thickness=thickness)
        assert error.value.status_code == 422


def test_too_few_records_rejected(world):
    db = world['db']
    empty = Source(key='HX-C', name='空来源', filename='c.csv', description='')
    db.add(empty)
    db.commit()
    with pytest.raises(HTTPException) as error:
        pair_runs.create_pair_run(db, world['user'], Input(
            name='不足样本', source_a_id=world['a'].id, source_b_id=empty.id,
            tolerance_humidity=1, tolerance_thickness=1))
    assert error.value.status_code == 422
