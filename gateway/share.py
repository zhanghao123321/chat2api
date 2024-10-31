import json
import random

from fastapi import Request, HTTPException
from fastapi.responses import Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app import app
from chatgpt.authorization import get_ua, verify_token
from chatgpt.proofofWork import get_config, get_requirements_token, get_answer_token
from gateway.reverseProxy import get_real_req_token, content_generator
from utils.Client import Client
from utils.Logger import logger
from utils.config import proxy_url_list, chatgpt_base_url_list, turnstile_solver_url, x_sign

base_headers = {
    'accept': '*/*',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'accept-language': 'en-US,en;q=0.9',
    'content-type': 'application/json',
    'oai-language': 'en-US',
    'priority': 'u=1, i',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
}


async def chatgpt_account_check(access_token):
    auth_info = {}
    client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
    try:
        proxy_url = random.choice(proxy_url_list) if proxy_url_list else None
        host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
        req_token = await get_real_req_token(access_token)
        access_token = await verify_token(req_token)
        ua = get_ua(req_token)

        headers = base_headers.copy()
        headers.update({"authorization": f"Bearer {access_token}"})
        headers.update(ua)

        client = Client(proxy=proxy_url, impersonate=ua.get("impersonate", "safari15_3"))
        r = await client.get(f"{host_url}/backend-api/models?history_and_training_disabled=false", headers=headers, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        models = r.json()
        r = await client.get(f"{host_url}/backend-api/accounts/check/v4-2023-04-27", headers=headers, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        accounts_info = r.json()

        auth_info.update({"models": models["models"]})
        auth_info.update({"accounts_info": accounts_info})

        account_ordering = accounts_info.get("account_ordering", [])
        is_deactivated = None
        plan_type = None
        team_ids = []
        for account in account_ordering:
            this_is_deactivated = accounts_info['accounts'].get(account, {}).get("account", {}).get("is_deactivated", False)
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
    except Exception as e:
        logger.error(f"chatgpt_account_check: {e}")
        return {}
    finally:
        await client.close()


async def chatgpt_refresh(refresh_token):
    client = Client(proxy=random.choice(proxy_url_list) if proxy_url_list else None)
    try:
        data = {
            "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
            "grant_type": "refresh_token",
            "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
            "refresh_token": refresh_token
        }
        r = await client.post("https://auth0.openai.com/oauth/token", json=data, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        res = r.json()
        auth_info = {}
        auth_info.update(res)
        auth_info.update({"refresh_token": refresh_token})
        auth_info.update({"accessToken": res.get("access_token", "")})
        return auth_info
    except Exception as e:
        logger.error(f"chatgpt_refresh: {e}")
        return {}
    finally:
        await client.close()


@app.post("/auth/refresh")
async def refresh(request: Request):
    auth_info = {}
    form_data = await request.form()

    auth_info.update(form_data)

    access_token = auth_info.get("access_token", auth_info.get("accessToken", ""))
    refresh_token = auth_info.get("refresh_token", "")

    if not refresh_token and not access_token:
        raise HTTPException(status_code=401, detail="refresh_token or access_token is required")

    if access_token:
        account_check_info = await chatgpt_account_check(access_token)
        if account_check_info:
            auth_info.update(account_check_info)
            auth_info.update({"accessToken": access_token})
            return Response(content=json.dumps(auth_info), media_type="application/json")

    if refresh_token:
        chatgpt_refresh_info = await chatgpt_refresh(refresh_token)
        if chatgpt_refresh_info:
            auth_info.update(chatgpt_refresh_info)
            access_token = auth_info.get("accessToken", "")
            account_check_info = await chatgpt_account_check(access_token)
            if account_check_info:
                auth_info.update(account_check_info)
                auth_info.update({"accessToken": access_token})
                return Response(content=json.dumps(auth_info), media_type="application/json")
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/backend-api/conversation")
async def chat_conversations(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    req_token = await get_real_req_token(token)
    access_token = await verify_token(req_token)
    ua = get_ua(req_token)
    user_agent = ua.get("user-agent", "")
    proxy_url = random.choice(proxy_url_list) if proxy_url_list else None
    host_url = random.choice(chatgpt_base_url_list) if chatgpt_base_url_list else "https://chatgpt.com"
    proof_token = None
    turnstile_token = None

    headers = base_headers.copy()
    headers.update(ua)
    headers.update({"authorization": f"Bearer {access_token}"})

    client = Client(proxy=proxy_url, impersonate=ua.get("impersonate", "safari15_3"))

    config = get_config(user_agent)
    p = get_requirements_token(config)
    data = {'p': p}
    r = await client.post(f'{host_url}/backend-api/sentinel/chat-requirements', headers=headers, json=data, timeout=10)
    resp = r.json()
    turnstile = resp.get('turnstile', {})
    turnstile_required = turnstile.get('required')
    if turnstile_required:
        turnstile_dx = turnstile.get("dx")
        try:
            if turnstile_solver_url:
                res = await client.post(
                    turnstile_solver_url, json={"url": "https://chatgpt.com", "p": p, "dx": turnstile_dx}
                )
                turnstile_token = res.json().get("t")
        except Exception as e:
            logger.info(f"Turnstile ignored: {e}")

    proofofwork = resp.get('proofofwork', {})
    proofofwork_required = proofofwork.get('required')
    if proofofwork_required:
        proofofwork_diff = proofofwork.get("difficulty")
        proofofwork_seed = proofofwork.get("seed")
        proof_token, solved = await run_in_threadpool(
            get_answer_token, proofofwork_seed, proofofwork_diff, config
        )
        if not solved:
            raise HTTPException(status_code=403, detail="Failed to solve proof of work")
    chat_token = resp.get('token')
    headers.update({
        "openai-sentinel-chat-requirements-token": chat_token,
        "openai-sentinel-proof-token": proof_token,
        "openai-sentinel-turnstile-token": turnstile_token,
    })

    params = dict(request.query_params)
    data = await request.body()
    request_cookies = dict(request.cookies)
    background = BackgroundTask(client.close)
    r = await client.post_stream(f"{host_url}/backend-api/conversation", params=params, headers=headers, cookies=request_cookies, data=data, stream=True, allow_redirects=False)
    rheaders = r.headers
    if x_sign:
        rheaders.update({"x-sign": x_sign})
    if 'stream' in rheaders.get("content-type", ""):
        return StreamingResponse(content_generator(r, token), headers=rheaders, media_type=rheaders.get("content-type"), background=background)
    else:
        return Response(content=(await r.atext()), headers=rheaders, media_type=rheaders.get("content-type"), status_code=r.status_code, background=background)
