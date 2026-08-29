# Song Discovery

A small, dependency-free web app: search an artist to see their whole
catalog and a short bio, or search a song to find tracks like it.

- Search an **artist** (e.g. "Imagine Dragons") → full track list, artwork,
  a Wikipedia bio, and a link to watch their videos on YouTube.
- Search a **song** (e.g. "Believer") → matching tracks; click one to see
  a 30-second preview, artist facts, a YouTube video link, and a "Songs
  like this one" list (same genre + more from the same artist).

No API keys or build step needed — it only calls the free, keyless
[iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/)
for music data/previews and the
[Wikipedia REST API](https://www.mediawiki.org/wiki/API:REST_API) for bios.

## Run it

```sh
cd song-discovery
python3 -m http.server 8000
```

Then open http://localhost:8000 in a browser. (Opening `index.html`
directly with `file://` also works in most browsers.)
