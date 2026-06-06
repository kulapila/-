"""Launch a local web viewer for the survey data."""

from __future__ import annotations

import json
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .utils import load_json, load_jsonl

HOST = "127.0.0.1"
PORT = 8080

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Survey Pipeline — Code Generation</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;color:#333}
header{background:#1a1a2e;color:#fff;padding:16px 24px}
header h1{font-size:20px}
header span{font-size:13px;opacity:.7}
nav{background:#16213e;display:flex;gap:0}
nav button{background:none;border:none;color:#a0a0c0;padding:12px 20px;cursor:pointer;font-size:14px;transition:.2s}
nav button:hover,nav button.active{color:#fff;background:#0f3460}
main{max-width:1300px;margin:24px auto;padding:0 20px}
.tab{display:none}
.tab.active{display:block}
.card{background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:4px solid #0f3460}
.card h2{font-size:15px;margin-bottom:6px;color:#1a1a2e}
.card .meta{font-size:12px;color:#888;margin-bottom:8px}
.card .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px}
.card .field{font-size:13px}
.card .field strong{color:#555;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.tag-blue{background:#e3f2fd;color:#1565c0}
.tag-green{background:#e8f5e9;color:#2e7d32}
.tag-orange{background:#fff3e0;color:#e65100}
.tag-purple{background:#f3e5f5;color:#7b1fa2}
.card.clickable{cursor:pointer;transition:.2s}
.card.clickable:hover{border-left-color:#e94560;transform:translateX(4px)}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
th{background:#1a1a2e;color:#fff;padding:10px 12px;font-size:12px;text-align:left}
td{padding:10px 12px;font-size:13px;border-bottom:1px solid #eee}
tr:hover{background:#f8f9fa}
#digest-content,#report-content{background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.08);line-height:1.7}
#digest-content h1,#report-content h1{font-size:22px;margin-bottom:12px}
#digest-content h2,#report-content h2{font-size:17px;margin:20px 0 8px;border-bottom:1px solid #eee;padding-bottom:6px}
#digest-content h3,#report-content h3{font-size:14px;margin:14px 0 6px}
#digest-content ul,#report-content ul,#digest-content ol,#report-content ol{margin:6px 0 6px 20px}
#digest-content li,#report-content li{margin:4px 0}
#digest-content pre,#report-content pre{background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto;font-size:12px}
#digest-content code,#report-content code{background:#f4f4f4;padding:1px 4px;border-radius:3px;font-size:12px}
.search-bar{margin-bottom:16px;display:flex;gap:8px}
.search-bar input{flex:1;padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.stat-card{background:#fff;border-radius:8px;padding:20px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.stat-card .number{font-size:32px;font-weight:700;color:#0f3460}
.stat-card .label{font-size:12px;color:#888;margin-top:4px}
.empty{text-align:center;padding:40px;color:#999}
.loading{text-align:center;padding:20px;color:#888;font-size:14px}
@media(max-width:768px){.stats{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header><h1>Survey Pipeline: Code Generation<span>  |  Visual Dashboard</span></h1></header>
<nav>
<button class="active" onclick="switchTab('dashboard')">Dashboard</button>
<button onclick="switchTab('papers')">Paper Cards</button>
</nav>
<main>
<div id="tab-dashboard" class="tab active">
<div class="stats">
<div class="stat-card"><div class="number" id="stat-papers">-</div><div class="label">Papers Fetched</div></div>
<div class="stat-card"><div class="number" id="stat-cards">-</div><div class="label">Cards Generated</div></div>
<div class="stat-card"><div class="number" id="stat-categories">-</div><div class="label">Categories</div></div>
<div class="stat-card"><div class="number" id="stat-weeks">-</div><div class="label">Weekly Digests</div></div>
</div>
<div id="dashboard-categories"></div>
</div>
<div id="tab-papers" class="tab">
<div class="search-bar">
<input type="text" id="paper-search" placeholder="Search by title, method, category..." oninput="filterPapers()"><button onclick="document.getElementById('paper-search').value='';renderPapers(allCards)" style="padding:8px 16px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">Show All</button>
</div>
<div id="papers-list"><div class="loading">Loading...</div></div>
</div>
</main>
<script>
let allCards=[],allPapers=[];
async function loadData(){
try{
const [cardsRes,papersRes]=await Promise.all([
fetch('/api/cards'),fetch('/api/papers')
]);
allCards=await cardsRes.json();
allPapers=await papersRes.json();
renderDashboard();
renderPapers(allCards);
}catch(e){document.querySelectorAll('.loading').forEach(el=>el.textContent='Error loading data: '+e.message)}
}
function renderDashboard(){
document.getElementById('stat-papers').textContent=allPapers.length;
document.getElementById('stat-cards').textContent=allCards.length;
const cats=new Set(allCards.map(c=>c.best_fit_category).filter(Boolean));
document.getElementById('stat-categories').textContent=cats.size;
document.getElementById('stat-weeks').textContent='1';
const catCount={};
allCards.forEach(c=>{const cat=c.best_fit_category||'Unknown';catCount[cat]=(catCount[cat]||0)+1});
document.getElementById('dashboard-categories').innerHTML=
'<h3 style="margin-bottom:12px">Category Distribution (click to filter)</h3>'+
Object.entries(catCount).map(([k,v])=>`<div class="card clickable" onclick="filterByCategory('${esc(k)}')"><h2>${k}</h2><span class="meta">${v} paper(s) →</span></div>`).join('');
}
function renderPapers(cards){
const container=document.getElementById('papers-list');
if(!cards.length){container.innerHTML='<div class="empty">No paper cards found.</div>';return}
container.innerHTML=cards.map(c=>`
<div class="card">
<h2><a href="https://arxiv.org/abs/${esc(c.arxiv_id)}" target="_blank" style="color:#1a1a2e;text-decoration:none">${esc(c.title)}</a></h2>
<div class="meta"><a href="https://arxiv.org/abs/${esc(c.arxiv_id)}" target="_blank" style="color:#888;text-decoration:none">${esc(c.arxiv_id)}</a> &middot; ${esc(c.best_fit_category||'')} &middot; Confidence: ${esc(c.confidence_level)}</div>
<div class="grid">
<div class="field"><strong>Problem</strong><br>${esc(c.problem)}</div>
<div class="field"><strong>Key Idea</strong><br>${esc(c.key_idea)}</div>
<div class="field"><strong>Method</strong><br>${esc(c.method)}</div>
<div class="field"><strong>Dataset</strong><br>${esc(c.dataset_or_scenario)}</div>
<div class="field"><strong>Metrics</strong><br>${esc(c.metrics)}</div>
<div class="field"><strong>Results</strong><br>${esc(c.results_summary)}</div>
<div class="field"><strong>Innovation Type</strong><br><span class="tag tag-blue">${esc(c.innovation_type)}</span></div>
<div class="field"><strong>Limitations</strong><br>${esc(c.limitations)}</div>
</div>
</div>`).join('');
}
function filterByCategory(cat){
switchTab('papers');
document.getElementById('paper-search').value=cat;
const filtered=allCards.filter(c=>(c.best_fit_category||'')===cat);
renderPapers(filtered);
}
function filterPapers(){
const q=document.getElementById('paper-search').value.toLowerCase();
if(!q){renderPapers(allCards);return}
const filtered=allCards.filter(c=>
c.title.toLowerCase().includes(q)||c.method.toLowerCase().includes(q)||
(c.best_fit_category||'').toLowerCase().includes(q)||c.problem.toLowerCase().includes(q)
);
renderPapers(filtered);
}
function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function switchTab(name){
document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
document.getElementById('tab-'+name).classList.add('active');
document.querySelector(`nav button[onclick="switchTab('${name}')"]`).classList.add('active');
}
loadData();
</script>
</body>
</html>"""


class ViewerHandler(BaseHTTPRequestHandler):
    data_dir: Path = Path("data")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_html(HTML_PAGE)
        elif path == "/api/cards":
            self._serve_json(self._load_cards())
        elif path == "/api/papers":
            self._serve_json(load_json(str(self.data_dir / "papers_raw.json")) or [])
        elif path == "/api/comparison":
            self._serve_json(self._load_comparison())
        elif path == "/api/digest":
            self._serve_text(self._load_latest_digest())
        elif path == "/api/report":
            self._serve_text(self._load_report())
        else:
            self.send_error(404)

    def _serve_html(self, content: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _serve_text(self, text: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def _load_cards(self):
        return [json.loads(line) for line in (self.data_dir / "paper_cards.jsonl").read_text("utf-8").strip().split("\n") if line.strip()] if (self.data_dir / "paper_cards.jsonl").exists() else []

    def _load_comparison(self):
        import csv
        path = self.data_dir / "comparison_table.csv"
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def _load_latest_digest(self) -> str:
        weekly = self.data_dir / "weekly"
        if not weekly.exists():
            return ""
        files = sorted(weekly.glob("digest_*.md"), reverse=True)
        return files[0].read_text("utf-8") if files else ""

    def _load_report(self) -> str:
        path = Path("output") / "final_report.md"
        return path.read_text("utf-8") if path.exists() else ""

    def log_message(self, format, *args):
        print(f"[viewer] {args[0]}")


def run_viewer(config=None):
    """Start the web viewer and open browser."""
    # Set data dir relative to project root
    from pathlib import Path as P
    ViewerHandler.data_dir = P("data")

    server = HTTPServer((HOST, PORT), ViewerHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"\n  Survey Viewer running at: {url}\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_viewer()
