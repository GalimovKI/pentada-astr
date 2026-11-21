"""Read-only HTTP regression against the official corpus and configured search engine."""
import argparse
import atexit
from importlib import import_module
import os

import json
import urllib.request
from urllib.error import HTTPError
from mail_search.core.settings import Settings
from mail_search.ingestion.dataset import load_dataset

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8000')
base = parser.parse_args().url.rstrip('/')
def get(path):
    with urllib.request.urlopen(base + path) as r:
        assert r.status == 200
        return json.load(r)
assert get('/health/live') == {'status': 'live'}
assert get('/health/ready') == {'status': 'ready'}
users = get('/api/v1/mailboxes')['items']
assert len(users) == 12 and users == sorted(users)
config = Settings(database_url='postgresql://unused', **{
    key: os.environ[key.upper()] for key in ('search_config', 'search_dataset', 'search_engine_factory')
    if key.upper() in os.environ})
dataset = load_dataset(config.search_dataset)
module, name = config.search_engine_factory.split(':')
loaded = getattr(import_module(module), name)(config)
atexit.register(loaded.close)
engine = loaded.engine
queries = dataset.queries
opened = 0
for query in queries:
    path = '/api/v1/mailboxes/' + query.synthetic_user
    body = json.dumps(dict(query=query.query, query_date=str(query.query_date), limit=10)).encode()
    req = urllib.request.Request(base + path + '/search', data=body, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response:
        assert 'search;dur=' in response.headers['Server-Timing']
        hits = json.load(response)['items']
    expected = engine.search(query.request(), 10)
    assert [h['doc_id'] for h in hits] == [h.doc_id for h in expected]
    for hit in hits:
        doc = dataset.documents[hit['doc_id']]
        assert hit['snippet'] == doc.doc[:200] and 'doc' not in hit
        assert hit['synthetic_user'] == query.synthetic_user
        assert hit['doc_dt'] is None or hit['doc_dt'] <= str(query.query_date)
    if hits:
        doc = get(path + '/messages/' + hits[0]['doc_id'] + '?query_date=' + str(query.query_date))['item']
        assert doc['doc'] == dataset.documents[doc['doc_id']].doc
        opened += 1
# Exercise full corpus pagination, including NULL dates, against independent ordering.
user = users[0]
expected = sorted([d for d in dataset.documents.values() if d.synthetic_user == user],
                  key=lambda d: (d.doc_dt is None, -d.doc_dt.toordinal() if d.doc_dt else 0, d.doc_id))
ids, cursor, pages = [], None, 0
while True:
    path = '/api/v1/mailboxes/' + user + '/messages?query_date=9999-12-31&limit=200'
    if cursor:
        path += '&cursor=' + cursor
    data = get(path)
    ids += [h['doc_id'] for h in data['items']]
    pages += 1
    cursor = data['next_cursor']
    if not cursor:
        break
assert ids == [d.doc_id for d in expected]
print(json.dumps(dict(queries_checked=len(queries), opened_messages=opened, mailboxes=len(users),
                      paginated_messages=len(ids), pages=pages, ranking_matches=True), indent=2))
