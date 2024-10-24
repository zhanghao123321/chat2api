import asyncio
import random

from fastapi import HTTPException
import ua_generator

from chatgpt.refreshToken import rt2ac
from utils.Logger import logger
from utils.config import authorization_list
import chatgpt.globals as globals


def get_req_token(req_token):
    if req_token in authorization_list:
        if len(globals.token_list) - len(globals.error_token_list) > 0:
            globals.count += 1
            globals.count %= len(globals.token_list)
            while globals.token_list[globals.count] in globals.error_token_list:
                globals.count += 1
                globals.count %= len(globals.token_list)
            return globals.token_list[globals.count]
        else:
            return None
    else:
        return req_token


def get_ua(req_token):
    user_agent = globals.user_agent_map.get(req_token, "")
    # token为空，免登录用户，则随机生成ua
    if not user_agent:
        ua = ua_generator.generate(device='desktop', browser=('chrome', 'edge'), platform=('windows', 'macos'))
        return {
            "User-Agent": ua.text,
            "Sec-Ch-Ua-Platform": ua.platform,
            "Sec-Ch-Ua": ua.ch.brands,
            "Sec-Ch-Ua-Mobile": ua.ch.mobile,
            "impersonate": random.choice(globals.impersonate_list),
        }
    else:
        return user_agent


async def verify_token(req_token):
    if not req_token:
        if authorization_list:
            logger.error("Unauthorized with empty token.")
            raise HTTPException(status_code=401)
        else:
            return None
    else:
        if req_token.startswith("eyJhbGciOi") or req_token.startswith("fk-"):
            access_token = req_token
            return access_token
        elif len(req_token) == 45:
            try:
                access_token = await rt2ac(req_token, force_refresh=False)
                return access_token
            except HTTPException as e:
                raise HTTPException(status_code=e.status_code, detail=e.detail)
        else:
            return req_token


async def refresh_all_tokens(force_refresh=False):
    for token in globals.token_list:
        if len(token) == 45:
            try:
                await asyncio.sleep(2)
                await rt2ac(token, force_refresh=force_refresh)
            except HTTPException:
                pass
    logger.info("All tokens refreshed.")
