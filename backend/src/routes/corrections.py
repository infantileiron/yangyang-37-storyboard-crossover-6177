from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from src.constants.enums import Role
from src.controllers.views import sheet_view
from src.models.base import Session
from src.models.workflow import CorrectionSheet
from src.services.auth import current_user, roles
from src.services.corrections import CORRECTION_FIELDS, import_sheet, parse_sheet, resolve_sample
from src.services.errors import BusinessError
from src.utils.formatting import csv_text

router = APIRouter(prefix='/api/corrections')
editor = roles(Role.ANALYST, Role.SUPERVISOR)


@router.get('')
def index(user=Depends(current_user)):
    with Session() as db:
        sheets = db.scalars(select(CorrectionSheet).order_by(CorrectionSheet.id.desc()).limit(100))
        return [sheet_view(sheet) for sheet in sheets]


@router.get('/effective')
def effective(user=Depends(current_user)):
    with Session() as db:
        sample = resolve_sample(db)
        return {'rows': sample['rows'], 'excluded': sample['excluded'],
                'sheet_count': len(sample['sheet_ids']), 'last_sheet_id': sample['last_sheet_id']}


@router.get('/template')
def template(user=Depends(current_user)):
    payload = csv_text([{'key': field['key'], 'label': field['key']} for field in CORRECTION_FIELDS],
                       [{field['key']: field.get('example') for field in CORRECTION_FIELDS}])
    return Response(payload, media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=corrections-template.csv'})


def import_payload(payload, actor):
    rows = parse_sheet(payload)
    with Session.begin() as db:
        sheet, added, skipped, repeated = import_sheet(db, rows, actor)
        return {'sheet_id': sheet.id, 'added': added, 'skipped': skipped, 'already_imported': repeated}


@router.post('/import')
async def import_csv(request: Request, user=Depends(editor)):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 512 * 1024:
            raise BusinessError('CSV 文件上限 512 KB', 413)
        raw.extend(chunk)
    return await run_in_threadpool(import_payload, bytes(raw), user['sub'])
