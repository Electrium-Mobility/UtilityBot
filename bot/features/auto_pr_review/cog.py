from discord.ext import commands
import requests
import re


class AutoPRReviewCog(commands.Cog):
    """Auto PR Review Assistant feature placeholder implementation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="prreview")
    async def prreview(self, ctx: commands.Context, *, pr_link: str):
        """Placeholder command: accept a PR link and return a placeholder response."""
        
        print("prreview command called")
        print(f"Received PR link: {pr_link}")


        pattern = r"https://github.com/Electrium-Mobility/([^/]+)/pull/([^/]+)/files"
        match = re.match(pattern,pr_link)
        if match is None:
            await ctx.send("❌ Invalid format for a PR link. Please send a PR from an Electrium-Mobility repo.")
            return

        project, pullNumber = match.groups()

        response = requests.get(f'https://api.github.com/repos/Electrium-Mobility/{project}/pulls/{pullNumber}')

        if response.status_code != 200:
            await ctx.send(f"Failed to fetch PR details, Please try again different PR link")
        else:
            responseJson = response.json()
            
            print(responseJson)
            
            await ctx.send(f"""
            ✅ **Pull Request Received!**

            📦 **Repository:** `{project}`
            👤 **Author:** `{responseJson['user']['login']}`
            🔢 **PR Number:** `#{responseJson['number']}`
            {"✅ Mergeable" if responseJson["mergeable"] else '❌ Merge Conflicts — please resolve!' }

            📝 **Title:** {responseJson['title']}
            💬 **Description:**  
                {responseJson.get('body') or '_No description provided._'}

            🔗 **Link:** {responseJson['html_url']}
            """
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoPRReviewCog(bot))