import os
import glob
import re
import sys
import shutil
import threading
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder='static')
ARTICLES_DIR = os.path.expanduser('~/projects/homelab-intake/articles')
MOD_REGISTRY_FILE = os.path.expanduser('~/work/claude-code/modpipeline/data/registry.json')

# ModPipeline integration
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/work/claude-code/modpipeline/.env'))

os.environ['MODPIPELINE_DATA_ROOT'] = os.path.expanduser('~/work/claude-code/modpipeline/data')
sys.path.insert(0, os.path.expanduser('~/work/claude-code/modpipeline'))
from common.paths import STAGING, APPROVED, REVIEW, DEPLOYED
from common.sidecar import read_json, write_reason
import registry as mod_registry
from deploy import pipeline as deploy_pipeline
from deploy.pipeline import DeployError

_deploy_lock = threading.Lock()

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/articles')
def list_articles():
    if not os.path.exists(ARTICLES_DIR):
        return jsonify([])
    
    files = glob.glob(os.path.join(ARTICLES_DIR, '*.md'))
    # Sort files by name descending (which includes the timestamp)
    files.sort(reverse=True)
    
    articles = []
    for filepath in files:
        filename = os.path.basename(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Very basic extraction
            title_match = re.search(r'^#\s+(.*)', content, re.MULTILINE)
            source_match = re.search(r'\*\*Source:\*\*\s+(.*)', content)
            date_match = re.search(r'\*\*Date:\*\*\s+(.*)', content)
            
            title = title_match.group(1) if title_match else filename.replace('.md', '')
            source = source_match.group(1) if source_match else ''
            date = date_match.group(1) if date_match else ''
            
            # Create a short snippet from the local summary
            summary_match = re.search(r'## Local AI Summary.*?$(.*?)(?:##|$)', content, re.MULTILINE | re.DOTALL)
            snippet = ''
            if summary_match:
                snippet = summary_match.group(1).strip()[:150] + '...'
                
            articles.append({
                'id': filename,
                'title': title,
                'date': date,
                'source': source,
                'snippet': snippet,
                'raw_content': content.lower()
            })
            
    return jsonify(articles)

@app.route('/api/articles/<filename>')
def get_article(filename):
    filepath = os.path.join(ARTICLES_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Not found'}), 404
        
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    return jsonify({'content': content})

@app.route('/api/queue')
def get_queue():
    import json
    QUEUE_FILE = os.path.expanduser('~/projects/homelab-intake/queue.json')
    if not os.path.exists(QUEUE_FILE):
        return jsonify([])
    try:
        with open(QUEUE_FILE, 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mods')
def get_mods():
    import json
    if not os.path.exists(MOD_REGISTRY_FILE):
        return jsonify({})
    try:
        with open(MOD_REGISTRY_FILE, 'r') as f:
            data = json.load(f)
        return jsonify(data.get('mods', {}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mods/staging')
def get_staging():
    submissions = []
    if STAGING.exists():
        for d in sorted(STAGING.iterdir()):
            meta_path = d / "metadata.json"
            sub_path = d / "submission.json"
            if meta_path.exists() and sub_path.exists():
                submissions.append({
                    "id": d.name,
                    "meta": read_json(meta_path),
                    "sub": read_json(sub_path)
                })
    return jsonify(submissions)

@app.route('/api/mods/approve/<sid>', methods=['POST'])
def approve_mod(sid):
    d = STAGING / sid
    if not d.exists():
        return jsonify({"error": "Not found"}), 404

    meta = read_json(d / "metadata.json")
    sub = read_json(d / "submission.json")
    decided_by = "parent"

    if not _deploy_lock.acquire(blocking=False):
        return jsonify({"error": "Deploy in progress"}), 409

    try:
        APPROVED.mkdir(parents=True, exist_ok=True)
        dest = APPROVED / d.name
        shutil.move(str(d), str(dest))
        mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                       sub["submitted_by"], "approved_pending_deploy", decided_by=decided_by)
        deploy_pipeline.run(dest, meta, sub, decided_by=decided_by)
        DEPLOYED.mkdir(parents=True, exist_ok=True)
        final = DEPLOYED / dest.name
        shutil.move(str(dest), str(final))
        mod_registry.record_deployed(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                     sub["submitted_by"], decided_by)
        return jsonify({"success": True, "message": f"{meta['name']} deployed."})
    except DeployError as exc:
        mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                       sub["submitted_by"], "deploy_failed_rolled_back", decided_by=decided_by)
        return jsonify({"success": False, "error": str(exc)}), 500
    except Exception as exc:
        mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                       sub["submitted_by"], "deploy_failed_error", decided_by=decided_by)
        return jsonify({"success": False, "error": f"Unexpected error: {str(exc)}"}), 500
    finally:
        _deploy_lock.release()

@app.route('/api/mods/reject/<sid>', methods=['POST'])
def reject_mod(sid):
    d = STAGING / sid
    if not d.exists():
        return jsonify({"error": "Not found"}), 404

    meta = read_json(d / "metadata.json")
    sub = read_json(d / "submission.json")
    data = request.json or {}
    reason = data.get("reason", "rejected via dashboard")
    decided_by = "parent"

    write_reason(d, "rejected_by_parent", reason)
    REVIEW.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(REVIEW / d.name))
    mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                   sub["submitted_by"], "rejected", decided_by=decided_by)
    return jsonify({"success": True})

@app.route("/setup")
def setup():
    DOWNLOADS_DIR = os.path.join(os.environ['MODPIPELINE_DATA_ROOT'], "downloads")
    return send_from_directory(DOWNLOADS_DIR, "automodpack-4.0.5.jar", as_attachment=True)

@app.route("/setup-loader-core")
def setup_loader_core():
    DOWNLOADS_DIR = os.path.join(os.environ['MODPIPELINE_DATA_ROOT'], "downloads")
    return send_from_directory(DOWNLOADS_DIR, "automodpack_mod-loader-fabric-core-4.0.5.jar", as_attachment=True)

@app.route("/downloads/<filename>")
def download(filename):
    DOWNLOADS_DIR = os.path.join(os.environ['MODPIPELINE_DATA_ROOT'], "downloads")
    return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8085, debug=True)
