import json

from flask import Response


def evidence_pack(run):
    if "更正清单" in run:
        run_id = run["更正清单"]["修订批次"]
        filename = f"rent-correction-{run_id}.json"
    else:
        run_id = run["运行清单"]["批次"]
        filename = f"rent-{run_id}.json"
    return Response(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n",
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
