import json
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

from app import app, templates
from gateway.login import login_html
from utils.kv_utils import set_value_for_key_list

with open("templates/chatgpt_context_1.json", "r", encoding="utf-8") as f:
    chatgpt_context_1 = json.load(f)
with open("templates/chatgpt_context_2.json", "r", encoding="utf-8") as f:
    chatgpt_context_2 = json.load(f)



@app.get("/", response_class=HTMLResponse)
async def chatgpt_html(request: Request):
    token = request.query_params.get("token")
    if not token:
        token = request.cookies.get("token")
    if not token:
        return await login_html(request)

    if len(token) != 45 and not token.startswith("eyJhbGciOi"):
        token = quote(token)

    user_chatgpt_context_1 = chatgpt_context_1.copy()
    user_chatgpt_context_2 = chatgpt_context_2.copy()

    set_value_for_key_list(user_chatgpt_context_1, "accessToken", token)
    if request.cookies.get("oai-locale"):
        set_value_for_key_list(user_chatgpt_context_1, "locale", request.cookies.get("oai-locale"))

    user_chatgpt_context_1 = json.dumps(user_chatgpt_context_1, separators=(',', ':'), ensure_ascii=False)
    user_chatgpt_context_2 = json.dumps(user_chatgpt_context_2, separators=(',', ':'), ensure_ascii=False)

    escaped_context_1 = user_chatgpt_context_1.replace("\\", "\\\\")
    escaped_context_2 = user_chatgpt_context_2.replace("\\", "\\\\")

    escaped_context_1 = escaped_context_1.replace('"', '\\"')
    escaped_context_2 = escaped_context_2.replace('"', '\\"')

    response = templates.TemplateResponse("chatgpt.html", {
        "request": request, 
        "react_chatgpt_context_1": escaped_context_1,
        "react_chatgpt_context_2": escaped_context_2
    })
    response.set_cookie("token", value=token, expires="Thu, 01 Jan 2099 00:00:00 GMT")
    return response
