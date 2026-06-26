
import requests, time

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

tests = {
    "Amazon/IMDb":  "https://m.media-amazon.com/images/M/MV5BMTMxNTMwODM0NF5BMl5BanBnXkFtZTcwODAyMTk2Mw@@._V1_SX300.jpg",
    "MAL CDN":      "https://cdn.myanimelist.net/images/anime/9/9453.jpg",
    "TMDB CDN":     "https://image.tmdb.org/t/p/w500/q6y0Go1tsGEsmtFryDOJo3dEmqu.jpg",
    "Fanart.tv":    "https://fanart.tv/fanart/movies/155/movieposter/the-dark-knight-4f9ba1f8dfa55.jpg",
    "Imgur":        "https://i.imgur.com/NsWKMqr.jpg",
}

for name, url in tests.items():
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"{"OK" if r.status_code==200 else "FAIL"} {r.status_code} ({len(r.content)}b) — {name}")
    except Exception as e:
        print(f"ERR — {name}: {e}")
    time.sleep(0.3)
