import json
import random
import re
import time

from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import utils.globals as globals
from app import app, templates
from gateway.reverseProxy import chatgpt_reverse_proxy
from utils.Client import Client
from utils.config import enable_gateway, proxy_url_list

if enable_gateway:
    @app.get("/", response_class=HTMLResponse)
    async def chatgpt_html(request: Request):
        token = request.query_params.get("token")
        if not token:
            token = request.cookies.get("token")
        if not token:
            return await login_html(request)

        response = templates.TemplateResponse("chatgpt.html", {"request": request, "token": token})
        response.set_cookie("token", value=token, expires="Thu, 01 Jan 2099 00:00:00 GMT")
        return response


    async def chatgpt_account_check(access_token):
        auth_info = {}
        headers = {
            'accept': '*/*',
            'accept-language': 'en',
            'authorization': 'Bearer ' + access_token,
            'content-type': 'application/json',
            'oai-language': 'en-US',
            'origin': 'https://chatgpt.com',
            'referer': 'https://chatgpt.com/',
            'sec-ch-ua': '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0',
        }
        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
        r = await client.get("https://chatgpt.com/backend-api/models?history_and_training_disabled=false",
                             headers=headers, timeout=5)
        models = r.json()
        r = await client.get("https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27", headers=headers, timeout=5)
        accounts_info = r.json()

        await client.close()

        auth_info.update({"models": models["models"]})
        auth_info.update({"accounts_info": accounts_info})

        account_ordering = accounts_info.get("account_ordering", [])
        is_deactivated = None
        plan_type = None
        team_ids = []
        for account in account_ordering:
            this_is_deactivated = accounts_info['accounts'].get(account, {}).get("account", {}).get("is_deactivated",
                                                                                                    False)
            this_plan_type = accounts_info['accounts'].get(account, {}).get("account", {}).get("plan_type", "free")

            if this_is_deactivated and is_deactivated is None:
                is_deactivated = True
            else:
                is_deactivated = False

            if this_plan_type == "chatgptteamplan":
                plan_type = "chatgptteamplan"
                team_ids.append(account)
            elif plan_type is None:
                plan_type = this_plan_type

        auth_info.update({"accountCheckInfo": {
            "is_deactivated": is_deactivated,
            "plan_type": plan_type,
            "team_ids": team_ids
        }})

        return auth_info

    async def chatgpt_refresh(refresh_token):
        data = {
            "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
            "grant_type": "refresh_token",
            "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
            "refresh_token": refresh_token
        }
        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
        r = await client.post("https://auth0.openai.com/oauth/token", json=data, timeout=5)
        res = r.json()
        await client.close()
        auth_info = {}
        auth_info.update(res)
        auth_info.update({"refresh_token": refresh_token})
        auth_info.update({"accessToken": res.get("access_token", "")})
        if r.status_code == 200:
            access_token = res['access_token']
            auth_info.update(await chatgpt_account_check(access_token))
            return auth_info
        return auth_info


    @app.post("/auth/refresh")
    async def refresh(request: Request):
        auth_info = {}
        form_data = await request.form()

        refresh_token = form_data.get("refresh_token", "")
        access_token = form_data.get("access_token", form_data.get("accessToken", ""))
        if not refresh_token and not access_token:
            return {"error": "refresh_token or access_token is required"}

        if refresh_token:
            auth_info.update(await chatgpt_refresh(refresh_token))
            access_token = auth_info.get("access_token", "")
        if access_token:
            auth_info.update(await chatgpt_account_check(access_token))
        response = Response(content=json.dumps(auth_info), media_type="application/json")
        return response

    @app.get("/login", response_class=HTMLResponse)
    async def login_html(request: Request):
        response = templates.TemplateResponse("login.html", {"request": request})
        return response


    @app.get("/gpts")
    async def get_gpts():
        return {"kind": "store"}


    @app.get("/backend-api/gizmos/bootstrap")
    async def get_gizmos_bootstrap():
        return {"gizmos": []}


    @app.get("/backend-api/conversations")
    async def get_conversations(request: Request):
        limit = int(request.query_params.get("limit", 28))
        offset = int(request.query_params.get("offset", 0))
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if len(token) == 45 or token.startswith("eyJhbGciOi"):
            return await chatgpt_reverse_proxy(request, "backend-api/conversations")
        else:
            items = []
            for conversation_id in globals.seed_map.get(token, {}).get("conversations", []):
                conversation = globals.conversation_map.get(conversation_id, None)
                if conversation:
                    items.append(conversation)
            items = items[int(offset):int(offset) + int(limit)]
            conversations = {
                "items": items,
                "total": len(items),
                "limit": limit,
                "offset": offset,
                "has_missing_conversations": False
            }
            return conversations


    @app.get("/backend-api/conversation/{conversation_id}")
    async def update_conversation(request: Request, conversation_id: str):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        conversation_details_response = await chatgpt_reverse_proxy(request,
                                                                    f"backend-api/conversation/{conversation_id}")
        if len(token) == 45 or token.startswith("eyJhbGciOi"):
            return conversation_details_response
        else:
            conversation_details_str = conversation_details_response.body.decode('utf-8')
            conversation_details = json.loads(conversation_details_str)
            if conversation_id in globals.seed_map[token][
                "conversations"] and conversation_id in globals.conversation_map:
                globals.conversation_map[conversation_id]["title"] = conversation_details.get("title", None)
                globals.conversation_map[conversation_id]["is_archived"] = conversation_details.get("is_archived",
                                                                                                    False)
                with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(globals.conversation_map, f, indent=4)
            return conversation_details_response


    @app.patch("/backend-api/conversation/{conversation_id}")
    async def patch_conversation(request: Request, conversation_id: str):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        patch_response = (await chatgpt_reverse_proxy(request, f"backend-api/conversation/{conversation_id}"))
        if len(token) == 45 or token.startswith("eyJhbGciOi"):
            return patch_response
        else:
            data = await request.json()
            if conversation_id in globals.seed_map[token][
                "conversations"] and conversation_id in globals.conversation_map:
                if not data.get("is_visible", True):
                    globals.conversation_map.pop(conversation_id)
                    globals.seed_map[token]["conversations"].remove(conversation_id)
                    with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
                        json.dump(globals.seed_map, f, indent=4)
                else:
                    globals.conversation_map[conversation_id].update(data)
                with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(globals.conversation_map, f, indent=4)
            return patch_response


    @app.post("/backend-api/conversation/gen_title/{conversation_id}")
    async def gen_title(request: Request, conversation_id: str):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        gen_title_response = await chatgpt_reverse_proxy(request,
                                                         f"backend-api/conversation/gen_title/{conversation_id}")
        if len(token) == 45 or token.startswith("eyJhbGciOi"):
            return gen_title_response
        else:
            conversation_gen_title_str = gen_title_response.body.decode('utf-8')
            conversation_gen_title = json.loads(conversation_gen_title_str)
            title = conversation_gen_title.get("message", '').split("'")[1]
            if conversation_id in globals.seed_map[token][
                "conversations"] and conversation_id in globals.conversation_map:
                globals.conversation_map[conversation_id]["title"] = title
                with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(globals.conversation_map, f, indent=4)
            return gen_title_response


    @app.get("/backend-api/me")
    async def get_me(request: Request):
        me = {
            "object": "user",
            "id": "org-chatgpt",
            "email": "chatgpt@openai.com",
            "name": "ChatGPT",
            "picture": "https://cdn.auth0.com/avatars/ai.png",
            "created": int(time.time()),
            "phone_number": None,
            "mfa_flag_enabled": False,
            "amr": [],
            "groups": [],
            "orgs": {
                "object": "list",
                "data": [
                    {
                        "object": "organization",
                        "id": "org-chatgpt",
                        "created": 1715641300,
                        "title": "Personal",
                        "name": "user-chatgpt",
                        "description": "Personal org for chatgpt@openai.com",
                        "personal": True,
                        "settings": {},
                        "parent_org_id": None,
                        "is_default": False,
                        "role": "owner",
                        "is_scale_tier_authorized_purchaser": None,
                        "is_scim_managed": False,
                        "projects": {
                            "object": "list",
                            "data": []
                        },
                        "groups": [],
                        "geography": None
                    }
                ]
            },
            "has_payg_project_spend_limit": None
        }
        return me


    banned_paths = [
        "backend-api/accounts/logout_all",
        "backend-api/accounts/deactivate",
        "backend-api/user_system_messages",
        "backend-api/memories",
        "backend-api/settings/clear_account_user_memory",
        "backend-api/conversations/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        "backend-api/accounts/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/invites",
        "admin",
    ]
    redirect_paths = ["auth/logout"]
    chatgpt_paths = ["c/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"]


    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
    async def reverse_proxy(request: Request, path: str):
        if re.match("ces/v1", path):
            return {"success": True}

        if re.match("backend-api/edge", path):
            return Response(status_code=204)

        for chatgpt_path in chatgpt_paths:
            if re.match(chatgpt_path, path):
                return await chatgpt_html(request)

        for banned_path in banned_paths:
            if re.match(banned_path, path):
                raise HTTPException(status_code=403, detail="Forbidden")

        for redirect_path in redirect_paths:
            if re.match(redirect_path, path):
                redirect_url = str(request.base_url)
                response = RedirectResponse(url=f"{redirect_url}login", status_code=302)
                return response

        return await chatgpt_reverse_proxy(request, path)
else:
    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
    async def reverse_proxy():
        raise HTTPException(status_code=404, detail="Gateway is disabled")
