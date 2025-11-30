from discord.ext import commands
import discord
from io import BytesIO
from typing import List, Optional
import logging
import os
import aiohttp
import json

logger = logging.getLogger("utilitybot.smart_qa")

# Only for testing purposes. Actual document is fetched from Outline API.
def _get_mock_knowledge_document() -> str:
    '''Mock knowledge base. Will be replaced by an actual document in the future.'''
    return (
        "Electrium Mobility is a student design team based at the University of Waterloo. Its goal is to create sustainable and affordable transportation in the form of Personal Electric Vehicles."
        "UtilityBot is a modular Discord bot written in Python using discord.py. "
        "Features are implemented as Cogs and are auto-loaded from bot/features. "
        "The Smart Q&A module answers user questions by consulting relevant notes. "
        "Commands use the '!' prefix (e.g., !qa). Message content intent must be enabled. "
        "Environment variables are provided via a .env file (DISCORD_TOKEN). "
        "Logging is configured through bot/core/logging.py. "
        "To run the bot: activate the venv and execute `python -m bot.main`. "
        "Extensions are discovered and loaded by bot/core/loader.py. "
        "This is a mock knowledge base used only for development without external APIs."
    )

async def _ask_deepseek(question: str, knowledge_document: str) -> Optional[str]:
    """Ask DeepSeek with knowledge context. Returns answer or None on failure."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None

    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer strictly using the provided knowledge. "
                    "If the answer is not present, say: 'I don't know based on the provided knowledge.'"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Knowledge:\n{knowledge_document}\n\n"
                    f"Question:\n{question}\n\n"
                    "Answer in 1-2 concise sentences."
                ),
            },
        ],
    }

    # Standard header
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("DeepSeek API non-200: %s", resp.status)
                    return None

                # Handles none type at each level
                data = await resp.json()
                choices = (data or {}).get("choices") or []
                if not choices:
                    return None
                content = (((choices[0] or {}).get("message") or {}).get("content") or "").strip()

                return content or None
    except Exception:
        logger.exception("DeepSeek API call failed")
        return None


class SmartQACog(commands.Cog):
    """Smart Q&A feature implementation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # get API info
        self.api_url = os.getenv("OUTLINE_API_URL")
        self.api_token = os.getenv("OUTLINE_API_KEY")

    @commands.command(name="qa")
    async def qa(self, ctx: commands.Context, *, question: str):
        """Placeholder command: accept a question and return a placeholder response."""
        await ctx.send(f"Received question: {question}\n(Placeholder response, to be implemented)")

    @commands.command(name="docs")
    async def get_bottom_docs(self, ctx):
        """List bottom-level documents after interactively selecting a collection."""

        # Fetch collections
        collections = await self._fetch_collections() # get all collections
        if not collections: # there are no collections
            return await ctx.send("No collections found.")

        # Display collections
        msg = "**Select a collection by name:**\n"
        for i, c in enumerate(collections, start=1):
            msg += f"{i}. {c['name']}\n" # display "number. title"

        await ctx.send(msg)

        # Wait for user reply
        def check(m):
            # must be same discord user and same channel
            return m.author == ctx.author and m.channel == ctx.channel 

        # give 30 sec time limit for user response
        try:  
            reply = await self.bot.wait_for("message", check=check, timeout=30) 
        except TimeoutError:
            return await ctx.send("Timed out waiting for a response.")

        name = str(reply.content) # user reply (name of collection)
        found = 0
        index = 0
        # Find collection based on name
        for collection in collections:
            if collection['name'] == name:
                found = 1
                break
            index+=1
        
        if not found: # Didn't find collection
            return await ctx.send("Invalid collection name. Please try again.")
        
        selected = collections[index]
        # await ctx.send(f"{index}") # debug
        collection_id = selected["id"]
        collection_name = selected["name"]

        await ctx.send(f"Fetching bottom-level documents from **{collection_name}**...")

        # Fetch documents
        docs = await self._fetch_documents(collection_id) # get all documents inside collection
        
        if not docs: # no documents in collection
            return await ctx.send("No documents found in this collection.")
        
        # Find bottom-level docs and get its full path

        count = len(docs) # number of documents
        
        by_id = {doc["id"]: doc for doc in docs} # dictionary map id to doc (key : value) for each document 
        response = f"**{count} bottom-level documents found in {collection_name}:**\n"
        
        for doc in docs: # get full path of all documents
            response += f"- {self._get_full_path(doc, by_id)}\n"

        await ctx.send(response) # print full path of all documents 

    # Bot command to test _select_collection() returns data.
    @commands.command(name="test_select_collections")
    async def test_select_collections(
        self,
        ctx: commands.Context,
        *,
        question: Optional[str] = None,
    ):
        """Test command for _select_collection function."""
        # Question is mandatory, notify user if missing
        if not question or not question.strip():
            await ctx.send("Error:Please provide a question! Usage: `!test_collections <your question>`")
            return
            
        # Defaults for how many collections to ask the AI for vs display
        match_limit = 3
        result_limit = 1
        
        await ctx.send(
            f"Testing collection selection for: {question}\n"
            f"(match limit: {match_limit}, displaying top {result_limit})\nPlease wait..."
        )
        
        try:
            selected = await self._select_collection(question, match_limit=match_limit, result_limit=result_limit)
            
            if selected:
                response = ["✅ Top collection results:"]
                for i, col in enumerate(selected, 1):
                    response.append(f"{i}. {col}")
                if match_limit > result_limit:
                    response.append(f"(Requested top {result_limit} of {match_limit} max match selections)")
                response = "\n".join(response)
            else:
                response = "❌ No collections selected (empty list returned)"
                
            await ctx.send(response)
        except Exception as e:
            await ctx.send(f"Error: {str(e)}")
            logger.exception("Error in test_collections command")

    # Bot command to test _fetch_collections() returns data.
    @commands.command(name="test_fetch_collections")
    async def test_fetch_collections(self, ctx: commands.Context):
        """Test command to verify _fetch_collections() returns data."""
        await ctx.send("Testing Outline collections API connection... Please wait...")

        if not self.api_url:
            await ctx.send("❌ OUTLINE_API_URL is not set in the environment variables.")
            return

        if not self.api_token:
            await ctx.send("❌ OUTLINE_API_KEY is not set in the environment variables.")
            return

        try:
            collections = await self._fetch_collections()

            if not collections:
                await ctx.send("❌ _fetch_collections returned no data (empty list).")
                return

            response = [f"✅ _fetch_collections succeeded! Found {len(collections)} collection(s)."]
            response.append("Here are the first few:")

            for collection in collections[:5]:
                name = collection.get("name", "Unnamed collection")
                coll_id = collection.get("id", "N/A")
                response.append(f"- **{name}** (ID: `{coll_id}`)")

            if len(collections) > 5:
                response.append(f"...and {len(collections) - 5} more.")

            await ctx.send("\n".join(response))

        except Exception as e:
            await ctx.send(f"❌ Error while calling _fetch_collections: {str(e)}")
            logger.exception("Error in test_fetch_collections command")

    @commands.command(name="test_get_document")
    async def test_get_document(self, ctx: commands.Context, *, document_path: Optional[str] = None):
        """Test command for _find_document_by_path function."""
        # Document path is mandatory, notify user if missing
        if not document_path or not document_path.strip():
            await ctx.send("❌ Please provide a document path! Usage: `!test_get_document <parent - sub - document>`")
            return
        
        await ctx.send(f"🔍 Testing document retrieval for: `{document_path}`\nPlease wait...")
        
        try:
            # Parse the document path
            path_tuple = self._parse_document_path(document_path)
            parent, subparents, doc_name = path_tuple
            
            if not parent or not doc_name:
                await ctx.send(f"❌ Invalid document path format. Expected: `parent - sub - document` or `parent - document`")
                return
            
            # Call the function to get document content
            content = await self._find_document_by_path(path_tuple)
            
            if content:
                # Send document content as text file attachment
                response = f"✅ **Document found!**\n**Path:** `{document_path}`\n**Content length:** {len(content)} characters\n\nSending as file attachment..."
                await ctx.send(response)
                
                # Create and send file
                file = discord.File(
                    BytesIO(content.encode('utf-8')),
                    filename=f"{doc_name.replace(' ', '_')}.txt"
                )
                await ctx.send(file=file)
            else:
                await ctx.send(f"❌ Document not found or has no content.\n**Path:** `{document_path}`")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in test_get_document command")

    async def _fetch_collections(self):
        """Fetch all collections."""
        headers = {"Authorization": f"Bearer {self.api_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.api_url}/collections.list", headers=headers) as resp:
                res = await resp.json()
                return res.get("data", [])

    # Select most relevant collection for a question based on collection names.
    async def _select_collection(self, question: str, match_limit: int = 3, result_limit: int = 1) -> List[str]:
        """
        Uses AI to determine which collections are most likely to contain information helpful for the question.
        Fetches all collections using _fetch_collections() and then uses AI to select the most relevant ones.
        
        Args:
            question: The question to find relevant information for
            match_limit: Maximum number of collection names to request from the AI (>=1)
            result_limit: Number of collection names to return to the user (<= match_limit, >=1)
        
        Returns:
            List of the most relevant collection names (ordered by relevance), or empty list if AI call fails
        """
        match_limit = max(1, match_limit)
        result_limit = max(1, min(result_limit, match_limit))
        
        # Fetch all collections using _fetch_collections()
        collections = await self._fetch_collections()
        if not collections:
            logger.warning("No collections found")
            return []
        
        # Extract collection names from collection objects
        collection_names = [collection.get("name") for collection in collections if collection.get("name")]
        
        if not collection_names:
            logger.warning("No collection names found in collections data")
            return []
        
        if len(collection_names) == 1:
            return collection_names
        
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not set, cannot select relevant collections")
            return []
        
        # Format collection list for AI
        collection_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(collection_names))
        
        # DeepSeek API call.
        # Return JSON object with 'collections' key containing array of collection names
        # in order of relevance (most relevant first), up to match_limit.
        # Return empty list if AI call fails.
        url = "https://api.deepseek.com/v1/chat/completions"
        payload = {
            "model": "deepseek-chat",
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that selects the most relevant collections for a question. "
                        f"You must respond with valid JSON only. Your response must be a JSON object with a 'collections' key "
                        f"containing an array of up to {match_limit} collection names in order of relevance (most relevant first)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"Available collections:\n{collection_list}\n\n"
                        "Which collections are most likely to contain information helpful for answering this question? "
                        f"Respond with at most {match_limit} collection names in a JSON object in this exact format:\n"
                        '{"collections": ["Collection Name 1", "Collection Name 2", "..."]}\n\n'
                        "Use the exact collection names as they appear in the list above."
                    ),
                },
            ],
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning("DeepSeek API non-200 when selecting collections: %s", resp.status)
                        return []
                    
                    data = await resp.json()
                    choices = (data or {}).get("choices") or []
                    if not choices:
                        return []
                    
                    content = (((choices[0] or {}).get("message") or {}).get("content") or "").strip()
                    
                    if not content:
                        return []
                    
                    # Parse JSON response
                    try:
                        response_data = json.loads(content)
                        matched_collections = response_data.get("collections", [])
                        
                        if not matched_collections:
                            logger.warning("AI returned empty collections array in JSON response")
                            return []
                        
                        # Validate that all returned collections exist in the original collection list
                        valid_collections = []
                        for collection_name in matched_collections:
                            # Find matching collection (case-insensitive)
                            for original_collection in collection_names:
                                if original_collection.lower() == collection_name.lower():
                                    if original_collection not in valid_collections:  # Avoid duplicates
                                        valid_collections.append(original_collection)
                                    break
                        
                        if not valid_collections:
                            logger.warning("None of the AI-selected collections matched the original collection list. AI response: %s", content)
                            return []
                        
                        # Limit to requested number of collections (if more were returned)
                        top_collections = valid_collections[:result_limit]
                        logger.info(
                            "Selected %d collection(s) for question '%s': %s",
                            len(top_collections),
                            question,
                            top_collections,
                        )
                        return top_collections
                        
                    except json.JSONDecodeError as e:
                        logger.warning("Failed to parse AI response as JSON: %s. Response: %s", e, content)
                        # Fallback: try to extract collection names from text if JSON parsing fails
                        matched_collections = []
                        for collection_name in collection_names:
                            if collection_name.lower() in content.lower():
                                matched_collections.append(collection_name)
                        
                        if matched_collections:
                            top_collections = matched_collections[:result_limit]
                            logger.info(
                                "Fallback: Selected %d collection(s) using text matching: %s",
                                len(top_collections),
                                top_collections,
                            )
                            return top_collections
                        else:
                            logger.warning("Could not extract collections from AI response, using first collection as fallback")
                            return [collection_names[0]]
                    
        except Exception as e:
            logger.exception("Error selecting relevant collections: %s", e)
            return []

    async def _fetch_documents(self, collection_id):
        """Fetch all documents in a collection (recursively)."""
        headers = {"Authorization": f"Bearer {self.api_token}"}
        data = {"collectionId": collection_id}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.api_url}/documents.list", headers=headers, json=data) as resp:
                res = await resp.json()
                return res.get("data", [])
    
    def _get_full_path(self, doc, by_id):
        """Gets full path of document, separated by '/'"""
        parts = [doc.get("title")] # get title of each document and store in array `parts`
        parent_id = doc.get("parentDocumentId") # get parent id of each document
        
        while parent_id: # while we havent reached root
            parent = by_id.get(parent_id) # find curr document's parent using id 
                                          # (pass parent_id as key in by_id)
            parts.append(parent["title"]) # add title of parent to path
            parent_id = parent.get("parentDocumentId") # set new parent id as the parent_id 
                                                       # of curr document

        parts.reverse() # reverse titles (path is from root to document, but its the other way
                        # around since we found it recursively)

        return "/".join(parts) # join titles with '/', then return it

    # Returns: the path of the document as a tuple. The last element is the document name.
    def _parse_document_path(self, full_name: str) -> tuple[str, list[str], str]:
        """
        Parses document name format with variable depth:
        "parent - sub1 - sub2 - sub3 - ... - document"
        "parent - document"
        
        Returns: (parent_collection, [sub_collections...], document_name)
        """
        if not full_name or not full_name.strip():
            return "", [], ""
        parts = [part.strip() for part in full_name.split(" - ")]
        # Check for empty parts (invalid path)
        if any(not part for part in parts):
            return "", [], ""
        # parent - document
        if len(parts) == 2:
            return parts[0], [], parts[1]
        # parent - sub1 - sub2 - ... - document
        elif len(parts) > 2:
            return parts[0], parts[1:-1], parts[-1]
        else:
            return "", [], ""

    def _verify_document_path(self, doc: dict, subparents: list[str], by_id: dict) -> bool:
        """
        Verify that a document's hierarchical path matches the expected subparents.
        
        Args:
            doc: The document to verify
            subparents: List of expected parent document names in order (closest to root first)
            by_id: Dictionary mapping document IDs to document objects
        
        Returns:
            True if the document's path matches the expected subparents, False otherwise
        """
        # Build the document's actual parent path by traversing parentDocumentId
        actual_path = []
        parent_id = doc.get("parentDocumentId")
        
        while parent_id:
            parent_doc = by_id.get(parent_id)
            if not parent_doc:
                logger.debug(f"Parent document ID '{parent_id}' not found in collection - possible data inconsistency")
                break
            actual_path.append(parent_doc.get("title", "").strip())
            parent_id = parent_doc.get("parentDocumentId")
        
        # Reverse to get root-to-document order (actual_path is built from doc to root)
        actual_path.reverse()
        
        # Compare expected subparents with actual path (case-insensitive)
        if len(subparents) != len(actual_path):
            return False
        
        for expected, actual in zip(subparents, actual_path):
            if expected.strip().lower() != actual.lower():
                return False
        
        return True

        
    async def _find_document_by_path(self, path: tuple[str, list[str], str]) -> Optional[str]:
        """
        Find a document by matching its title and hierarchical path in the specified collection.
        
        Args:
            path: Tuple of (parent_collection_name, [sub_collections...], document_name)
        
        Returns:
            Document content as string, or None if not found.
            Note: If multiple documents match the path (unlikely in well-structured collections),
            only the first matching document's content is returned.
        """
        parent_name = path[0]
        subparents = path[1]
        doc_name = path[2]

        # Step 1: Find the parent collection (case-insensitive)
        collections = await self._fetch_collections()
        parent_collection = None
        parent_name_lower = parent_name.strip().lower()
        for collection in collections:
            if collection.get("name", "").strip().lower() == parent_name_lower:
                parent_collection = collection
                break

        if not parent_collection:
            logger.warning(f"Collection '{parent_name}' not found")
            return None

        collection_id = parent_collection.get("id")

        # Step 2: Fetch all documents in the collection
        docs = await self._fetch_documents(collection_id)
        if not docs:
            logger.warning(f"No documents found in collection '{parent_name}'")
            return None

        # Build a dictionary to look up documents by ID for path verification
        by_id = {doc["id"]: doc for doc in docs}

        # Step 3: Match the document by title and verify hierarchical path
        target_doc = None
        doc_name_lower = doc_name.strip().lower()
        
        for doc in docs:
            if doc.get('title', '').strip().lower() == doc_name_lower:
                # Verify the document's hierarchical path matches the subparents
                if self._verify_document_path(doc, subparents, by_id):
                    target_doc = doc
                    break

        if not target_doc:
            # Log available document titles for debugging
            available_titles = [doc.get('title', 'Untitled') for doc in docs[:10]]
            logger.warning(
                f"Document '{doc_name}' not found in collection '{parent_name}' with path {subparents}. "
                f"Available documents (first 10): {available_titles}"
            )
            return None

        # Step 4: Fetch document content
        document_id = target_doc["id"]
        headers = {"Authorization": f"Bearer {self.api_token}"}
        data = {"id": document_id}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/documents.info", headers=headers, json=data) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        doc_data = res.get("data", {})

                        # Try different possible content fields
                        content = (
                            doc_data.get("text") or
                            doc_data.get("content") or
                            doc_data.get("body") or
                            doc_data.get("markdown") or
                            ""
                        )

                        if content:
                            logger.info(f"Successfully fetched document '{doc_name}' from collection '{parent_name}' ({len(content)} chars)")
                            return content
                        else:
                            logger.warning(f"Document '{doc_name}' found but has no content. Available fields: {list(doc_data.keys())}")
                            return None
                    else:
                        error_text = await resp.text()
                        logger.warning(f"Failed to fetch document content: HTTP {resp.status} - {error_text}")
                        return None

        except Exception as e:
            logger.exception(f"Error fetching document content: {e}")
            return None



async def setup(bot: commands.Bot):
    await bot.add_cog(SmartQACog(bot))