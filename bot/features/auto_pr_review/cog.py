from urllib import request
from discord.ext import tasks, commands
import requests
import aiohttp
import xml.etree.ElementTree as ET
import json
import re
import os
import json
import asyncio


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # Deep Seek API
MAX_LINES = 50  # Limit of max diff changes sent to the deepseek API to save tokens
MAX_TOKEN = 150  # Limit for token usage
STORAGE_PATH = os.path.join(os.path.dirname(__file__), "tracked_repos.json")


GITHUB_PAT = os.getenv(
    "GITHUB_PAT"
)  # github pat is needed to make requests to GitHub API

#retry/backoff for transient errors + rate limits
async def api_call_retry(session, method, url, retries=3, backoff_factor=1, headers=None, **kwargs):
        for attempt in range(retries + 1):
            try:
                async with session.request(method, url, headers=headers, **kwargs) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("retry after")
                        if retry_after:
                            await asyncio.sleep(float(retry_after))
                        else:
                            await asyncio.sleep(backoff_factor * (2 ** attempt))
                        continue
                    if resp.status in {500, 502, 503, 504}:
                        await asyncio.sleep(backoff_factor * (2** attempt))
                        continue

                    return resp
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await asyncio.sleep(backoff_factor * (2 ** attempt))
        raise Exception(f"api request failed after {retries} retries")


#async functions for requests
async def get_file_paths(url, headers):
            async with aiohttp.ClientSession() as session:
                resp = await api_call_retry(session, "GET", url, headers=headers)
                return resp
                
async def get_commit_information(url, headers):
        async with aiohttp.ClientSession() as session:
            resp = await api_call_retry(session, "GET", url, headers=headers)
            return resp
            
async def analyze_with_ai(url, headers, json, timeout):
        async with aiohttp.ClientSession() as session:
            resp = await api_call_retry(session, "POST", url, headers=headers, json=json, timeout=timeout)
            return resp
            
async def get_diff(url, headers):
        async with aiohttp.ClientSession() as session:
            resp = await api_call_retry(session, "GET", url, headers=headers)
            return resp
            
async def get_pulls(url):
        async with aiohttp.ClientSession() as session:
            resp = await api_call_retry(session, "GET", url)
            return resp
            
async def get_feed(url):
        async with aiohttp.ClientSession() as session:
            resp = await api_call_retry(session, "GET", url)
            return resp

