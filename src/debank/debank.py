import asyncio
import json
import time
import uuid

from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient, Response
from loguru import logger

from debank.const import HEADERS


class DebankError(Exception):
    pass


class DebankApiUrl:
    REFCODE_TRACK = "https://api.debank.com/user/ref_code/track"
    BADGE_USER_CAN_MINT = "https://api.debank.com/badge/user_can_mint"
    BADGE_MINT = "https://api.debank.com/badge/mint"
    SIGN_V2 = "https://api.debank.com/user/sign_v2"
    LOGIN_V2 = "https://api.debank.com/user/login_v2"
    BADGE_LIST = "https://api.debank.com/badge/list"


class Debank:
    def __init__(self, proxy: str | None) -> None:
        self.client = AsyncClient(
            headers=HEADERS,
            http2=True,
            proxies={"all://": proxy} if proxy else None
        )

    def __del__(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.client.aclose())
            else:
                loop.run_until_complete(self.client.aclose())
        except Exception:
            pass

    def validate_response(self, response: Response) -> Response:
        if response.status_code != 200:
            raise DebankError(f"Debank return {response.text}")
        
        if "error_msg" in (err_json := response.json()):
            raise DebankError(f"Debank return {err_json['error_msg']}")

        return response
    
    async def refcode_track(self) -> Response:
        return self.validate_response(
            await self.client.post(DebankApiUrl.REFCODE_TRACK)
        )
    
    async def badge_user_can_mint(self, id: int) -> Response:
        return self.validate_response(
            await self.client.get(DebankApiUrl.BADGE_USER_CAN_MINT, params={"id": id})
        )
    
    async def badge_mint(self, id: int) -> Response:
        return self.validate_response(
            await self.client.get(DebankApiUrl.BADGE_MINT, json={"id": id})
        )

    async def sign_v2(self, address: str) -> Response:
        return self.validate_response(
            await self.client.post(DebankApiUrl.SIGN_V2, json={"id": address})
        )
    
    async def login_v2(self, address: str, signature: str) -> Response:
        return self.validate_response(
            await self.client.post(DebankApiUrl.LOGIN_V2, json={"id": address, "signature": signature})
        )


class DebankWorker(Debank):
    def __init__(self, proxy: str | None) -> None:
        super().__init__(proxy)

    async def login(self, account: Account) -> None:
        sign_v2_response = await self.sign_v2(account.address.lower())
        sign_v2_text = sign_v2_response.json()["data"]["text"]

        signature = account.sign_message(encode_defunct(text=sign_v2_text)).signature.hex()

        login_v2_response = await self.login_v2(account.address.lower(), signature)

        session_id = login_v2_response.json()["data"]["session_id"]

        account_header = {
            "random_at": int(time.time()),
            "random_id": uuid.uuid4().hex,
            "session_id": session_id,
            "user_addr": account.address.lower(),
            "wallet_type":"metamask",
            "is_verified": True
        }

        self.client.headers["account"] = json.dumps(account_header)
    
    async def is_can_mint_bage(self, id: int) -> bool:
        return (await self.badge_user_can_mint(id)).json()["data"]["can_mint"]


async def badge_list() -> dict[int, str]:
    async with AsyncClient(headers=HEADERS, http2=True) as client:
        response = await client.get(DebankApiUrl.BADGE_LIST)

    badges = response.json()["data"]["badge_list"]

    logger.info(
        f"Found {len(badges)} badges. Names: {', '.join([badge['name'] for badge in badges])}."
    )

    return {badge["id"]: badge["name"] for badge in badges}


async def worker(q: asyncio.Queue, BADGE_IDS: dict[int, str]) -> None:
    while not q.empty():
        private_key, proxy = await q.get()

        account: Account = Account.from_key(private_key)

        debank = DebankWorker(proxy)

        try:
            await debank.login(account)

            for id, name in BADGE_IDS.items():
                is_can_mint = await debank.is_can_mint_bage(id)

                if is_can_mint:
                    await debank.badge_mint(id)
                    logger.success(f"[{account.address}] Badge {name} minted")
                else:
                    logger.error(f"[{account.address}] Badge {name} can't minted")

                await asyncio.sleep(2)
        except DebankError as e:
            logger.error(f"Debank Error: {e}")
        except Exception as e:
            logger.error(f"Error: {e}")
