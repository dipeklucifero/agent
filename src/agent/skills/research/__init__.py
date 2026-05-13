"""Research skills - web fetch + note-taking.

ROADMAP:
  - research.web_search(query, k=5) -> [ {title, url, snippet} ]
      Use a privacy-respecting backend like SearXNG (self-hostable) or
      DuckDuckGo HTML. Avoid keyed APIs for a personal agent.
  - research.fetch_url(url) -> text  (trafilatura for clean extraction)
  - notes.add(tag, body) -> note_id
  - notes.search(query, k=10) -> [ {ts, tag, body} ]  (uses notes_fts FTS5)

Implementation notes:
  - fetch_url should truncate to ~8KB and strip scripts/styles; large pages
    OOM a 2GB VPS fast.
  - notes.search uses the SQLite FTS5 triggers already set up in
    memory/db.py - no new schema needed.
"""
