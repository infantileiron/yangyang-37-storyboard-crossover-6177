from fastapi.testclient import TestClient

from src.main import app
from src.models.base import Session
from src.services.auth import sign_in
from src.services.runs import run_pending

OBSERVATIONS = (
    'reviewer,sequence,a,b,c\n'
    'YG-01,ABC,31,24,32\n'
    'YG-02,BCA,28,22,30\n'
    'YG-03,CAB,35,29,33\n'
    'YG-04,ACB,26,20,27\n'
    'YG-05,BAC,33,25,34\n'
)
CORRECTIONS = 'reviewer,sequence,a,b,c,revision\nYG-01,ABC,20,24,32,1\n'


def token_for(email, password):
    return {'Authorization': f'Bearer {sign_in(email, password)["token"]}'}


def test_correction_sheet_api_flow():
    analyst = token_for('analyst@demo.local', 'Analyst-2026!')
    viewer = token_for('viewer@demo.local', 'Viewer-2026!')
    with TestClient(app) as client:
        response = client.post('/api/observations/import', content=OBSERVATIONS.encode(),
                               headers={**analyst, 'Content-Type': 'text/csv'})
        assert response.status_code == 200, response.text
        assert response.json()['added'] == 5

        # 只读角色不能导入更正单
        response = client.post('/api/corrections/import', content=CORRECTIONS.encode(),
                               headers={**viewer, 'Content-Type': 'text/csv'})
        assert response.status_code == 403

        response = client.post('/api/corrections/import', content=CORRECTIONS.encode(),
                               headers={**analyst, 'Content-Type': 'text/csv'})
        assert response.status_code == 200, response.text
        report = response.json()
        assert (report['added'], report['skipped'], report['already_imported']) == (1, 0, False)

        # 重试导入不重复计入
        response = client.post('/api/corrections/import', content=CORRECTIONS.encode(),
                               headers={**analyst, 'Content-Type': 'text/csv'})
        assert response.json()['already_imported'] is True
        assert response.json()['added'] == 0

        response = client.get('/api/corrections', headers=viewer)
        assert [sheet['record_count'] for sheet in response.json()] == [1]
        response = client.get('/api/corrections/effective', headers=viewer)
        effective = response.json()
        assert effective['last_sheet_id'] == 1 and effective['excluded'] == []
        corrected = {row['reviewer']: row for row in effective['rows'] if row['origin'] == 'correction'}
        assert corrected['YG-01']['a'] == 20 and corrected['YG-01']['revision'] == 1

        # 发起分析并跑 worker，结果写清用了哪些修订
        response = client.post('/api/runs', json={'title': '更正后复核', 'parameters': {}}, headers=analyst)
        assert response.status_code == 201, response.text
        run_id = response.json()['id']
        assert response.json()['last_sheet_id'] == 1
        with Session.begin() as db:
            assert run_pending(db) is True
        response = client.get(f'/api/runs/{run_id}', headers=analyst)
        assert response.status_code == 200, response.text
        provenance = response.json()['result']['provenance']
        assert provenance['sheet_ids'] == [1] and provenance['excluded'] == []
        used = {row['reviewer']: row for row in provenance['revisions']}
        assert used['YG-01'] == {'reviewer': 'YG-01', 'revision': 1, 'origin': 'correction'}
        assert used['YG-02']['origin'] == 'ledger'
