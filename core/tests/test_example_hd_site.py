#!/usr/bin/env python3
"""CF-0470: the Example brand site (`site/example-hd/`) - the home page, privacy
policy and terms the OAuth app's Branding page and the YouTube API audit link
to. No network: every check reads the files.

What is pinned:

* every page parses with `html.parser`, has `<html lang>`, a `<title>` and a
  viewport meta tag, and pulls in only the site's own stylesheet - no
  `<script>` at all, no `<link>` to another host;
* every internal link (href/src that is not http(s)/mailto/#) points at a file
  that exists in the site directory;
* the privacy policy links the Google Privacy Policy and the Google page where
  access is revoked (YouTube API Services Developer Policies III.A.2.c/h), the
  terms link the YouTube Terms of Service (III.A.1);
* the scopes the privacy policy names are exactly the ones
  `agents/publisher/publisher_auth.py` asks for (`SCOPES`) - a scope added or
  dropped in the code without the policy turns this red;
* the home page carries the Search Console placeholder until the tag replaces
  it, and the effective date of both legal pages is set.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "example-hd"
sys.path.insert(0, str(ROOT / "agents" / "publisher"))

import publisher_auth                                           # noqa: E402

PAGES = ("index.html", "privacy.html", "terms.html", "404.html")
GOOGLE_PRIVACY = "http://www.google.com/policies/privacy"
REVOKE = "https://security.google.com/settings/security/permissions"
YOUTUBE_TOS = "https://www.youtube.com/t/terms"
SCOPE_RE = re.compile(r"https://www\.googleapis\.com/auth/[A-Za-z0-9._-]+")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = ""
        self._in_title = False
        self.viewport = False
        self.scripts = []
        self.links = []          # <link> tags: (rel, href)
        self.refs = []           # every href / src
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("name") == "viewport" and "width=device-width" in (a.get("content") or ""):
            self.viewport = True
        elif tag == "script":
            self.scripts.append(a)
        elif tag == "link":
            self.links.append((a.get("rel"), a.get("href")))
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.text.append(data)


def parse(name):
    p = Page()
    p.feed((SITE / name).read_text(encoding="utf-8"))
    p.close()
    return p


def is_external(ref):
    return ref.startswith(("http://", "https://", "mailto:", "#", "//"))


def internal_target(ref):
    path = ref.split("#", 1)[0].split("?", 1)[0]
    return SITE / path.lstrip("/") if path else None


def test_every_page_and_the_stylesheet_exist():
    missing = [n for n in PAGES + ("style.css", "README.md") if not (SITE / n).is_file()]
    assert not missing, f"site/example-hd/ lacks {missing}"


def test_pages_parse_with_lang_title_viewport():
    for name in PAGES:
        p = parse(name)
        assert p.lang, f"{name}: <html> has no lang"
        assert p.title.strip(), f"{name}: no <title>"
        assert p.viewport, f"{name}: no viewport meta tag (width=device-width)"


def test_no_scripts_and_no_external_link_tags():
    for name in PAGES:
        p = parse(name)
        assert not p.scripts, f"{name}: has <script> {p.scripts} - the site has no JavaScript"
        for rel, href in p.links:
            assert href and not is_external(href), (
                f"{name}: <link rel={rel} href={href}> - only the site's own stylesheet, "
                "no external resources")
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(" not in css, "style.css pulls in an external resource"


def test_internal_links_point_at_existing_files():
    broken = []
    for name in PAGES:
        for ref in parse(name).refs:
            if is_external(ref):
                continue
            target = internal_target(ref)
            if target is not None and not target.is_file():
                broken.append(f"{name} -> {ref}")
    assert not broken, f"internal links to missing files: {broken}"


def test_privacy_links_google_privacy_policy_and_revocation_page():
    p = parse("privacy.html")
    assert GOOGLE_PRIVACY in p.refs, "privacy.html does not link the Google Privacy Policy (III.A.2.c)"
    assert REVOKE in p.refs, "privacy.html does not link the Google revocation page (III.A.2.h)"
    text = " ".join(p.text)
    assert "YouTube API Services" in text, "privacy.html does not say the Tool uses YouTube API Services (III.A.2.b)"
    assert "{{CONTACT_EMAIL}}" in text or "@" in text, "privacy.html has no contact (III.A.2.i)"


def test_terms_link_youtube_terms_of_service():
    p = parse("terms.html")
    assert YOUTUBE_TOS in p.refs, "terms.html does not link the YouTube Terms of Service (III.A.1)"
    assert "agree to be bound by" in " ".join(" ".join(p.text).split()), (
        "terms.html does not state that users agree to be bound by the YouTube Terms of Service")


def test_privacy_names_exactly_the_scopes_the_publisher_requests():
    named = set(SCOPE_RE.findall((SITE / "privacy.html").read_text(encoding="utf-8")))
    asked = set(publisher_auth.SCOPES)
    assert named == asked, (
        f"privacy.html names scopes {sorted(named)}, publisher_auth.SCOPES asks for "
        f"{sorted(asked)} - change the policy (and docs/api-audit/) together with the code")






def test_search_console_placeholder_or_tag_on_home_page():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert ("<!-- GOOGLE_SITE_VERIFICATION -->" in html
            or 'name="google-site-verification"' in html), (
        "index.html has neither the Search Console placeholder nor the verification tag")


def test_legal_pages_carry_effective_date():
    for name in ("privacy.html", "terms.html"):
        assert re.search(r"Effective date: \d{4}-\d{2}-\d{2}", (SITE / name).read_text(encoding="utf-8")), (
            f"{name}: no 'Effective date: YYYY-MM-DD'")


def test_scope_check_catches_a_drift():
    """The guard itself: a scope missing from the policy is seen."""
    named = set(SCOPE_RE.findall((SITE / "privacy.html").read_text(encoding="utf-8")))
    drifted = set(publisher_auth.SCOPES) | {"https://www.googleapis.com/auth/youtube.force-ssl"}
    assert named != drifted


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            traceback.print_exc()
            print(f"FAIL {t.__name__}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
