import asyncio
import json
import random

import ua_generator
from fastapi import HTTPException

import utils.globals as globals
from chatgpt.refreshToken import rt2ac
from utils.Logger import logger
from utils.config import authorization_list, random_token, autoseed


def get_req_token(req_token, seed=None):
    if autoseed:
        available_token_list = list(set(globals.token_list) - set(globals.error_token_list))
        length = len(available_token_list)
        if seed and length > 0:
            if seed not in globals.seed_map.keys():
                globals.seed_map[seed] = {"token": random.choice(available_token_list), "conversations": []}
                with open(globals.SEED_MAP_FILE, "w") as f:
                    json.dump(globals.seed_map, f, indent=4)
            else:
                req_token = globals.seed_map[seed]["token"]
            return req_token

        if req_token in authorization_list:
            if len(available_token_list) > 0:
                if random_token:
                    req_token = random.choice(available_token_list)
                    return req_token
                else:
                    globals.count += 1
                    globals.count %= length
                    return available_token_list[globals.count]
            else:
                return None
        else:
            return req_token
    else:
        if seed not in globals.seed_map.keys():
            raise HTTPException(status_code=401, detail={"error": "Invalid Seed"})
        return globals.seed_map[seed]["token"]
        


def get_ua(req_token):
    user_agent = globals.user_agent_map.get(req_token, {})
    user_agent = {k.lower(): v for k, v in user_agent.items()}
    if not user_agent:
        if not req_token:
            ua = ua_generator.generate(device='desktop', browser=('chrome', 'edge'), platform=('windows', 'macos'))
            return {
                "user-agent": ua.text,
                "sec-ch-ua-platform": ua.platform,
                "sec-ch-ua": ua.ch.brands,
                "sec-ch-ua-mobile": ua.ch.mobile,
                "impersonate": random.choice(globals.impersonate_list),
            }
        else:
            ua = ua_generator.generate(device='desktop', browser=('chrome', 'edge'), platform=('windows', 'macos'))
            user_agent = {
                "user-agent": ua.text,
                "sec-ch-ua-platform": ua.platform,
                "sec-ch-ua": ua.ch.brands,
                "sec-ch-ua-mobile": ua.ch.mobile,
                "impersonate": random.choice(globals.impersonate_list),
            }
            globals.user_agent_map[req_token] = user_agent
            with open(globals.USER_AGENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(globals.user_agent_map, f, indent=4)
            return user_agent
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
    for token in list(set(globals.token_list) - set(globals.error_token_list)):
        if len(token) == 45:
            try:
                await asyncio.sleep(0.5)
                await rt2ac(token, force_refresh=force_refresh)
            except HTTPException:
                pass
    logger.info("All tokens refreshed.")
