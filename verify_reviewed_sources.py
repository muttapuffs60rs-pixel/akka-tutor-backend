"""Read-only source fingerprint verification; never changes review status.

Downloads the public official PDFs to ignored tmp/pdfs and fails if the publisher
replaced a file. A changed PDF must be visually reviewed before updating metadata.
"""
import hashlib
from pathlib import Path
import ssl
import httpx
from reviewed_sources import reviewed_database


def main():
    target = Path(__file__).parent / 'tmp/pdfs'
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(verify=ssl.create_default_context(), timeout=120) as client:
        for row in reviewed_database().rows:
            response = client.get(row['source_url'])
            response.raise_for_status()
            if not response.content.startswith(b'%PDF-'):
                raise ValueError('Source is not a PDF')
            if hashlib.sha256(response.content).hexdigest() != row['source_sha256']:
                raise ValueError(f"Source changed: {row['id']}; review required")
            (target / (row['id'] + '.pdf')).write_bytes(response.content)
            print(f"PASS {row['id']}: source fingerprint unchanged")


if __name__ == '__main__':
    main()
