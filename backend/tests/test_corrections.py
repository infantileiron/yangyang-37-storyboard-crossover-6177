import pytest
from sqlalchemy import func, select

from src.domain.analysis import seed
from src.models.base import Session
from src.models.workflow import AnalysisRun, CorrectionRecord, CorrectionSheet, Observation
from src.schemas.requests import CreateRun
from src.services.corrections import import_sheet, parse_sheet, resolve_sample
from src.services.errors import BusinessError
from src.services.observations import add_observations, clean_observation
from src.services.runs import create_run, run_pending

ACTOR = 'analyst@demo.local'


def correction_row(reviewer, revision, sequence='BCA', a=31, b=24, c=32):
    return {'reviewer': reviewer, 'revision': revision, 'sequence': sequence, 'a': a, 'b': b, 'c': c}


def import_rows(rows, actor=ACTOR):
    with Session.begin() as db:
        return import_sheet(db, rows, actor)


def seed_observations():
    rows = [clean_observation(row) for row in seed()]
    with Session.begin() as db:
        add_observations(db, rows, ACTOR, 'observation.imported')


def current_sample():
    with Session() as db:
        return resolve_sample(db)


def test_late_lower_revision_does_not_displace_higher():
    import_rows([correction_row('YG-01', 3, a=30, b=20, c=25)])
    import_rows([correction_row('YG-01', 1, a=99, b=99, c=99)])
    import_rows([correction_row('YG-01', 2, a=88, b=88, c=88)])
    sample = current_sample()
    row = next(item for item in sample['rows'] if item['reviewer'] == 'YG-01')
    assert (row['revision'], row['a'], row['b'], row['c']) == (3, 30, 20, 25)
    assert sample['excluded'] == []


def test_retry_import_is_idempotent():
    rows = [correction_row('YG-01', 1), correction_row('YG-02', 1)]
    sheet, added, skipped, repeated = import_rows(rows)
    assert (added, skipped, repeated) == (2, 0, False)
    again_sheet, again_added, again_skipped, again_repeated = import_rows([dict(row) for row in rows])
    assert (again_added, again_skipped, again_repeated) == (0, 2, True)
    assert again_sheet.id == sheet.id
    with Session() as db:
        assert db.scalar(select(func.count(CorrectionSheet.id))) == 1
        assert db.scalar(select(func.count(CorrectionRecord.id))) == 2
    # 部分重叠的新单只计入新记录
    _, added, skipped, repeated = import_rows([correction_row('YG-01', 1), correction_row('YG-03', 1)])
    assert (added, skipped, repeated) == (1, 1, False)
    with Session() as db:
        assert db.scalar(select(func.count(CorrectionRecord.id))) == 3


def test_conflict_at_top_revision_excludes_reviewer():
    import_rows([correction_row('YG-01', 2, a=30)])
    import_rows([correction_row('YG-01', 2, a=31)])
    sample = current_sample()
    assert sample['rows'] == []
    assert len(sample['excluded']) == 1
    assert sample['excluded'][0]['reviewer'] == 'YG-01'
    assert sample['excluded'][0]['revision'] == 2
    # 试跑次序对不上同样剔除
    import_rows([correction_row('YG-02', 1, sequence='ABC')])
    import_rows([correction_row('YG-02', 1, sequence='CAB')])
    sample = current_sample()
    assert {item['reviewer'] for item in sample['excluded']} == {'YG-01', 'YG-02'}


def test_same_content_same_revision_is_not_conflict():
    import_rows([correction_row('YG-01', 2, a=30)])
    import_rows([correction_row('YG-01', 2, a=30)])
    sample = current_sample()
    assert sample['excluded'] == []
    assert [item['revision'] for item in sample['rows']] == [2]


def test_clean_higher_revision_reinstates_reviewer():
    import_rows([correction_row('YG-01', 2, a=30)])
    import_rows([correction_row('YG-01', 2, a=31)])
    assert current_sample()['excluded'][0]['reviewer'] == 'YG-01'
    import_rows([correction_row('YG-01', 3, a=28)])
    sample = current_sample()
    assert sample['excluded'] == []
    row = next(item for item in sample['rows'] if item['reviewer'] == 'YG-01')
    assert (row['revision'], row['a']) == (3, 28)
    # 更高版自身仍冲突则继续剔除
    import_rows([correction_row('YG-01', 4, a=27)])
    import_rows([correction_row('YG-01', 4, a=26)])
    assert current_sample()['excluded'][0]['revision'] == 4


