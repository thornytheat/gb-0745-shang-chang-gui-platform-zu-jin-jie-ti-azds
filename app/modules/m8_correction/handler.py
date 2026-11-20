from app.errors import InputError
from app.modules.m8_correction.service import revise_once
from app.web import find_run
from flask import Blueprint, abort, current_app, jsonify, request

routes = Blueprint("correction", __name__)


def revisions():
    return current_app.extensions["rent-revisions"]


@routes.post("/api/corrections")
def create_revision():
    payload = request.get_json(silent=True)
    if not hasattr(payload, "get"):
        raise InputError("BAD_REVISION", "请求须为 JSON 对象")
    revision, reused = revise_once(
        current_app.extensions["rent-runs"], revisions(), payload
    )
    key = revision["更正清单"]["修订批次"]
    return (
        jsonify(
            id=key,
            reused=reused,
            location=f"/work/correction?run={revision['更正清单']['源批次']}&revision={key}",
            cross_check=revision["更正清单"]["原账复核"],
            totals=revision["更正勾稽"],
        ),
        200 if reused else 201,
    )


@routes.get("/api/corrections/<run_id>")
def list_revisions(run_id):
    find_run(run_id)
    return jsonify(revisions().history(run_id))


@routes.get("/api/correction/<revision_id>")
def inspect_revision(revision_id):
    revision = revisions().get(revision_id)
    if revision is None:
        abort(404)
    return jsonify(revision)
