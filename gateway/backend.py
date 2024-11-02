import json
import re
import time
import uuid

from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import utils.globals as globals
from app import app, templates
from gateway.reverseProxy import chatgpt_reverse_proxy
from utils.configs import authorization_list
from utils.configs import enable_gateway

with open("templates/remix_context.json", "r", encoding="utf-8") as f:
    remix_context = json.load(f)


def set_value_for_key(data, target_key, new_value):
    if isinstance(data, dict):
        for key, value in data.items():
            if key == target_key:
                data[key] = new_value
            else:
                set_value_for_key(value, target_key, new_value)
    elif isinstance(data, list):
        for item in data:
            set_value_for_key(item, target_key, new_value)


if enable_gateway:
    @app.get("/", response_class=HTMLResponse)
    async def chatgpt_html(request: Request):
        token = request.query_params.get("token")
        if not token:
            token = request.cookies.get("token")
        if not token:
            return await login_html(request)

        user_remix_context = remix_context.copy()
        set_value_for_key(user_remix_context, "user", {"id": "user-chatgpt"})
        set_value_for_key(user_remix_context, "accessToken", token)

        response = templates.TemplateResponse("chatgpt.html", {"request": request, "remix_context": user_remix_context})
        response.set_cookie("token", value=token, expires="Thu, 01 Jan 2099 00:00:00 GMT")
        return response

    # @app.get("/backend-api/accounts/check/v4-2023-04-27")
    # async def check_account(request: Request):
    #     token = request.headers.get("Authorization").replace("Bearer ", "")
    #     check_account_response = await chatgpt_reverse_proxy(request, "backend-api/accounts/check/v4-2023-04-27")
    #     if len(token) == 45 or token.startswith("eyJhbGciOi"):
    #         return check_account_response
    #     else:
    #         check_account_str = check_account_response.body.decode('utf-8')
    #         check_account_info = json.loads(check_account_str)
    #         for key in check_account_info.get("accounts", {}).keys():
    #             account_id = check_account_info["accounts"][key]["account"]["account_id"]
    #             globals.seed_map[token]["user_id"] = check_account_info["accounts"][key]["account"]["account_user_id"].split("__")[0]
    #             check_account_info["accounts"][key]["account"]["account_user_id"] = f"user-chatgpt__{account_id}"
    #         with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
    #             json.dump(globals.seed_map, f, indent=4)
    #         return check_account_info


    def verify_authorization(request: Request):
        auth_header = request.headers.get("Authorization").replace("Bearer ", "")

        if not auth_header:
            raise HTTPException(status_code=401, detail="Authorization header is missing")
        if auth_header not in authorization_list:
            raise HTTPException(status_code=401, detail="Invalid authorization")


    @app.get("/seedtoken")
    async def get_seedtoken(request: Request):
        verify_authorization(request)
        try:
            params = request.query_params
            seed = params.get("seed")

            if seed:
                if seed not in globals.seed_map:
                    raise HTTPException(status_code=404, detail=f"Seed '{seed}' not found")
                return {
                    "status": "success",
                    "data": {
                        "seed": seed,
                        "token": globals.seed_map[seed]["token"]
                    }
                }

            token_map = {
                seed: data["token"]
                for seed, data in globals.seed_map.items()
            }
            return {"status": "success", "data": token_map}

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


    @app.post("/seedtoken")
    async def set_seedtoken(request: Request):
        verify_authorization(request)
        data = await request.json()

        seed = data.get("seed")
        token = data.get("token")

        if seed not in globals.seed_map:
            globals.seed_map[seed] = {
                "token": token,
                "conversations": []
            }
        else:
            globals.seed_map[seed]["token"] = token

        with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(globals.seed_map, f, indent=4)

        return {"status": "success", "message": "Token updated successfully"}


    @app.delete("/seedtoken")
    async def delete_seedtoken(request: Request):
        verify_authorization(request)

        try:
            data = await request.json()
            seed = data.get("seed")

            if not seed:
                raise HTTPException(status_code=400, detail="Missing required field: seed")

            if seed not in globals.seed_map:
                raise HTTPException(status_code=404, detail=f"Seed '{seed}' not found")
            del globals.seed_map[seed]

            with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.seed_map, f, indent=4)

            return {
                "status": "success",
                "message": f"Seed '{seed}' deleted successfully"
            }

        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON data")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
                        "settings": {
                            "threads_ui_visibility": "NONE",
                            "usage_dashboard_visibility": "ANY_ROLE",
                            "disable_user_api_keys": False
                        },
                        "parent_org_id": None,
                        "is_default": True,
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
            "has_payg_project_spend_limit": True
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
        if re.match("/v1/rgstr", path):
            return Response(status_code=202, content=b'{"success":true}')

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