class AutoPRReviewCog(commands.Cog):
    """Auto PR Review Assistant feature placeholder implementation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tracked_feeds = {}
        self.load_tracked_feeds()
        self.poll_atom_feeds.start()


    # method that returns files to ignore when putting it into ai
    def ignore_files(self, repo):

        headers={
                "Authorization": f"token {GITHUB_PAT}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1521.3 Safari/537.36",
            }
        raw_response = asyncio.run(get_file_paths(f"https://api.github.com/repos/Electrium-Mobility/{repo}/git/trees/main?recursive=1", headers))

        if raw_response.status_code != 200:
            print(f"Error: {raw_response.status_code}")
            return

        response_json = raw_response.json()

        paths = [item["path"] for item in response_json["tree"]]

        ignore_patterns = {
            ".md",
            ".git",
            "LICENSE",
            ".txt",
            ".env",
            "mock",
            "test_data",
            "sample_data",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".zip",
            ".exe",
            ".dll",
            ".bin",
            ".csv",
            ".mp3",
            ".mp4",
        }

        ignore_files = [
            path
            for path in paths
            if any(pattern in path for pattern in ignore_patterns)
        ]

        return ignore_files

    # method to get number of additions and deletions
    def commit_information(self, repo, commit_sha):
        headers = {
                "Authorization": f"token {GITHUB_PAT}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1521.3 Safari/537.36",
            }
        raw_response = asyncio.run(get_commit_information(f"https://api.github.com/repos/Electrium-Mobility/{repo}/commits/{commit_sha}", headers))

        if raw_response.status_code != 200:
            print(f"Error: {raw_response.status_code}")
            return

        parse_response = raw_response.json()

        deleted_lines = parse_response["stats"]["deletions"]
        added_lines = parse_response["stats"]["additions"]

        print(f"Total Number of Deletions are {deleted_lines}.")
        print(f"Total Number of Additions are {added_lines}.")

    # method to remove unimportant lines from diff changes
    def filter_lines(self, lines):
        ignore_prefixes = ("import ", "from ", "#", "'''", '"""')
        return [
            l for l in lines if l.strip() and not l.strip().startswith(ignore_prefixes)
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

        return [
            self.filter_lines(added_lines)[:MAX_LINES],
            self.filter_lines(removed_lines)[:MAX_LINES],
        ]

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
                5. **Generate a Recommendation Score (0–100)** indicating how ready this pull request is for approval, where:
                                - 90–100: Ready to merge (high quality, minimal issues)
                                - 70–89: Acceptable with minor improvements
                                - 50–69: Needs moderate revisions before approval
                                - Below 50: Requires major changes or rework


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

                **Suggestions**
                - Add try/except around API calls
                - Validate environment variables before initialization

                **Recommendation Score**
                - 85
            """

            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
            json={
                    "model": "deepseek-coder",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an experienced code reviewer analyzing Git diffs.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": MAX_TOKEN,
                }
            timeout=30

            response = asyncio.run(analyze_with_ai("https://api.deepseek.com/v1/chat/completions", headers, json, timeout))

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"Error with deepseek: {e}"

    def analyze_diff(self, url):
        headers={"Accept": "application/vnd.github.v3.diff"}
        diffResponse = asyncio.run(get_diff(url, headers))

        diff_text = diffResponse.text
        diff_changes = self.extract_changes(diff_text)
        return self.analyze_with_deepseek(diff_changes)

    @commands.command(name="prreview")
    @commands.cooldown(
        1, 30, commands.BucketType.user
    )  # Add a rate limit to only every 30s
    async def prreview(self, ctx: commands.Context, *, pr_link: str):
        """Placeholder command: accept a PR link and return a placeholder response."""

        print("prreview command called")
        print(f"Received PR link: {pr_link}")

        pattern = r"https://github.com/Electrium-Mobility/([^/]+)/pull/(\d+)"
        match = re.match(pattern, pr_link)
        if match is None:
            await ctx.send(
                "❌ Invalid format for a PR link. Please send a PR from an Electrium-Mobility repo."
            )
            return

        project, pullNumber = match.groups()

        response = asyncio.run(get_pulls(f"https://api.github.com/repos/Electrium-Mobility/{project}/pulls/{pullNumber}"))

        if response.status_code != 200:
            await ctx.send(
                f"Failed to fetch PR details, Please try again different PR link"
            )
        else:
            responseJson = response.json()

            deepseek_response = self.analyze_diff(
                f"https://api.github.com/repos/Electrium-Mobility/{project}/pulls/{pullNumber}"
            )
            
            # Handle case where DEEPSEEK_API_KEY is not set
            if isinstance(deepseek_response, int):  # -1 returned when API key missing
                deepseek_response = "⚠️ AI analysis unavailable (DEEPSEEK_API_KEY not configured)"
            else:
                deepseek_response = (
                    deepseek_response.replace("\\n", "\n").replace("\n**", "\n\n**").strip()
                )

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

    def load_tracked_feeds(self):
        if os.path.exists(STORAGE_PATH):
            try:
                with open(STORAGE_PATH, "r", encoding="utf-8") as f:
                    self.tracked_feeds = json.load(f)
            except Exception:
                self.tracked_feeds = {}
        else:
            self.tracked_feeds = {}

    def save_tracked_feeds(self):
        with open(STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.tracked_feeds, f, indent=2)

    def make_atom_url(self, owner: str, repo: str) -> str:
        return f"https://github.com/{owner}/{repo}/commits.atom"

    def parse_atom_entries(self, xml_text: str) -> list:
        """Return list of entries as dicts with keys id,title,link,updated,author"""
        entries = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            found = root.findall("atom:entry", ns)
            for entry in found:
                eid = entry.find("atom:id", ns).text
                title = entry.find("atom:title", ns).text
                link = entry.find("atom:link", ns).get("href")
                updated = entry.find("atom:updated", ns).text
                author = entry.find("atom:author/atom:name", ns).text
                entries.append(
                    {
                        "id": eid,
                        "title": title,
                        "link": link,
                        "updated": updated,
                        "author": author,
                    }
                )
        except ET.ParseError:
            return []
        return entries

    @commands.command(name="trackrepo", aliases=["track"])
    async def trackrepo(self, ctx: commands.Context, repo: str):
        """Start tracking a repo's commits via its Atom feed.
        Usage: !trackrepo owner/repo or full URL
        Notifications will be sent to the current channel.
        """
        # Accept owner/repo or full github url
        m = re.match(r"^https?://github\.com/([\w-]+)/([\w.-]+)(/)?$", repo)
        if m:
            owner, r = m.group(1), m.group(2)
        else:
            m2 = re.match(r"^([\w-]+)/([\w.-]+)$", repo)
            if not m2:
                await ctx.send(
                    "❌ Please provide a repo as owner/repo or a full GitHub URL."
                )
                return
            owner, r = m2.group(1), m2.group(2)

        key = f"{owner}/{r}"
        atom_url = self.make_atom_url(owner, r)

        # fetch feed once to get latest id
        response = asyncio.run(get_feed(atom_url))

        if response.status_code != 200:
            await ctx.send(
                f"❌ Failed to fetch feed for {key} (HTTP {response.status_code})."
            )
        else:

            entries = self.parse_atom_entries(response.content)
            last_id = entries[0]["id"] if entries else ""

            self.tracked_feeds[key] = {
                "atom_url": atom_url,
                "last_id": last_id,
                "channel_id": ctx.channel.id,
            }
            self.save_tracked_feeds()
            await ctx.send(f"✅ Now tracking commits for {key} in this channel.")

    @commands.command(name="untrackrepo", aliases=["untrack"])
    async def untrackrepo(self, ctx: commands.Context, repo: str):
        """Stop tracking a repo's atom feed."""
        m = re.match(r"^https?://github\.com/([\w-]+)/([\w.-]+)(/)?$", repo)
        if m:
            key = f"{m.group(1)}/{m.group(2)}"
        else:
            m2 = re.match(r"^([\w-]+)/([\w.-]+)$", repo)
            if not m2:
                await ctx.send(
                    "❌ Please provide a repo as owner/repo or a full GitHub URL."
                )
                return
            key = f"{m2.group(1)}/{m2.group(2)}"

        if key in self.tracked_feeds:
            del self.tracked_feeds[key]
            self.save_tracked_feeds()
            await ctx.send(f"✅ Stopped tracking {key}.")
        else:
            await ctx.send("❌ That repository is not being tracked.")

    @commands.command(name="listtrackedrepos", aliases=["listtracked", "tracked"])
    async def listtrackedrepos(self, ctx: commands.Context):
        if not self.tracked_feeds:
            await ctx.send("No feeds are currently tracked.")
            return
        lines = []
        for key, info in self.tracked_feeds.items():
            ch = self.bot.get_channel(info.get("channel_id"))
            ch_text = ch.mention if ch else "unknown channel"
            lines.append(f"{key} → {ch_text}")
        await ctx.send("Tracked feeds:\n" + "\n - ".join(lines))

    @tasks.loop(minutes=1)
    async def poll_atom_feeds(self):
        if not self.tracked_feeds:
            return
        async with aiohttp.ClientSession() as session:
            for key, info in self.tracked_feeds.items():
                atom_url = info.get("atom_url")
                # fetch feed asynchronously using aiohttp
                try:
                    async with session.get(atom_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            continue
                        # decode bytes to string for XML parsing
                        xml_content = await response.text()
                        entries = self.parse_atom_entries(xml_content)
                except Exception as e:
                    print(f"Error fetching feed {key}: {e}")
                    continue

                if not entries:
                    continue

                newest_id = entries[0]["id"]
                last_id = info.get("last_id")
                if last_id == newest_id:
                    continue

                # find new entries up to newest
                new_entries = []
                for e in entries:
                    if e["id"] == last_id:
                        break
                    new_entries.append(e)

                # send notifications oldest-first
                channel = self.bot.get_channel(info.get("channel_id"))
                for e in reversed(new_entries):
                    msg = (
                        f"🔔 New commit in **{key}**\n"
                        f"**Author:** {e.get('author', '')}\n"
                        f"**Message:** {e.get('title', '')}\n"
                        f"[Link to commit]({e.get('link', '')})"
                        # ? Maybe include timestamp of commit
                    )
                    try:
                        if channel:
                            await channel.send(msg)
                        else:
                            # fallback: skip or implement owner DM
                            pass
                    except Exception:
                        pass

                # update last_id to newest
                self.tracked_feeds[key]["last_id"] = newest_id
                self.save_tracked_feeds()


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoPRReviewCog(bot))
