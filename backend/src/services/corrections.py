import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config.project import SPEC
from src.models.workflow import AuditEvent, CorrectionRecord, CorrectionSheet, Observation
from src.services.errors import BusinessError
from src.services.observations import parse_csv

# 更正记录在观测字段之外多一个修订号，同一审修员按修订号合并。
CORRECTION_FIELDS = [*SPEC['fields'],
                     {'key': 'revision', 'label': '修订号', 'type': 'integer', 'min': 1, 'max': 9999, 'example': 2}]
PAYLOAD_KEYS = ('sequence', 'a', 'b', 'c')


def parse_sheet(raw):
    return parse_csv(raw, CORRECTION_FIELDS)


def sheet_key(rows):
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    return 'sheet:' + hashlib.sha256(canonical.encode()).hexdigest()


def record_key(row):
    payload = {key: row[key] for key in PAYLOAD_KEYS}
    return 'corr:' + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def import_sheet(db, rows, actor):
    """整张更正单在一个事务里生效；相同内容的单重试导入不重复计入。"""
    key = sheet_key(rows)
    existing = db.scalar(select(CorrectionSheet).where(CorrectionSheet.sheet_key == key))
    if existing:
        return existing, 0, len(rows), True
    sheet = CorrectionSheet(sheet_key=key, record_count=len(rows), imported_by=actor)
    db.add(sheet)
    try:
        db.flush()
    except IntegrityError as exc:
        raise BusinessError('相同更正单正在导入，请刷新后重试', 409) from exc
    reviewers = {row['reviewer'] for row in rows}
    known = set(db.execute(
        select(CorrectionRecord.reviewer, CorrectionRecord.revision, CorrectionRecord.content_key)
        .where(CorrectionRecord.reviewer.in_(reviewers))))
    items, seen = [], set()
    for row in rows:
        triple = (row['reviewer'], row['revision'], record_key(row))
        if triple in known or triple in seen:
            continue
        seen.add(triple)
        items.append(CorrectionRecord(sheet_id=sheet.id, reviewer=row['reviewer'], revision=row['revision'],
                                      content_key=record_key(row),
                                      payload={key: row[key] for key in PAYLOAD_KEYS}))
    db.add_all(items)
    db.add(AuditEvent(actor=actor, action='correction.imported',
                      detail=f'更正单 #{sheet.id} · 记录 {len(rows)} 条，新计入 {len(items)} 条'))
    try:
        db.flush()
    except IntegrityError as exc:
        raise BusinessError('有相同更正记录刚刚写入，请刷新后重试', 409) from exc
    return sheet, len(items), len(rows) - len(items), False


def build_sample(observations, records):
    """按审修员归并更正：最高修订号生效；最高版计时或试跑次序对不上就先剔除该审修员。

    observations / records 只需提供 payload、sheet_id、reviewer、revision、content_key 属性。
    """
    revisions = {}
    sheet_ids = set()
    for record in records:
        sheet_ids.add(record.sheet_id)
        revisions.setdefault(record.reviewer, {}).setdefault(record.revision, {})[record.content_key] = record.payload
    rows, excluded = [], []
    for reviewer in sorted(revisions):
        top = max(revisions[reviewer])
        contents = revisions[reviewer][top]
        if len(contents) > 1:
            excluded.append({'reviewer': reviewer, 'revision': top,
                             'reason': f'修订 {top} 的计时或试跑次序对不上，待无冲突的更高版'})
            continue
        payload = next(iter(contents.values()))
        rows.append({'reviewer': reviewer, **payload, 'revision': top, 'origin': 'correction'})
    for observation in observations:
        if observation.payload['reviewer'] in revisions:
            continue
        rows.append({**observation.payload, 'revision': None, 'origin': 'ledger'})
    rows.sort(key=lambda row: row['reviewer'])
    return {'rows': rows, 'excluded': excluded, 'sheet_ids': sorted(sheet_ids),
            'last_sheet_id': max(sheet_ids, default=0)}


def resolve_sample(db):
    observations = list(db.scalars(select(Observation).order_by(Observation.id)))
    records = list(db.scalars(select(CorrectionRecord).order_by(CorrectionRecord.id)))
    return build_sample(observations, records)
