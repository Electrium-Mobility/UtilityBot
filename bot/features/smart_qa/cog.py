from discord.ext import commands
import aiohttp
import os

class SmartQACog(commands.Cog):
    """Smart Q&A feature placeholder implementation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # get API info
        self.api_url = os.getenv("OUTLINE_API_URL")
        self.api_token = os.getenv("OUTLINE_API_KEY")

    @commands.command(name="qa")
    async def qa(self, ctx: commands.Context, *, question: str):
        """Placeholder command: accept a question and return a placeholder response."""
        await ctx.send(f"Received question: {question}\n(Placeholder response, to be implemented)")
    
    @commands.command(name="collections") # discord command = "!collections" 
    async def get_collections(self, ctx):
        """Display number and names of all Outline collections in docs."""
        headers = {"Authorization": f"Bearer {self.api_token}"} # create http header for docs

        # send post request to get collections 
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.api_url}/collections.list", headers=headers) as resp:
                data = await resp.json()

        # check if response contains "data" field
        if "data" not in data:
            await ctx.send("Failed to fetch collections. Check API token or URL.")
            return

        collections = data["data"] # collections data
        names = [c["name"] for c in collections] # names of collections
        
        # print out collections info 
        message = f"{len(names)} collections found:\n" + "\n".join(f"- {n}" for n in names)
        await ctx.send(message)

async def setup(bot: commands.Bot):
    await bot.add_cog(SmartQACog(bot))