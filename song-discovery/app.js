// Song Discovery — search an artist to see their catalog + facts,
// or search a song to find similar tracks. Uses only free, keyless APIs:
// iTunes Search/Lookup (music data + 30s previews) and Wikipedia (bios).

const ITUNES_SEARCH = "https://itunes.apple.com/search";
const ITUNES_LOOKUP = "https://itunes.apple.com/lookup";
const WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/";

const els = {
  form: document.getElementById("search-form"),
  input: document.getElementById("search-input"),
  status: document.getElementById("status"),
  artistView: document.getElementById("artist-view"),
  artistArt: document.getElementById("artist-art"),
  artistName: document.getElementById("artist-name"),
  artistBio: document.getElementById("artist-bio"),
  artistVideosLink: document.getElementById("artist-videos-link"),
  artistTracks: document.getElementById("artist-tracks"),
  songResults: document.getElementById("song-results"),
  songList: document.getElementById("song-list"),
  detailView: document.getElementById("detail-view"),
  backBtn: document.getElementById("back-btn"),
  detailArt: document.getElementById("detail-art"),
  detailTitle: document.getElementById("detail-title"),
  detailArtist: document.getElementById("detail-artist"),
  detailGenre: document.getElementById("detail-genre"),
  detailAudio: document.getElementById("detail-audio"),
  detailVideoLink: document.getElementById("detail-video-link"),
  detailStoreLink: document.getElementById("detail-store-link"),
  detailBio: document.getElementById("detail-bio"),
  similarList: document.getElementById("similar-list"),
};

let lastSongResults = []; // remembered so "Back" can restore the list

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const query = els.input.value.trim();
  if (query) runSearch(query);
});

els.backBtn.addEventListener("click", () => {
  hideAll();
  if (lastSongResults.length) {
    els.songResults.hidden = false;
  }
});

function hideAll() {
  els.artistView.hidden = true;
  els.songResults.hidden = true;
  els.detailView.hidden = true;
  els.status.hidden = true;
}

function setStatus(msg) {
  els.status.hidden = false;
  els.status.textContent = msg;
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function youtubeSearchUrl(query) {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
}

async function runSearch(query) {
  hideAll();
  setStatus(`Searching for "${query}"...`);
  try {
    // First, see if the query is really an artist (e.g. "Imagine Dragons").
    const artistMatches = await fetchJSON(
      `${ITUNES_SEARCH}?term=${encodeURIComponent(query)}&entity=musicArtist&limit=1`
    );
    const artist = artistMatches.results[0];
    const looksLikeArtist =
      artist && artist.artistName.toLowerCase() === query.toLowerCase();

    if (looksLikeArtist) {
      await showArtist(artist);
    } else {
      await showSongResults(query);
    }
  } catch (err) {
    hideAll();
    setStatus(`Something went wrong: ${err.message}`);
  }
}

async function showArtist(artist) {
  setStatus(`Loading ${artist.artistName}'s catalog...`);
  const [tracksData, bio] = await Promise.all([
    fetchJSON(`${ITUNES_LOOKUP}?id=${artist.artistId}&entity=song&limit=50`),
    getWikipediaSummary(artist.artistName),
  ]);

  const tracks = tracksData.results.filter((r) => r.wrapperType === "track");

  els.artistName.textContent = artist.artistName;
  els.artistArt.src = tracks[0]?.artworkUrl100?.replace("100x100", "300x300") || "";
  els.artistArt.alt = artist.artistName;
  els.artistBio.textContent = bio || "No biography found.";
  els.artistVideosLink.href = youtubeSearchUrl(`${artist.artistName} official videos`);

  els.artistTracks.innerHTML = "";
  tracks.forEach((track) => els.artistTracks.appendChild(trackItem(track)));

  hideAll();
  els.artistView.hidden = false;
}

async function showSongResults(query) {
  const data = await fetchJSON(
    `${ITUNES_SEARCH}?term=${encodeURIComponent(query)}&entity=song&limit=25`
  );
  const tracks = data.results;

  if (!tracks.length) {
    hideAll();
    setStatus(`No songs found for "${query}". Try another search.`);
    return;
  }

  lastSongResults = tracks;
  els.songList.innerHTML = "";
  tracks.forEach((track) => els.songList.appendChild(trackItem(track)));

  hideAll();
  els.songResults.hidden = false;
}

function trackItem(track) {
  const li = document.createElement("li");
  li.className = "track-item";
  li.innerHTML = `
    <img src="${track.artworkUrl60 || track.artworkUrl100 || ""}" alt="" />
    <div class="track-meta">
      <div class="track-title">${escapeHtml(track.trackName)}</div>
      <div class="track-sub">${escapeHtml(track.artistName)} &middot; ${escapeHtml(track.primaryGenreName || "")}</div>
    </div>
  `;
  li.addEventListener("click", () => showDetail(track));
  return li;
}

async function showDetail(track) {
  hideAll();
  setStatus(`Loading "${track.trackName}"...`);

  els.detailTitle.textContent = track.trackName;
  els.detailArtist.textContent = track.artistName;
  els.detailGenre.textContent = track.primaryGenreName || "";
  els.detailArt.src = (track.artworkUrl100 || "").replace("100x100", "300x300");
  els.detailArt.alt = track.trackName;
  els.detailAudio.src = track.previewUrl || "";
  els.detailVideoLink.href = youtubeSearchUrl(`${track.artistName} ${track.trackName} official video`);
  els.detailStoreLink.href = track.trackViewUrl || "#";

  const [bio, similar] = await Promise.all([
    getWikipediaSummary(track.artistName),
    getSimilarSongs(track),
  ]);

  els.detailBio.textContent = bio || "";
  els.similarList.innerHTML = "";
  similar.forEach((t) => els.similarList.appendChild(trackItem(t)));

  hideAll();
  els.detailView.hidden = false;
}

async function getSimilarSongs(track) {
  const genre = track.primaryGenreName;
  if (!genre) return [];

  // Proxy for "similar": other songs in the same genre, minus this exact
  // track and duplicates, plus a couple more from the same artist.
  const [byGenre, byArtist] = await Promise.all([
    fetchJSON(`${ITUNES_SEARCH}?term=${encodeURIComponent(genre)}&entity=song&limit=25`),
    fetchJSON(`${ITUNES_SEARCH}?term=${encodeURIComponent(track.artistName)}&entity=song&limit=10`),
  ]);

  const seen = new Set([track.trackId]);
  const combined = [];

  for (const t of [...byArtist.results, ...byGenre.results]) {
    if (seen.has(t.trackId)) continue;
    seen.add(t.trackId);
    combined.push(t);
    if (combined.length >= 12) break;
  }
  return combined;
}

async function getWikipediaSummary(name) {
  try {
    const data = await fetchJSON(WIKI_SUMMARY + encodeURIComponent(name));
    if (data.type === "disambiguation") return "";
    return data.extract || "";
  } catch {
    return "";
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
