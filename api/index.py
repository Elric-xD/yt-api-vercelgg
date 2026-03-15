import os
import tempfile
import requests
from http.cookiejar import MozillaCookieJar
from flask import Flask, request, jsonify
from flask_caching import Cache
from youtube_search import YoutubeSearch
import yt_dlp

# -------------------------
# Vercel Compatibility Setup
# -------------------------
temp_dir = tempfile.gettempdir()
# Ensure cookies_file points to a place yt-dlp can actually read if it exists
cookie_file = os.path.join(os.getcwd(), 'cookies.txt') 
if not os.path.exists(cookie_file):
    cookie_file = None

app = Flask(__name__)

# Cache Configuration (In-Memory)
cache = Cache(app, config={
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': 3600 # 1 hour default
})

# -------------------------
# Helper Functions
# -------------------------
def to_iso_duration(duration_str: str) -> str:
    parts = str(duration_str).split(':') if duration_str else []
    iso = 'PT'
    try:
        if len(parts) == 3:
            h, m, s = parts
            iso += f"{int(h)}H{int(m)}M{int(s)}S"
        elif len(parts) == 2:
            m, s = parts
            iso += f"{int(m)}M{int(s)}S"
        elif len(parts) == 1 and parts[0].isdigit():
            iso += f"{int(parts[0])}S"
        else: iso += '0S'
    except: iso += '0S'
    return iso

# CRITICAL: Optimized yt-dlp options for Vercel
def get_ydl_opts(is_meta=False):
    return {
        'quiet': True,
        'skip_download': True,
        'cachedir': False,
        'cookiefile': cookie_file,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'no_warnings': True,
        # --- THE SPEED TRICK ---
        'extract_flat': True if is_meta else False,
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
        'format': 'ba/wa', # Extremely loose format selection
        'extractor_args': {'youtube': {'skip': ['dash', 'hls']}}, # Skips heavy manifest parsing
        'socket_timeout': 5,
    }



def extract_info(url=None, search_query=None, is_meta=False):
    ydl_opts = get_ydl_opts(is_meta)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            target = f"ytsearch1:{search_query}" if search_query else url
            info = ydl.extract_info(target, download=False)
            if 'entries' in info: # Handle search results
                info = info['entries'][0]
            return info, None
        except Exception as e:
            return None, str(e)

def build_formats_list(info):
    fmts = []
    for f in info.get('formats', []):
        if not f.get('url'): continue
        has_v = f.get('vcodec') != 'none'
        has_a = f.get('acodec') != 'none'
        kind = 'progressive' if has_v and has_a else 'video-only' if has_v else 'audio-only' if has_a else None
        if not kind: continue
        fmts.append({
            'format_id': f.get('format_id'),
            'ext': f.get('ext'),
            'kind': kind,
            'url': f.get('url'),
            'abr': f.get('abr', 0),
            'height': f.get('height', 0)
        })
    return fmts

# -------------------------
# Routes
# -------------------------

@app.route('/')
def home():
    return jsonify({'message': '✅ YouTube API is alive and optimized for Vercel'})

@app.route('/api/fast-meta')
@cache.cached(timeout=3600, query_string=True)
def api_fast_meta():
    q = request.args.get('search', '').strip()
    u = request.args.get('url', '').strip()
    try:
        if q:
            results = YoutubeSearch(q, max_results=1).to_dict()
            if results:
                v = results[0]
                return jsonify({
                    'title': v.get('title'),
                    'link': f"https://www.youtube.com/watch?v={v['id']}",
                    'duration': to_iso_duration(v.get('duration')),
                    'thumbnail': v.get('thumbnails', [None])[0]
                })
        elif u:
            info, err = extract_info(url=u, is_meta=True)
            if err: return jsonify({'error': err}), 500
            return jsonify({
                'title': info.get('title'),
                'link': info.get('webpage_url'),
                'duration': to_iso_duration(info.get('duration')),
                'thumbnail': info.get('thumbnail')
            })
        return jsonify({'error': 'Missing params'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/audio')
@cache.cached(timeout=3600, query_string=True)
def api_audio():
    u = request.args.get('url') or request.args.get('search')
    if not u: return jsonify({'error': 'Missing url/search'}), 400
    
    # Check if input is a search term or URL
    is_search = not (u.startswith('http://') or u.startswith('https://'))
    info, err = extract_info(search_query=u if is_search else None, url=None if is_search else u)
    
    if err: return jsonify({'error': err}), 500
    
    fmts = build_formats_list(info)
    afmts = [f for f in fmts if f['kind'] in ('audio-only', 'progressive')]
    return jsonify({
        'title': info.get('title'),
        'audio_formats': afmts
    })

@app.route('/api/all')
def api_all():
    u = request.args.get('url') or request.args.get('search')
    if not u: return jsonify({'error': 'Missing param'}), 400
    is_search = not (u.startswith('http://') or u.startswith('https://'))
    info, err = extract_info(search_query=u if is_search else None, url=None if is_search else u)
    if err: return jsonify({'error': err}), 500
    return jsonify({
        'title': info.get('title'),
        'duration': info.get('duration'),
        'formats': build_formats_list(info)
    })

@app.route('/api/playlist')
def api_playlist():
    u = request.args.get('url')
    if not u: return jsonify({'error': 'Missing url'}), 400
    info, err = extract_info(url=u, is_meta=True)
    if err: return jsonify({'error': err}), 500
    
    videos = [{
        'title': e.get('title'),
        'url': f"https://www.youtube.com/watch?v={e.get('id')}",
        'duration': e.get('duration')
    } for e in info.get('entries', [])]
    
    return jsonify({'title': info.get('title'), 'videos': videos})

if __name__ == '__main__':
    app.run(debug=True)
        