def test_invalid_sheet_rolls_back_entirely():
    bad = b'reviewer,sequence,a,b,c,revision\nYG-01,BCA,31,24,32,1\nYG-02,BCA,999,24,32,1\n'
    with pytest.raises(BusinessError):
        with Session.begin() as db:
            import_sheet(db, parse_sheet(bad), ACTOR)
    with Session() as db:
        assert db.scalar(select(func.count(CorrectionSheet.id))) == 0
        assert db.scalar(select(func.count(CorrectionRecord.id))) == 0


def test_uncommitted_sheet_is_invisible_to_concurrent_snapshot():
    session = Session()
    try:
        session.begin()
        rows = [correction_row(f'YG-{index:02d}', 1) for index in range(1, 5)]
        import_sheet(session, rows, ACTOR)
        sample = current_sample()  # 另一会话只能看到整单生效前的状态
        assert sample['rows'] == [] and sample['sheet_ids'] == []
        session.commit()
    finally:
        session.close()
    sample = current_sample()
    assert len(sample['rows']) == 4 and sample['sheet_ids'] == [1]


def test_queued_run_keeps_original_sample_and_result_lists_provenance():
    seed_observations()
    with Session.begin() as db:
        first = create_run(db, CreateRun(title='第一次', parameters={}), ACTOR)
        first_id = first.id
    # 排队期间收到更正：YG-01 改时，YG-02 两版对不上
    import_rows([correction_row('YG-01', 1, a=1, b=2, c=3)])
    import_rows([correction_row('YG-02', 1, a=10, b=20, c=30)])
    import_rows([correction_row('YG-02', 1, a=11, b=20, c=30)])
    with Session.begin() as db:
        assert run_pending(db) is True
    with Session() as db:
        first = db.get(AnalysisRun, first_id)
        assert first.status == 'succeeded'
        assert first.sample_size == 24
        provenance = first.result['provenance']
        assert provenance['sheet_ids'] == [] and provenance['excluded'] == []
        assert all(item['origin'] == 'ledger' and item['revision'] is None
                   for item in provenance['revisions'])
        assert len(provenance['revisions']) == 24
    # 新分析取整单生效后的样本：YG-01 用修订 1，YG-02 被剔除
    with Session.begin() as db:
        second = create_run(db, CreateRun(title='第二次', parameters={}), ACTOR)
        second_id = second.id
        assert second.last_sheet_id == 3
        assert second.sample_size == 23
    with Session.begin() as db:
        assert run_pending(db) is True
    with Session() as db:
        second = db.get(AnalysisRun, second_id)
        assert second.status == 'succeeded'
        provenance = second.result['provenance']
        assert provenance['sheet_ids'] == [1, 2, 3]
        used = {item['reviewer']: item for item in provenance['revisions']}
        assert used['YG-01'] == {'reviewer': 'YG-01', 'revision': 1, 'origin': 'correction'}
        assert 'YG-02' not in used
        assert [item['reviewer'] for item in provenance['excluded']] == ['YG-02']
        # 第一次的结果保持原样本结论，不受后续更正影响
        first = db.get(AnalysisRun, first_id)
        assert first.result['provenance']['sheet_ids'] == []
        assert first.sample_size == 24


def test_create_run_without_any_sample_fails():
    with Session.begin() as db:
        with pytest.raises(BusinessError):
            create_run(db, CreateRun(title='空样本', parameters={}), ACTOR)


def test_legacy_run_without_frozen_sample_still_computes():
    seed_observations()
    with Session.begin() as db:
        ids = list(db.scalars(select(Observation.id).order_by(Observation.id)))
        legacy = AnalysisRun(title='旧版排队', owner=ACTOR, parameters={}, observation_ids=ids,
                             last_observation_id=ids[-1], sample_size=len(ids))
        db.add(legacy)
        db.flush()
        legacy_id = legacy.id
    with Session.begin() as db:
        assert run_pending(db) is True
    with Session() as db:
        legacy = db.get(AnalysisRun, legacy_id)
        assert legacy.status == 'succeeded'
        assert 'provenance' not in legacy.result
