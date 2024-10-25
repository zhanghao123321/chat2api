import random

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask

from chatgpt.authorization import get_ua
from utils.Client import Client
from utils.config import chatgpt_base_url_list, proxy_url_list, enable_gateway

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


async def chatgpt_reverse_proxy(request: Request, path: str):
    if not enable_gateway:
        raise HTTPException(status_code=404, detail="Gateway is disabled")

    try:
        origin_host = request.url.netloc
        if request.url.is_secure:
            petrol = "https"
        else:
            petrol = "http"

        params = dict(request.query_params)
        request_cookies = dict(request.cookies)
        headers = {
            key: value for key, value in request.headers.items()
            if (key.lower() not in ["host", "origin", "referer", "user-agent",
                                    "authorization"] and key.lower() not in headers_reject_list)
        }

        base_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        if "assets/" in path:
            base_url = "https://cdn.oaistatic.com"
        if "file-" in path and "backend-api" not in path:
            base_url = "https://files.oaiusercontent.com"

        req_token = request.cookies.get("req_token")
        ua = get_ua(req_token)
        headers.update(ua)
        headers.update({
            "accept-Language": "en-US,en;q=0.9",
            "host": base_url.replace("https://", "").replace("http://", ""),
            "origin": base_url,
            "referer": f"{base_url}/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        })

        if request.headers.get('Authorization'):
            headers['Authorization'] = request.headers['Authorization']

        if headers.get("Content-Type") == "application/json":
            data = await request.json()
        else:
            data = await request.body()

        client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None, impersonate=ua.get("impersonate"))
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
                return StreamingResponse(r.aiter_content(), media_type=r.headers.get("content-type", ""),
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
                    response.set_cookie("access_token", value=request_cookies.get("access_token", ""), domain=origin_host)
                return response
        except Exception:
            await client.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
