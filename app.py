import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename

from converters import convert_file_to_pdf, UnsupportedFileType

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMPLATE_STORAGE_DIR = BASE_DIR / "stored_templates"
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "storage.json"

for directory in (UPLOAD_DIR, OUTPUT_DIR, TEMPLATE_STORAGE_DIR, DATA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)


def load_storage() -> Dict[str, List[Dict[str, Any]]]:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
                return {
                    "history": data.get("history", []),
                    "templates": data.get("templates", []),
                }
        except json.JSONDecodeError:
            pass
    return {"history": [], "templates": []}


def save_storage(data: Dict[str, List[Dict[str, Any]]]) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def find_history_entry(data: Dict[str, List[Dict[str, Any]]], history_id: str) -> Dict[str, Any]:
    for entry in data["history"]:
        if entry["id"] == history_id:
            return entry
    return {}


def find_template_entry(data: Dict[str, List[Dict[str, Any]]], template_id: str) -> Dict[str, Any]:
    for entry in data["templates"]:
        if entry["id"] == template_id:
            return entry
    return {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "请选择一个文件"}), 400

    filename = secure_filename(file.filename)
    history_id = str(uuid.uuid4())
    stored_name = f"{history_id}_{filename}"
    save_path = UPLOAD_DIR / stored_name
    file.save(save_path)

    storage = load_storage()
    entry = {
        "id": history_id,
        "filename": filename,
        "stored_name": stored_name,
        "original_path": str(save_path.relative_to(BASE_DIR)),
        "status": "uploaded",
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "pdf_path": None,
        "converted_at": None,
    }
    storage["history"].append(entry)
    save_storage(storage)

    return jsonify(_decorate_history_entry(entry))


@app.route("/api/convert", methods=["POST"])
def convert_history_item():
    payload = request.get_json(force=True, silent=True)
    if not payload or "history_id" not in payload:
        return jsonify({"error": "缺少history_id"}), 400

    history_id = payload["history_id"]
    storage = load_storage()
    entry = find_history_entry(storage, history_id)
    if not entry:
        return jsonify({"error": "未找到对应的历史记录"}), 404

    if entry.get("status") == "converted" and entry.get("pdf_path"):
        return jsonify(_decorate_history_entry(entry))

    source_path = BASE_DIR / entry["original_path"]
    if not source_path.exists():
        return jsonify({"error": "原始文件不存在，无法转换"}), 404

    original_stem = Path(entry["filename"]).stem
    pdf_filename = f"{original_stem}_{history_id}.pdf"
    output_path = OUTPUT_DIR / pdf_filename

    try:
        convert_file_to_pdf(source_path, output_path)
    except UnsupportedFileType as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": f"转换失败: {exc}"}), 500

    entry["status"] = "converted"
    entry["pdf_path"] = str(output_path.relative_to(BASE_DIR))
    entry["converted_at"] = datetime.utcnow().isoformat() + "Z"
    save_storage(storage)

    return jsonify(_decorate_history_entry(entry))


@app.route("/api/history", methods=["GET"])
def list_history():
    storage = load_storage()
    history = [_decorate_history_entry(item) for item in storage["history"]]
    history.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
    return jsonify(history)


@app.route("/api/history/<history_id>", methods=["DELETE"])
def delete_history(history_id: str):
    storage = load_storage()
    entry = find_history_entry(storage, history_id)
    if not entry:
        return jsonify({"error": "记录不存在"}), 404

    storage["history"] = [item for item in storage["history"] if item["id"] != history_id]

    original_path = BASE_DIR / entry["original_path"]
    if original_path.exists():
        original_path.unlink()

    pdf_path = entry.get("pdf_path")
    if pdf_path:
        pdf_full_path = BASE_DIR / pdf_path
        if pdf_full_path.exists():
            pdf_full_path.unlink()

    related_templates = [tpl for tpl in storage["templates"] if tpl.get("source_history_id") == history_id]
    for template in related_templates:
        _remove_template_files(template)
    storage["templates"] = [tpl for tpl in storage["templates"] if tpl.get("source_history_id") != history_id]

    save_storage(storage)
    return jsonify({"message": "删除成功"})


