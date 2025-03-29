import json

from fastapi import Request
from fastapi.responses import Response

from app import app
from gateway.reverseProxy import chatgpt_reverse_proxy
from utils.kv_utils import set_value_for_key_dict

with open("templates/initialize.json", "r") as f:
    initialize_json = json.load(f)


@app.post("/v1/initialize")
async def initialize(request: Request):
    initialize_response = (await chatgpt_reverse_proxy(request, f"v1/initialize"))
    if not initialize_response:
        return Response(status_code=204)
    initialize_str = initialize_response.body.decode('utf-8')
    if not initialize_str:
        return Response(status_code=204)
    initialize_json = json.loads(initialize_str)
    set_value_for_key_dict(initialize_json, "ip", "8.8.8.8")
    set_value_for_key_dict(initialize_json, "country", "US")
    return Response(content=json.dumps(initialize_json, indent=4), media_type="application/json")


@app.post("/v1/rgstr")
async def rgstr():
    return Response(status_code=202, content=json.dumps({"success": True}, indent=4), media_type="application/json")


@app.get("/ces/v1/projects/oai/settings")
async def ces_v1_projects_oai_settings():
    return Response(status_code=200, content=json.dumps({"integrations":{"Segment.io":{"apiHost":"chatgpt.com/ces/v1","apiKey":"oai"}}}, indent=4), media_type="application/json")


@app.post("/ces/v1/{path:path}")
async def ces_v1():
    return Response(status_code=202, content=json.dumps({"success": True}, indent=4), media_type="application/json")


@app.post("/ces/statsc/flush")
async def ces_v1():
    return Response(status_code=200, content=json.dumps({"success": True}, indent=4), media_type="application/json")
