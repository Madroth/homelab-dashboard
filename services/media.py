import json
import os
import sqlite3
import sys

if '/home/linuxbox/projects/media-curator' not in sys.path:
    sys.path.append('/home/linuxbox/projects/media-curator')

MEDIA_DB = os.path.expanduser('~/projects/media-curator/queue.db')


def _get_conn():
    from database import get_conn
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    return conn


def get_queue(search: str = '', media_type: str = '', status: str = '') -> list[dict]:
    if not os.path.exists(MEDIA_DB):
        return []

    conn = _get_conn()
    c = conn.cursor()

    query = 'SELECT * FROM media_queue WHERE 1=1'
    params = []
    if search:
        query += ' AND (proposed_title LIKE ? OR original_filename LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    if media_type:
        query += ' AND media_type = ?'
        params.append(media_type)
    if status:
        query += ' AND status = ?'
        params.append(status)

    query += ' ORDER BY created_at DESC LIMIT 100'
    c.execute(query, params)

    rows = []
    for r in c.fetchall():
        d = dict(r)
        d['metadata'] = json.loads(d['metadata_json']) if d['metadata_json'] else {}
        rows.append(d)
    conn.close()
    return rows


def approve(item_id: str) -> tuple[bool, str]:
    from library import approve_item
    return approve_item(item_id)


def reject(item_id: str) -> tuple[bool, str]:
    from library import reject_item
    return reject_item(item_id)


def reclassify(item_id: str, new_type: str) -> tuple[bool, str | None]:
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM media_queue WHERE id=?', (item_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return False, 'Not found'

    original_path = row['original_path']
    old_proposed = row['proposed_path']

    # If the file has already been moved to the library, use the library file as the source
    if row['status'] == 'approved' and old_proposed and os.path.exists(old_proposed):
        original_path = old_proposed
        c.execute('UPDATE media_queue SET original_path=? WHERE id=?', (original_path, item_id))

    try:
        from curator_daemon import identify_media
    except ImportError:
        conn.close()
        return False, 'Backend daemon not found.'

    is_group = os.path.isdir(original_path)
    filename = os.path.basename(original_path)
    ext = '' if is_group else os.path.splitext(filename)[1].lower()

    res = identify_media(filename, original_path, ext, is_group=is_group, force_media_type=new_type)
    if not res:
        conn.close()
        return False, 'Failed to reclassify via backend daemon.'

    media_type, proposed_title, proposed_path, metadata, _ = res
    metadata['sort_logic'] = f'User manually reclassified as {new_type}.'
    meta_str = json.dumps(metadata)

    c.execute('''UPDATE media_queue SET media_type=?, proposed_title=?, proposed_path=?,
                 metadata_json=?, status="pending" WHERE id=?''',
              (new_type, proposed_title, proposed_path, meta_str, item_id))
    conn.commit()
    conn.close()

    success, msg = approve(item_id)
    if not success:
        return False, msg
    return True, None


def edit(item_id: str, proposed_title: str | None = None) -> tuple[bool, str | None]:
    conn = _get_conn()
    c = conn.cursor()

    if proposed_title is not None:
        c.execute('SELECT * FROM media_queue WHERE id=?', (item_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False, 'Item not found'
        if row['status'] == 'approved':
            conn.close()
            return False, 'Cannot edit title of an approved item. Use Reclassify instead.'
        c.execute('UPDATE media_queue SET proposed_title=? WHERE id=?', (proposed_title, item_id))

    c.execute('UPDATE media_queue SET needs_intervention=0 WHERE id=?', (item_id,))
    conn.commit()
    conn.close()
    return True, None


def bulk_action(action: str, item_ids: list[str]) -> list[dict]:
    results = []
    if action == 'approve':
        for iid in item_ids:
            success, msg = approve(iid)
            results.append({'id': iid, 'success': success, 'msg': msg})
    elif action == 'reject':
        for iid in item_ids:
            success, msg = reject(iid)
            results.append({'id': iid, 'success': success, 'msg': msg})
    return results


def undo(item_id: str) -> tuple[bool, str | None]:
    """Moves an approved item back to the drop zone and re-queues it.

    This spans two storage systems -- the filesystem and queue.db -- so the order of
    operations is the whole problem. The move used to happen first and the UPDATE was
    unguarded: media-curator dropped its UNIQUE index on original_path for a PARTIAL
    unique index over (original_path, file_hash) scoped to pending rows, and writing
    original_path while flipping status back to 'pending' is exactly what that index
    now judges. An IntegrityError there left the file already moved while the database
    still called it approved and living at proposed_path -- permanently out of sync,
    and reachable from a button.

    So: if the database write fails, the file goes back where it came from before the
    error is reported. The pair either both change or neither does.
    """
    import shutil
    conn = _get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM media_queue WHERE id=?', (item_id,))
        row = c.fetchone()
        if not row or row['status'] != 'approved':
            return False, 'Item not found or not approved'

        proposed_path = row['proposed_path']
        original_filename = row['original_filename']
        from curator_daemon import DROP_ZONE
        dest_path = os.path.join(DROP_ZONE, original_filename)

        moved = False
        if os.path.exists(proposed_path):
            if os.path.exists(dest_path):
                return False, f'Destination {original_filename} already exists in drop zone.'
            try:
                shutil.move(proposed_path, dest_path)
            except Exception as e:
                return False, f'Move failed: {e}'
            moved = True

        try:
            c.execute('UPDATE media_queue SET status="pending", needs_intervention=1, '
                       'original_path=? WHERE id=?', (dest_path, item_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            if not moved:
                return False, f'Undo failed: {e}'
            try:
                shutil.move(dest_path, proposed_path)
            except Exception as put_back:
                # Both halves failed. Say so loudly and name both paths -- a silent
                # "failed" here would leave a file stranded with nothing pointing at it.
                return False, (f'Undo failed ({e}), AND the file could not be moved back '
                               f'({put_back}). It is at {dest_path} but the database still '
                               f'says {proposed_path} -- needs manual repair.')
            return False, f'Undo failed, file left where it was: {e}'
        return True, None
    finally:
        conn.close()


def upload(filename: str, content: bytes) -> tuple[bool, str]:
    from curator_daemon import DROP_ZONE, is_contained
    from werkzeug.utils import secure_filename
    os.makedirs(DROP_ZONE, exist_ok=True)
    safe_name = secure_filename(filename)
    if not safe_name:
        return False, 'Invalid filename'
    file_path = os.path.join(DROP_ZONE, safe_name)
    if not is_contained(file_path, DROP_ZONE):
        return False, 'Path traversal blocked'
    with open(file_path, 'wb') as f:
        f.write(content)
    return True, safe_name


def get_cover_path(item_id: str) -> str | None:
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM media_queue WHERE id=?', (item_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None

    search_path = row['proposed_path'] if row['status'] == 'approved' else row['original_path']
    if not search_path or not os.path.exists(search_path):
        return None

    src_dir = os.path.dirname(search_path)
    for name in ('cover.jpg', 'cover.png', 'folder.jpg', 'poster.jpg'):
        p = os.path.join(src_dir, name)
        if os.path.exists(p):
            return p
    return None