@app.route("/download/<history_id>", methods=["GET"])
def download_pdf(history_id: str):
    storage = load_storage()
    entry = find_history_entry(storage, history_id)
    if not entry or entry.get("status") != "converted" or not entry.get("pdf_path"):
        return jsonify({"error": "文件不可下载"}), 404

    pdf_path = BASE_DIR / entry["pdf_path"]
    if not pdf_path.exists():
        return jsonify({"error": "文件不存在"}), 404

    return send_from_directory(pdf_path.parent, pdf_path.name, as_attachment=True)


@app.route("/api/templates", methods=["GET"])
def list_templates():
    storage = load_storage()
    templates = [
        {
            **template,
            "download_url": f"/template-download/{template['id']}"
            if template.get("stored_path")
            else None,
        }
        for template in storage["templates"]
    ]
    templates.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jsonify(templates)


@app.route("/api/templates", methods=["POST"])
def create_template():
    payload = request.get_json(force=True, silent=True)
    if not payload or "history_id" not in payload:
        return jsonify({"error": "缺少history_id"}), 400

    history_id = payload["history_id"]
    name = payload.get("name")

    storage = load_storage()
    entry = find_history_entry(storage, history_id)
    if not entry:
        return jsonify({"error": "历史记录不存在"}), 404

    source_path = BASE_DIR / entry["original_path"]
    if not source_path.exists():
        return jsonify({"error": "源文件缺失，无法创建模板"}), 404

    template_id = str(uuid.uuid4())
    template_filename = f"{template_id}_{Path(entry['filename']).name}"
    stored_path = TEMPLATE_STORAGE_DIR / template_filename
    shutil.copy2(source_path, stored_path)

    template_entry = {
        "id": template_id,
        "name": name or entry["filename"],
        "filename": entry["filename"],
        "stored_path": str(stored_path.relative_to(BASE_DIR)),
        "source_history_id": history_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    storage["templates"].append(template_entry)
    save_storage(storage)

    template_entry["download_url"] = f"/template-download/{template_id}"
    return jsonify(template_entry)


@app.route("/api/templates/<template_id>", methods=["DELETE"])
def delete_template(template_id: str):
    storage = load_storage()
    template = find_template_entry(storage, template_id)
    if not template:
        return jsonify({"error": "模板不存在"}), 404

    _remove_template_files(template)
    storage["templates"] = [tpl for tpl in storage["templates"] if tpl["id"] != template_id]
    save_storage(storage)

    return jsonify({"message": "模板已删除"})


@app.route("/api/templates/<template_id>/use", methods=["POST"])
def use_template(template_id: str):
    payload = request.get_json(force=True, silent=True) or {}
    new_name = payload.get("name")

    storage = load_storage()
    template = find_template_entry(storage, template_id)
    if not template:
        return jsonify({"error": "模板不存在"}), 404

    template_path = BASE_DIR / template["stored_path"]
    if not template_path.exists():
        return jsonify({"error": "模板文件缺失"}), 404

    history_id = str(uuid.uuid4())
    filename = new_name or template["filename"]
    stored_name = f"{history_id}_{secure_filename(filename)}"
    destination = UPLOAD_DIR / stored_name
    shutil.copy2(template_path, destination)

    history_entry = {
        "id": history_id,
        "filename": filename,
        "stored_name": stored_name,
        "original_path": str(destination.relative_to(BASE_DIR)),
        "status": "uploaded",
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "pdf_path": None,
        "converted_at": None,
        "template_origin": template_id,
    }

    storage["history"].append(history_entry)
    save_storage(storage)

    return jsonify(_decorate_history_entry(history_entry))


@app.route("/template-download/<template_id>", methods=["GET"])
def download_template(template_id: str):
    storage = load_storage()
    template = find_template_entry(storage, template_id)
    if not template or not template.get("stored_path"):
        return jsonify({"error": "模板不可下载"}), 404

    template_path = BASE_DIR / template["stored_path"]
    if not template_path.exists():
        return jsonify({"error": "模板文件不存在"}), 404

    return send_from_directory(template_path.parent, template_path.name, as_attachment=True)


def _decorate_history_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    decorated = dict(entry)
    if entry.get("pdf_path"):
        decorated["download_url"] = f"/download/{entry['id']}"
    else:
        decorated["download_url"] = None
    return decorated


def _remove_template_files(template: Dict[str, Any]) -> None:
    stored_path = template.get("stored_path")
    if stored_path:
        template_file = BASE_DIR / stored_path
        if template_file.exists():
            template_file.unlink()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
