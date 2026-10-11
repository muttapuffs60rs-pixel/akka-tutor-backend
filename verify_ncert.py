"""Read-only live checks for curriculum isolation and ingestion counts."""
import argparse
import json
import os
from pathlib import Path
import ssl

import httpx
from dotenv import load_dotenv
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=ROOT/'curriculum/ncert_ingestion_report.json')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'],
                       options=SyncClientOptions(httpx_client=httpx.Client(
                           verify=ssl.create_default_context(), timeout=120),
                           auto_refresh_token=False, persist_session=False))
    checks = []
    manifest = json.loads((ROOT/'curriculum/ncert_manifest.json').read_text())
    report = json.loads(args.report.read_text())
    expected = {f"{b['code']}{chapter:02}" for b in manifest for chapter in b['chapter_ids']}
    assert set(report) == expected, f'Import is incomplete: {len(expected-set(report))} chapters missing'
    assert all(row.get('verified') for row in report.values())
    baseline = {6:5922, 7:6217, 8:7429, 9:8288, 10:11554, 11:45146, 12:48085}
    for grade in range(6, 13):
        tn_count = (db.table('documents').select('id', count='exact', head=True)
                    .eq('board','tn').eq('grade_level',grade).execute().count)
        assert tn_count == baseline[grade], f'State Board Class {grade} count changed'
        cbse_count = (db.table('documents').select('id', count='exact', head=True)
                      .eq('board','cbse').eq('grade_level',grade).execute().count)
        expected_count = sum(row['chunks'] for row in report.values() if row['grade']==grade)
        assert cbse_count == expected_count, f'CBSE Class {grade} stored count differs from import report'
        sample = (db.table('documents').select('content,embedding,subject,book_code')
                  .eq('board', 'cbse').eq('grade_level', grade).limit(1).execute().data)
        if not sample:
            raise AssertionError(f'Missing CBSE Class {grade}')
        sample = sample[0]
        vector = sample['embedding']
        if isinstance(vector, str):
            vector = json.loads(vector)
        params = dict(query_embedding=vector, query_text=sample['content'][:100],
                      match_threshold=.1, match_count=5, filter_grade=grade,
                      filter_subject=sample['subject'], filter_board='cbse')
        matches = db.rpc('match_board_documents', params).execute().data
        assert matches, f'No CBSE retrieval for Class {grade}'
        for match in matches:
            rows = (db.table('documents').select('id').eq('board', 'cbse')
                    .eq('grade_level', grade).eq('subject', sample['subject'])
                    .eq('content', match['content']).limit(1).execute().data)
            assert rows, 'Cross-curriculum result'
        checks.append(dict(grade=grade, board='cbse', matches=len(matches), chunks=cbse_count,
                           state_board_chunks_unchanged=tn_count, verified=True))

    # Same grade, same subject, same query/vector: board is the only changing filter.
    sample = (db.table('documents').select('content,embedding').eq('board','cbse')
              .eq('grade_level',9).eq('subject','Science').limit(1).execute().data)[0]
    vector = json.loads(sample['embedding']) if isinstance(sample['embedding'],str) else sample['embedding']
    for board in ('tn','cbse'):
        params = dict(query_embedding=vector,query_text=sample['content'][:100],
                      match_threshold=-1,match_count=5,filter_grade=9,filter_subject='Science')
        matches = db.rpc('match_board_documents',dict(params,filter_board=board)).execute().data
        assert matches
        for match in matches:
            rows = (db.table('documents').select('id').eq('board',board).eq('grade_level',9)
                    .eq('subject','Science').eq('content',match['content']).limit(1).execute().data)
            assert rows, f'Class 9 {board} mixed with another board'
        if board=='tn':
            legacy=db.rpc('hybrid_match_documents',params).execute().data
            assert legacy==matches, 'Legacy search no longer restricted to State Board'
        checks.append(dict(grade=9,subject='Science',board=board,same_query_isolated=True))
    (ROOT/'curriculum/ncert_live_verification.json').write_text(json.dumps(checks,indent=2))
    print('PASS: Classes 6–12 retrievable; identical Class 9 searches isolated by board.')


if __name__ == '__main__':
    main()
