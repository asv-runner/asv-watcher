import asyncio
import os
import aiohttp
from gidgethub.aiohttp import GitHubAPI


async def main():
    async with aiohttp.ClientSession() as session:
        gh = GitHubAPI(session, "asv-runner", oauth_token=os.getenv("GH_AUTH"))
        await gh.post(
            "/repos/asv-runner/asv-watcher/issues",
            data={
                "title": "Regression!",
                "body": "You broke it."
            }
        )


asyncio.run(main())
