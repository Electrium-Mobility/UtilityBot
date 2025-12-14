from urllib import request
from discord.ext import tasks, commands
import aiohttp
import aiofiles
import xml.etree.ElementTree as ET
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
    async def ignore_files(self, repo):

        headers={
                "Authorization": f"token {GITHUB_PAT}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1521.3 Safari/537.36",
            }
        raw_response = await get_file_paths(f"https://api.github.com/repos/Electrium-Mobility/{repo}/git/trees/main?recursive=1", headers)

        if raw_response.status != 200:
            print(f"Error: {raw_response.status}")
            return

        response_json = await raw_response.json()

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
    async def commit_information(self, repo, commit_sha):
        headers = {
                "Authorization": f"token {GITHUB_PAT}",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1521.3 Safari/537.36",
            }
        raw_response = await get_commit_information(f"https://api.github.com/repos/Electrium-Mobility/{repo}/commits/{commit_sha}", headers)

        if raw_response.status != 200:
            print(f"Error: {raw_response.status}")
            return

        parse_response = await raw_response.json()

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

    async def analyze_with_deepseek(self, changes):
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

            response = await analyze_with_ai("https://api.deepseek.com/v1/chat/completions", headers, json, timeout)

            data = await response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"Error with deepseek: {e}"

    async def analyze_diff(self, url):
        headers={"Accept": "application/vnd.github.v3.diff"}
        diffResponse = await get_diff(url, headers)

        diff_text = await diffResponse.text()
        diff_changes = self.extract_changes(diff_text)
        return await self.analyze_with_deepseek(diff_changes)

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

        response = await get_pulls(f"https://api.github.com/repos/Electrium-Mobility/{project}/pulls/{pullNumber}")

        if response.status != 200:
            await ctx.send(
                f"Failed to fetch PR details, Please try again different PR link"
            )
        else:
            responseJson = await response.json()

            deepseek_response = await self.analyze_diff(
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

            # record contributor statistics (additions, deletions, and author)
            author = responseJson['user']['login']
            additions = responseJson['additions']
            deletions = responseJson['deletions']
            await self.update_contributor_stats(author, additions, deletions, project)

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

    async def load_tracked_feeds(self):
        # load tracked feeds from storage.
        if os.path.exists(STORAGE_PATH):
            try:
                async with aiofiles.open(STORAGE_PATH, "r", encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                    # backward compatibility
                    if isinstance(data, dict):
                        self.tracked_feeds = data.get("feeds", data)
                        self.contributor_stats = data.get("contributors", {})
                    else:
                        self.tracked_feeds = {}
                        self.contributor_stats = {}
            except Exception:
                self.tracked_feeds = {}
                self.contributor_stats = {}
        else:
            self.tracked_feeds = {}
            self.contributor_stats = {}

    async def save_tracked_feeds(self):
        # save tracked feeds to storage 
        data = {
            "feeds": self.tracked_feeds,
            "contributors": self.contributor_stats
        }
        async with aiofiles.open(STORAGE_PATH, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2))

    async def update_contributor_stats(self, author: str, additions: int, deletions: int, repo: str = None):
        # update contributor statistics with lines changed
        if author not in self.contributor_stats:
            self.contributor_stats[author] = {
                "total_additions": 0,
                "total_deletions": 0,
                "total_changes": 0,
                "pr_count": 0,
                "repos": {}
            }
        
        # update overall stats
        self.contributor_stats[author]["total_additions"] += additions
        self.contributor_stats[author]["total_deletions"] += deletions
        self.contributor_stats[author]["total_changes"] += (additions + deletions)
        self.contributor_stats[author]["pr_count"] += 1
        
        # update per-repo stats if repo is provided
        if repo:
            if repo not in self.contributor_stats[author]["repos"]:
                self.contributor_stats[author]["repos"][repo] = {
                    "additions": 0,
                    "deletions": 0,
                    "changes": 0,
                    "pr_count": 0
                }
            self.contributor_stats[author]["repos"][repo]["additions"] += additions
            self.contributor_stats[author]["repos"][repo]["deletions"] += deletions
            self.contributor_stats[author]["repos"][repo]["changes"] += (additions + deletions)
            self.contributor_stats[author]["repos"][repo]["pr_count"] += 1
        
        await self.save_tracked_feeds()

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
        """Start tracking a repo's commits from Electrium-Mobility Github via its Atom feed.
        Usage: !trackrepo repo or full URL
        Notifications will be sent to the current channel.
        """

        # Accept repo or full github url
        m = re.match(r"^https?://github\.com/Electrium-Mobility/([\w-]+)(/)?$", repo)
        if m:
            r = m.group(1)
        else:
            m2 = re.match(r"([\w.-]+)$", repo)
            if not m2:
                await ctx.send(
                    "❌ Please provide a repo name or a full GitHub URL."
                )
                return
            r = m2.group(1)

        key = f"Electrium-Mobility/{r}"
        atom_url = f"https://github.com/Electrium-Mobility/{r}/commits.atom"

        # fetch feed once to get latest id
        response = await get_feed(atom_url)

        if response.status != 200:
            await ctx.send(
                f"❌ Failed to fetch feed for {key} (HTTP {response.status})."
            )
        else:

            content = await response.text()
            entries = self.parse_atom_entries(content)
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
        # Accept repo or full github url
        m = re.match(r"^https?://github\.com/Electrium-Mobility/([\w-]+)(/)?$", repo)
        if m:
            r = m.group(1)
        else:
            m2 = re.match(r"([\w.-]+)$", repo)
            if not m2:
                await ctx.send(
                    "❌ Please provide a repo name or a full GitHub URL."
                )
                return
            r = m2.group(1)

        key = f"Electrium-Mobility/{r}"

        if key in self.tracked_feeds:
            del self.tracked_feeds[key]
            self.save_tracked_feeds()
            await ctx.send(f"✅ Stopped tracking `{key}`.")
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

    @commands.command(name="contributorstats", aliases=["stats", "contributors"])
    async def contributorstats(self, ctx: commands.Context, contributor: str = None):
        # Display stats for contributors showing lines changed.
        # If no username is provided, shows stats for all contributors.
        if not self.contributor_stats:
            await ctx.send("No contributor statistics available yet.")
            return
        
        if contributor:
            # show stats for specific contributor
            if contributor not in self.contributor_stats:
                await ctx.send(f"No statistics found for contributor `{contributor}`.")
                return
            
            stats = self.contributor_stats[contributor]
            repo_lines = []
            for repo, repo_stats in stats["repos"].items():
                repo_lines.append(
                    f"  • `{repo}`: {repo_stats['changes']:,} lines "
                    f"(+{repo_stats['additions']:,} / -{repo_stats['deletions']:,}), "
                    f"{repo_stats['pr_count']} PR{'s' if repo_stats['pr_count'] != 1 else ''}"
                )
            
            repo_breakdown = "\n".join(repo_lines) if repo_lines else "  No repository data"
            
            await ctx.send(
                f"**Contributor Statistics for `{contributor}`**\n\n"
                f"**Total Lines Changed:** {stats['total_changes']:,}\n"
                f"**Lines Added:** +{stats['total_additions']:,}\n"
                f"**Lines Deleted:** -{stats['total_deletions']:,}\n"
                f"**Pull Requests:** {stats['pr_count']}\n\n"
                f"**Per Repository:**\n{repo_breakdown}"
            )
        else:
            # show stats for all contributors (sorted by total changes)
            sorted_contributors = sorted(
                self.contributor_stats.items(),
                key=lambda x: x[1]["total_changes"],
                reverse=True
            )
            
            lines = []
            for username, stats in sorted_contributors[:10]:
                lines.append(
                    f"**{username}**: {stats['total_changes']:,} lines changed "
                    f"(+{stats['total_additions']:,} / -{stats['total_deletions']:,}), "
                    f"{stats['pr_count']} PR{'s' if stats['pr_count'] != 1 else ''}"
                )
            
            total_contributors = len(self.contributor_stats)
            footer = ""
            if total_contributors > 10:
                footer = f"\n\n*Showing top 10 of {total_contributors} contributors. Use `!contributorstats <username>` for individual stats.*"
            
            await ctx.send(
                f"**Contributor Statistics**\n\n"
                + "\n".join(lines)
                + footer
            )

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
                    print(f"Error fetching feed `{key}`: {e}")
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
                        f"🔔 New commit in `{key}`\n"
                        f"**Author:** {e.get('author', '')}\n"
                        f"**Message:** {e.get('title', '')}\n"
                        f"[Link to commit]({e.get('link', '')})"
                    )

                    # analyze commit information with deepseek
                    deepseek_response = self.analyze_diff(e.get('link', ''))

                    # handle case where DEEPSEEK_API_KEY is not set
                    if isinstance(deepseek_response, int):  # -1 returned when API key missing
                        deepseek_response = "⚠️ AI analysis unavailable (DEEPSEEK_API_KEY not configured)"
                    else:
                        deepseek_response = (
                            deepseek_response.replace("\\n", "\n").replace("\n**", "\n\n**").strip()
                        )

                    try:
                        if channel:
                            await channel.send(msg)
                            await channel.send(deepseek_response)
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
