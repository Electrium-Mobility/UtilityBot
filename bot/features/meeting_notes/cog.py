import discord
from discord.ext import commands, voice_recv
from openai import OpenAI
import soundfile as sf
import numpy as np
import asyncio
import os
import logging
from dotenv import load_dotenv
import ctypes
from deepgram import DeepgramClient
from pathlib import Path

log = logging.getLogger(__name__)

# Initialize OpenAI client
load_dotenv()

client = OpenAI(api_key=os.environ.get('DEEPSEEK_API_KEY'), base_url="https://api.deepseek.com")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

deepgram = DeepgramClient(api_key=DEEPGRAM_API_KEY)

# Load Opus DLL for audio decoding
opus_path = os.getenv("OPUS_DLL_PATH")

if not opus_path:
    raise EnvironmentError("OPUS_DLL_PATH not set in .env")

opus_dll_path = Path(opus_path)

if not opus_dll_path.exists():
    raise FileNotFoundError(f"Opus DLL not found at {opus_dll_path}")

# Handle platform-specific loading
if os.name == "nt":
    os.add_dll_directory(str(opus_dll_path.parent))
else:
    lib_env = "LD_LIBRARY_PATH" if os.name == "posix" else "DYLD_LIBRARY_PATH"
    os.environ[lib_env] = str(opus_dll_path.parent) + os.pathsep + os.environ.get(lib_env, "")

# Update environment so opuslib can locate it
os.environ["OPUS_LIBRARY"] = str(opus_dll_path)
os.environ["PATH"] = str(opus_dll_path.parent) + os.pathsep + os.environ["PATH"]

ctypes.cdll.LoadLibrary(str(opus_dll_path))

import opuslib

# Decodes incoming Opus audio and stores PCM samples
class CombinedRecorder(voice_recv.AudioSink):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.decoder = opuslib.Decoder(48000, 1)

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data):
        try:
            if data.opus:
                pcm = self.decoder.decode(data.opus, 960, decode_fec=False)
                audio = np.frombuffer(pcm, dtype=np.int16)
                self.cog.audio_buffer.append(audio)
        except opuslib.OpusError as e:
            log.warning(f"Decode error from {user}: {e}")
        except Exception as e:
            log.error(f"Unexpected error decoding audio: {e}")

    def cleanup(self):
        pass


# Cog for meeting notes functionality
class MeetingNotesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vc = None
        self.audio_buffer = []
        super().__init__()

    # Create WAV file from recorded audio
    async def cleanup(self):
        if not self.audio_buffer:
            print("No audio data received.")
            return None

        all_audio = np.concatenate(self.audio_buffer).astype(np.int16)
        sf.write("meeting_audio.wav", all_audio, 48000, subtype="PCM_16")
        print("Audio saved to meeting_audio.wav")
        return "meeting_audio.wav"
    
    # Summarize text using DeepSeek
    async def summarize_text(self, text):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an AI that summarizes multi-speaker meeting transcripts."
                            "Write a concise summary focusing on key topics, decisions, and action items."
                            "Ignore filler words or greetings. Write in a bullet points."
                            "Focus on tasks assigned to each individual and any general descisions made."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                stream=False,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"Error during summarization: {e}")
            return None

    # Command to start recording
    @commands.command(name="record")
    async def record(self, ctx):
        if ctx.author.voice is None:
            return await ctx.send("You must be in a voice channel to use this command.")

        channel = ctx.author.voice.channel
        self.vc = await channel.connect(cls=voice_recv.VoiceRecvClient)

        self.recorder = CombinedRecorder(self)
        self.vc.listen(self.recorder)

        await ctx.send("Started recording... use `!stop` to end.")

    # Command to stop recording and process audio
    @commands.command(name="stop")
    async def stop(self, ctx):
        if not self.vc:
            return await ctx.send("I'm not currently recording.")

        await self.vc.disconnect(force=True)
        await ctx.send("Stopped recording. Processing meeting audio...")

        file_path = await self.cleanup()
        if not file_path:
            return await ctx.send("No audio captured.")

        await asyncio.sleep(2)

        # Transcribe audio using OpenAI Whisper
        try:
            with open(file_path, "rb") as audio_file:
                response = deepgram.listen.v1.media.transcribe_file(
                    request=audio_file.read(),
                    model="nova-3",
                    smart_format=True,
                )
            transcript_text = response.results.channels[0].alternatives[0].transcript
            summary = await self.summarize_text(transcript_text)

            if summary:
                await ctx.send(f"**Meeting Summary:**\n```{summary}```")
            else:
                await ctx.send("Could not generate a summary.")
        except Exception as e:
            await ctx.send(f"Error processing meeting: {e}")
            log.error(e)

        # Clean up audio file
        try:
            await asyncio.sleep(1)
            os.remove(file_path)
            await ctx.send("Cleaned up audio file.")
        except OSError as e:
            log.warning(f"Could not delete audio file: {e}")


async def setup(bot):
    await bot.add_cog(MeetingNotesCog(bot))
