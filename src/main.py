import asyncio

from loguru import logger

from debank import badge_list, worker


async def main():
    q = asyncio.Queue()

    with open("accounts.txt", "r") as f:
        accounts = f.read().splitlines()

    format_accounts = []
    for account in accounts:
        if ":" in account:
            format_accounts.append(account.split(":", maxsplit=1))
        else:
            format_accounts.append([account, None])

    for account in format_accounts:
        q.put_nowait(account)

    BADGE_IDS = await badge_list()

    await asyncio.gather(*[worker(q, BADGE_IDS) for _ in range(5)])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Exit!")
