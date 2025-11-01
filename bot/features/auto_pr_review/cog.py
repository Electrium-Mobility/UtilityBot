from discord.ext import commands
import requests
import re
import os




DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") # Deep Seek API
MAX_LINES = 50 # Limit of max diff changes sent to the deepseek API to save tokens
MAX_TOKEN = 150 # Limit for token usage

class AutoPRReviewCog(commands.Cog):
    """Auto PR Review Assistant feature placeholder implementation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


    
    # method to remove unimportant lines from diff changes
    def filter_lines(self, lines):
        ignore_prefixes = ("import ", "from ", "#", "'''", '"""')
        return [
            l for l in lines
            if l.strip() and not l.strip().startswith(ignore_prefixes)
        ]


    # method to extract only the diff changes from diff_text
    def extract_changes(self, diff_text):
        added_lines = []
        removed_lines = []

        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue 
            
            ## Only add the lines the begin with + or -
            if line.startswith("+"):
                added_lines.append(line[1:].strip())
            elif line.startswith("-"):
                removed_lines.append(line[1:].strip())
        

        
        return [self.filter_lines(added_lines)[:MAX_LINES], self.filter_lines(removed_lines)[:MAX_LINES]]
    


    def analyze_with_deepseek(self, changes):
        added_lines = changes[0]
        removed_lines = changes[1]

        if not DEEPSEEK_API_KEY:
            return -1
        try:
            prompt = f"""
                You are an experienced senior software engineer performing an code review.

                Each section shows the removed and added code extracted from the diff.

                -----------------------------
                🟥 REMOVED CODE (truncated to {len(removed_lines)} lines):
                {removed_lines}

                -----------------------------
                🟩 ADDED CODE (truncated to {len(added_lines)} lines):
                {added_lines}
                -----------------------------

                Your task:
                1. **Summarize** the key functional and structural changes in plain English.  
                2. **Explain** the purpose or motivation behind the change if possible.  
                3. **Identify** any potential issues (bugs, performance, style, or security risks).  
                4. **Suggest** specific improvements or refactorings if relevant.  


                NOTE:Keep the tone concise, constructive, and focused on practical insights.
                NOTE: Use bullet points or short paragraphs for readability.
                NOTE: Divide your suggestions and summary with a header EX:(**Summary**, **Suggestions**)
                NOTE: Start your points message with a dash (-) 
                NOTE: Keep your response short, Stop once your summary is complete. DO NOT ADD EMOJIS
                EXAMPLE OUTPUT: 
                **Summary**
                - Switched from OpenAI to DeepSeek for text summarization
                - Changed model from GPT-4o-mini to deepseek-chat

                **Potential Issues**
                - Missing error handling for API calls
                - No validation for missing environment variables
            """

            response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-coder",
                "messages": [
                    {"role": "system", "content": "You are an experienced code reviewer analyzing Git diffs."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": MAX_TOKEN,
            },
            timeout=30,)

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"Error with deepseek: {e}"

        


    def analyze_diff(self, url):
        diffResponse = requests.get(url,
            headers={"Accept": 'application/vnd.github.v3.diff'}
        )

        diff_text = diffResponse.text
        diff_changes = self.extract_changes(diff_text)
        return self.analyze_with_deepseek(diff_changes)
        

    @commands.command(name="prreview")
    @commands.cooldown(1, 30, commands.BucketType.user) # Add a rate limit to only every 30s
    async def prreview(self, ctx: commands.Context, *, pr_link: str):
        """Placeholder command: accept a PR link and return a placeholder response."""
        
        print("prreview command called")
        print(f"Received PR link: {pr_link}")


        pattern = r"https://github.com/Electrium-Mobility/([^/]+)/pull/(\d+)"
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

            deepseek_response = self.analyze_diff(f'https://api.github.com/repos/Electrium-Mobility/{project}/pulls/{pullNumber}')
            deepseek_response = deepseek_response.replace("\\n", "\n").replace("\n**", "\n\n**").strip()
        
        
            

            mergeable_state = responseJson.get("mergeable_state")
            merged = responseJson.get("merged", False)

            if merged:
                merge_status = "✅ **Already merged!**"
            elif mergeable_state in ("clean", "unstable", "has_hooks"):
                merge_status = "✅ **Mergeable**"
            elif mergeable_state in ("dirty", "blocked", "behind"):
                merge_status = "❌ **Merge conflicts — please resolve!**"
            elif mergeable_state == "draft":
                merge_status = "📝 **Draft — not ready to merge yet**"
            else:
                merge_status = "❓ **Merge status unknown (GitHub still checking...)**"


            await ctx.send(
                f"✅ **Pull Request Received!**\n\n"
                f"📦 **Repository:** `{project}`\n"
                f"👤 **Author:** `{responseJson['user']['login']}`\n"
                f"🔢 **PR Number:** `#{responseJson['number']}`\n"
                f"📊 **Lines Added: {responseJson['additions']} | Lines Removed: {responseJson['deletions']}**\n"
                f"{merge_status}\n"
                f"📝 **Title:** {responseJson['title']}\n"
                f"🧠 **AI Summary:**\n"
                f"{deepseek_response}\n"
                f"🔗 **Link:** {responseJson['html_url']}"
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoPRReviewCog(bot))