import asyncio
import sys
import time
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord.ext import commands
from discord.ext.commands import Context
from sqlalchemy import select

from database.models import Cookie

if TYPE_CHECKING:
    from bot import ChuniBot
    from cogs.botutils import UtilsCog


class KamaitachiCog(commands.Cog):
    def __init__(self, bot: "ChuniBot") -> None:
        self.bot = bot
        self.utils: "UtilsCog" = bot.get_cog("Utils")  # type: ignore[reportGeneralTypeIssues]

        if (kt_client_id := self.bot.cfg.credentials.kamaitachi_client_id) is None:
            msg = "Kamaitachi client ID is not set"
            raise ValueError(msg)

        self.kt_client_id = kt_client_id
        self.user_agent = f"ChuniBot (https://github.com/Rapptz/discord.py {discord.__version__}) Python/{sys.version_info[0]}.{sys.version_info[1]} aiohttp/{aiohttp.__version__}"

    async def cog_unload(self) -> None:
        return await super().cog_unload()

    @commands.group("kamaitachi", aliases=["kt"], invoke_without_command=True)
    async def kamaitachi(self, ctx: Context):
        pass

    async def _verify_and_login(self, token: str) -> Optional[str]:
        async with aiohttp.ClientSession() as session, session.get(
            "https://kamaitachi.xyz/api/v1/status",
            headers={
                "Authorization": f"Bearer {token}",
            },
        ) as resp:
            data = await resp.json()

        if data["success"] is False:
            return data["description"]

        if data["body"]["whoami"] is None:
            return "The provided API token is not bound to any user."

        permissions = data["body"]["permissions"]
        if "submit_score" not in permissions or "customise_score" not in permissions:
            return (
                "The provided API token is missing permissions.\n"
                "Ensure that the token has permissions `submit_score` and `customise_score`"
            )

        return None

    @kamaitachi.command("link", aliases=["login"])
    async def kamaitachi_link(self, ctx: Context, token: str):
        async with self.bot.begin_db_session() as session:
            query = select(Cookie).where(Cookie.discord_id == ctx.author.id)
            cookie = (await session.execute(query)).scalar_one_or_none()

        if cookie is None:
            return await ctx.reply(
                content="Please login with `c>login` first before linking with Kamaitachi.",
                mention_author=False,
            )

        if not isinstance(ctx.channel, discord.channel.DMChannel):
            please_delete_message = ""
            if token is not None:
                try:
                    await ctx.message.delete()
                except discord.errors.Forbidden:
                    please_delete_message = "Please delete the original command. Why are you exposing your API keys?"

            channel = (
                ctx.author.dm_channel
                if ctx.author.dm_channel
                else await ctx.author.create_dm()
            )

            await ctx.send(
                f"Login instructions have been sent to your DMs. {please_delete_message}"
                "(please **enable Privacy Settings -> Direct Messages** if you haven't received it.)"
            )
        elif token is not None:
            result = await self._verify_and_login(token)
            if result is not None:
                raise commands.BadArgument(result)

            cookie.kamaitachi_token = token
            async with self.bot.begin_db_session() as session, session.begin():
                await session.merge(cookie)

            return await ctx.reply(
                content="Successfully linked with Kamaitachi.", mention_author=False
            )

        embed = discord.Embed(
            title="Link with Kamaitachi",
            color=0xCA1961,
            description=(
                f"Retrive an API key from https://kamaitachi.xyz/client-file-flow/{self.kt_client_id} then "
                "run `c>kamaitachi link <token>` in DMs."
            ),
        )

        return await channel.send(
            content="Kamaitachi is a modern score tracker for arcade rhythm games.",
            embed=embed,
        )

    @kamaitachi.command("unlink", aliases=["logout"])
    async def kamaitachi_unlink(self, ctx: Context):
        async with self.bot.begin_db_session() as session:
            query = select(Cookie).where(Cookie.discord_id == ctx.author.id)
            cookie = (await session.execute(query)).scalar_one_or_none()

        if cookie is None or cookie.kamaitachi_token is None:
            return await ctx.reply(
                content="You are not linked with Kamaitachi.", mention_author=False
            )

        cookie.kamaitachi_token = None
        async with self.bot.begin_db_session() as session:
            await session.merge(cookie)

        return await ctx.reply(
            content="Successfully unlinked with Kamaitachi.", mention_author=False
        )

    @kamaitachi.command("sync", aliases=["s"])
    async def kamaitachi_sync(self, ctx: Context, mode: str = "recent"):
        """Sync CHUNITHM scores with Kamaitachi.

        Parameters
        ----------
        mode: str
            What to sync with Kamaitachi. Only `recent` is currently supported.
        """
        async with self.bot.begin_db_session() as session:
            query = select(Cookie).where(Cookie.discord_id == ctx.author.id)
            cookie = (await session.execute(query)).scalar_one_or_none()

        if cookie is None:
            return await ctx.reply(
                content="Please login with `c>login` first before syncing with Kamaitachi.",
                mention_author=False,
            )

        if cookie.kamaitachi_token is None:
            return await ctx.reply(
                content="You are not linked with Kamaitachi. DM me with `c>kamaitachi link` for instructions.",
                mention_author=False,
            )

        scores = []
        message = await ctx.reply(
            "Fetching recent scores from CHUNITHM-NET...", mention_author=False
        )
        async with self.utils.chuninet(ctx) as client:
            await client.authenticate()

            recents = await client.recent_record()
            for recent in recents:
                score_data = {
                    "score": recent.score,
                    "lamp": str(recent.clear),
                    "matchType": "inGameID",
                    "identifier": "",
                    "difficulty": str(recent.difficulty),
                    "timeAchieved": time.mktime(recent.date.timetuple()) * 1000,
                    "judgements": {},
                    "hitMeta": {},
                }

                if recent.detailed is None:
                    continue

                detailed_recent = await client.detailed_recent_record(
                    recent.detailed.idx
                )

                if detailed_recent.detailed is None:
                    continue

                score_data["identifier"] = str(detailed_recent.detailed.idx)

                score_data["judgements"]["jcrit"] = detailed_recent.judgements.jcrit
                score_data["judgements"]["justice"] = detailed_recent.judgements.justice
                score_data["judgements"]["attack"] = detailed_recent.judgements.attack
                score_data["judgements"]["miss"] = detailed_recent.judgements.miss

                if (
                    detailed_recent.judgements.justice == 0
                    and detailed_recent.judgements.attack == 0
                    and detailed_recent.judgements.miss == 0
                ):
                    score_data["lamp"] = "ALL JUSTICE CRITICAL"

                score_data["hitMeta"]["maxCombo"] = detailed_recent.max_combo

                scores.append(score_data)

            await message.edit(content="Uploading scores to Kamaitachi...")
            request_body = {
                "meta": {
                    "game": "chunithm",
                    "playtype": "Single",
                    "service": "site-importer",
                },
                "scores": scores,
            }

            async with aiohttp.ClientSession() as session, session.post(
                "https://kamaitachi.xyz/ir/direct-manual/import",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {cookie.kamaitachi_token}",
                    "Content-Type": "application/json",
                    "X-User-Intent": "true",
                },
            ) as resp:
                data = await resp.json()

                if not data["success"]:
                    return await message.edit(
                        content=f"Failed to upload scores to Kamaitachi: {data['description']}"
                    )
                poll_url = data["body"]["url"]

            while True:
                async with aiohttp.ClientSession() as session, session.get(
                    poll_url,
                    headers={
                        "Authorization": f"Bearer {cookie.kamaitachi_token}",
                    },
                ) as resp:
                    data = await resp.json()

                if not data["success"]:
                    return await message.edit(
                        content=f"Failed to upload scores to Kamaitachi: {data['description']}"
                    )

                if data["body"]["importStatus"] == "ongoing":
                    await message.edit(
                        content=(
                            f"Importing scores: {data['description']}\n"
                            f"Progress: {data['body']['progress']['description']}"
                        )
                    )
                    await asyncio.sleep(2)
                    continue

                if data["body"]["importStatus"] == "completed":
                    msg = f"{data['description']} {len(data['body']['import']['scoreIDs'])} scores"

                    if len(data["body"]["import"]["errors"]) > 0:
                        msg += f", {len(data['body']['import']['errors'])} errors"

                    return await message.edit(content=msg)


async def setup(bot: "ChuniBot"):
    await bot.add_cog(KamaitachiCog(bot))
