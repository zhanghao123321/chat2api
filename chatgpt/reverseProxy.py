import json
import random

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask

from chatgpt.authorization import verify_token, get_req_token, get_ua
import chatgpt.globals as globals
from utils.Client import Client
from utils.config import chatgpt_base_url_list, proxy_url_list


from datetime import datetime, timezone

def generate_current_time():
    current_time = datetime.now(timezone.utc)
    formatted_time = current_time.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    return formatted_time

headers_reject_list = [
    "x-real-ip",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-forwarded-host",
    "x-forwarded-server",
    "cf-warp-tag-id",
    "cf-visitor",
    "cf-ray",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cdn-loop",
    "remote-host",
    "x-frame-options",
    "x-xss-protection",
    "x-content-type-options",
    "content-security-policy",
    "host",
    "cookie",
    "connection",
    "content-length",
    "content-encoding",
    "x-middleware-prefetch",
    "x-nextjs-data",
    "purpose",
    "x-forwarded-uri",
    "x-forwarded-path",
    "x-forwarded-method",
    "x-forwarded-protocol",
    "x-forwarded-scheme",
    "cf-request-id",
    "cf-worker",
    "cf-access-client-id",
    "cf-access-client-device-type",
    "cf-access-client-device-model",
    "cf-access-client-device-name",
    "cf-access-client-device-brand",
    "x-middleware-prefetch",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-server",
    "x-real-ip",
    "x-forwarded-port",
    "cf-connecting-ip",
    "cf-ipcountry",
    "cf-ray",
    "cf-visitor",
]


async def get_real_req_token(token):
    req_token = get_req_token(token)
    if len(req_token) == 45 or req_token.startswith("eyJhbGciOi"):
        return req_token
    else:
        req_token = get_req_token(None, token)
        return req_token


async def content_generator(r, token):
    first_chunk = None
    async for chunk in r.aiter_content():
        if first_chunk is None and len(token) != 45 and not token.startswith("eyJhbGciOi"):
            first_chunk = chunk.decode('utf-8')
            conversation_id = json.loads(first_chunk[6:]).get("conversation_id")
            conversation_detail = {
                "id": conversation_id,
                "title": "New Chat",
                "update_time": generate_current_time(),
                "workspace_id": None,
            }
            if conversation_id not in globals.conversation_map:
                globals.conversation_map[conversation_id] = conversation_detail
            else:
                globals.conversation_map[conversation_id]["update_time"] = generate_current_time()
            if conversation_id not in globals.seed_map[token]["conversations"]:
                globals.seed_map[token]["conversations"].insert(0, conversation_id)
            else:
                globals.seed_map[token]["conversations"].remove(conversation_id)
                globals.seed_map[token]["conversations"].insert(0, conversation_id)
            with open(globals.CONVERSATION_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.conversation_map, f)
            with open(globals.SEED_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.seed_map, f, indent=4)
        yield chunk


async def chatgpt_reverse_proxy(request: Request, path: str):
    try:
        origin_host = request.url.netloc
        if request.url.is_secure:
            petrol = "https"
        else:
            petrol = "http"
        if "x-forwarded-proto" in request.headers:
            petrol = request.headers["x-forwarded-proto"]
        if "cf-visitor" in request.headers:
            cf_visitor = json.loads(request.headers["cf-visitor"])
            petrol = cf_visitor.get("scheme", petrol)

        params = dict(request.query_params)
        request_cookies = dict(request.cookies)

        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() not in ["host", "origin", "referer", "priority", "oai-device-id"] and key.lower() not in headers_reject_list)
        }

        base_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        if "assets/" in path:
            base_url = "https://cdn.oaistatic.com"
        if "file-" in path and "backend-api" not in path:
            base_url = "https://files.oaiusercontent.com"

        token = request.cookies.get("token")
        req_token = await get_real_req_token(token)
        ua = get_ua(req_token)
        headers.update(ua)

        headers.update({
            "accept-language": "en-US,en;q=0.9",
            "host": base_url.replace("https://", "").replace("http://", ""),
            "origin": base_url,
            "referer": f"{base_url}/"
        })

        token = headers.get("authorization", "").replace("Bearer ", "")
        if token:
            req_token = await get_real_req_token(token)
            access_token = await verify_token(req_token)
            headers.update({"authorization": access_token})

        data = await request.body()

        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
        try:
            background = BackgroundTask(client.close)
            r = await client.request(request.method, f"{base_url}/{path}", params=params, headers=headers,
                                     cookies=request_cookies, data=data, stream=True, allow_redirects=False)

            if r.status_code == 302:
                return Response(status_code=302,
                                headers={"Location": r.headers.get("Location").replace("chatgpt.com", origin_host)
                                .replace("cdn.oaistatic.com", origin_host)
                                .replace("https", petrol)}, background=background)
            elif 'stream' in r.headers.get("content-type", ""):
                return StreamingResponse(content_generator(r, token), media_type=r.headers.get("content-type", ""),
                                         background=background)
            else:
                if "/backend-api/conversation" in path or "/register-websocket" in path:
                    response = Response(content=(await r.atext()), media_type=r.headers.get("content-type"),
                                        status_code=r.status_code, background=background)
                else:
                    content = ((await r.atext()).replace("chatgpt.com", origin_host)
                               .replace("cdn.oaistatic.com", origin_host)
                               # .replace("files.oaiusercontent.com", origin_host)
                               .replace("https", petrol))
                    rheaders = dict(r.headers)
                    content_type = rheaders.get("content-type", "")
                    cache_control = rheaders.get("cache-control", "")
                    expires = rheaders.get("expires", "")
                    rheaders = {
                        "cache-control": cache_control,
                        "content-type": content_type,
                        "expires": expires
                    }
                    response = Response(content=content, headers=rheaders,
                                        status_code=r.status_code, background=background)
                return response
        except Exception:
            await client.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
