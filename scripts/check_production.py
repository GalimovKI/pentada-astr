"""Read-only smoke check for the built frontend and same-origin API proxy."""
import argparse
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    base = parser.parse_args().url.rstrip("/")

    def request(path, status=200, *, method="GET", body=None):
        req = Request(base + path, data=body, method=method,
                      headers={"Content-Type": "application/json"} if body else {})
        try:
            response = urlopen(req, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == status, (path, response.status, status)
            return response.headers, response.read()

    for endpoint, state in (("live", "live"), ("ready", "ready")):
        headers, body = request("/health/" + endpoint)
        assert json.loads(body) == {"status": state}
        assert headers["Cache-Control"] == "no-store"
    headers, html = request("/")
    assert headers.get_content_type() == "text/html"
    assets = re.findall(r'(?:src|href)="(/[^"?]+)"', html.decode())
    assets += ["/fonts/VKSansDisplay-Regular.woff2", "/fonts/VKSansDisplay-Medium.woff2"]
    for asset in assets:
        headers, content = request(asset)
        assert content and headers["Cache-Control"] == "no-cache"
    request("/assets/missing.js", 404)
    headers, body = request("/api/v1/does-not-exist", 404)
    assert headers.get_content_type() == "application/json"
    assert json.loads(body) == {"error": {"code": "http_error"}}
    _, body = request("/api/v1/mailboxes", 405, method="POST", body=b"{}")
    assert json.loads(body) == {"error": {"code": "http_error"}}
    _, body = request("/api/v1/mailboxes")
    boxes = json.loads(body)["items"]
    assert boxes
    headers, body = request("/api/v1/mailboxes/" + boxes[0] + "/search", 422,
                            method="POST", body=b'{"query":""}')
    assert json.loads(body) == {"error": {"code": "validation_error"}}
    assert "search;dur=" in headers["Server-Timing"]
    assert headers["Cache-Control"] == "no-store"
    print(json.dumps({"static_assets": len(assets), "mailboxes": len(boxes),
                      "proxy_methods_errors_headers": "ok"}))


if __name__ == "__main__":
    main()
