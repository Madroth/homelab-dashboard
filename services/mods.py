import os
import shutil
import sys
import threading

from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/work/claude-code/modpipeline/.env'))

os.environ['MODPIPELINE_DATA_ROOT'] = os.path.expanduser('~/work/claude-code/modpipeline/data')
sys.path.insert(0, os.path.expanduser('~/work/claude-code/modpipeline'))

from common.paths import APPROVED, DEPLOYED, REVIEW, STAGING  # noqa: E402
from common.sidecar import read_json, write_reason  # noqa: E402
import registry as mod_registry  # noqa: E402
from deploy import pipeline as deploy_pipeline  # noqa: E402
from deploy.pipeline import DeployError  # noqa: E402

_deploy_lock = threading.Lock()


MOD_REGISTRY_FILE = os.path.expanduser('~/work/claude-code/modpipeline/data/registry.json')


def get_mods() -> dict:
    import json
    if not os.path.exists(MOD_REGISTRY_FILE):
        return {}
    with open(MOD_REGISTRY_FILE, 'r') as f:
        data = json.load(f)
    mods = data.get('mods', {})

    # Deployed submission dirs retain metadata.json (version) and
    # submission.json (submitted_at) even after deploy; registry.json
    # itself doesn't track version, so enrich by matching on sha256.
    deployed_by_hash = {}
    if DEPLOYED.exists():
        for d in DEPLOYED.iterdir():
            sub_path = d / "submission.json"
            meta_path = d / "metadata.json"
            if not sub_path.exists():
                continue
            try:
                sub_data = read_json(sub_path)
            except Exception:
                continue
            version = None
            if meta_path.exists():
                try:
                    version = read_json(meta_path).get('version')
                except Exception:
                    pass
            deployed_by_hash[sub_data.get('sha256')] = {
                'version': version,
                'submitted_at': sub_data.get('arrived_at'),
            }

    for mod in mods.values():
        info = deployed_by_hash.get(mod.get('current_hash'))
        if info:
            mod['version'] = info['version']
            mod['submitted_at'] = info['submitted_at']

    return mods


def get_staging() -> list[dict]:
    submissions = []
    if STAGING.exists():
        for d in sorted(STAGING.iterdir()):
            meta_path = d / "metadata.json"
            sub_path = d / "submission.json"
            if meta_path.exists() and sub_path.exists():
                submissions.append({
                    "id": d.name,
                    "meta": read_json(meta_path),
                    "sub": read_json(sub_path),
                })
    return submissions


def approve_mod(sid: str, decided_by: str = "parent") -> dict:
    d = STAGING / sid
    if not d.exists():
        return {"error": "Not found"}

    meta = read_json(d / "metadata.json")
    sub = read_json(d / "submission.json")

    if not _deploy_lock.acquire(blocking=False):
        return {"error": "Deploy in progress"}

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
        return {"success": True, "message": f"{meta['name']} deployed."}
    except DeployError as exc:
        mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                        sub["submitted_by"], "deploy_failed_rolled_back", decided_by=decided_by)
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                        sub["submitted_by"], "deploy_failed_error", decided_by=decided_by)
        return {"success": False, "error": f"Unexpected error: {exc}"}
    finally:
        _deploy_lock.release()


def reject_mod(sid: str, reason: str = "rejected via dashboard", decided_by: str = "parent") -> dict:
    d = STAGING / sid
    if not d.exists():
        return {"error": "Not found"}

    meta = read_json(d / "metadata.json")
    sub = read_json(d / "submission.json")

    write_reason(d, "rejected_by_parent", reason)
    REVIEW.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(REVIEW / d.name))
    mod_registry.record_submission(meta["mod_id"], sub["sha256"], sub["original_filename"],
                                    sub["submitted_by"], "rejected", decided_by=decided_by)
    return {"success": True}
