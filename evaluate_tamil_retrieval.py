"""Offline textbook retrieval regression checks, without provider calls.

Run with --corpus-dir pointing to grade-scoped exports named tamil-corpus-N.json.
The reviewed test expectations live in tests/fixtures/tamil_retrieval_cases.json.
Exports contain only the indicated subject for each grade; never combine subjects.
"""
import argparse
import json
from pathlib import Path
from textbook_retrieval import TamilBookIndex, compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((Path(__file__).parent / 'tests/fixtures/tamil_retrieval_cases.json').read_text(encoding='utf-8'))
    indexes = {}
    results = []
    for case in cases:
        key = (case['grade'], case['subject'])
        if key not in indexes:
            path = args.corpus_dir / f"tamil-corpus-{case['grade']}.json"
            indexes[key] = TamilBookIndex(json.loads(path.read_text(encoding='utf-8')))
        rows = indexes[key].search(case['question'])
        content = compact('\n'.join(row['content'] for row in rows))
        passed = (all(compact(expected) in content for expected in case['expected'])
                  if case['expected'] else not rows)
        # The budget is the one used by /ask; finding text after it isn't a pass.
        budgeted = compact('\n---\n'.join(row['content'] for row in rows).encode('utf-8')[:12000].decode('utf-8', errors='ignore'))
        passed = passed and all(compact(x) in budgeted for x in case['expected'])
        results.append({'id': case['id'], 'passed': passed,
                        'document_ids': [row.get('id') for row in rows],
                        'context_bytes': len(content.encode('utf-8'))})
        print(case['id'], 'PASS' if passed else 'FAIL')
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if all(row['passed'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
