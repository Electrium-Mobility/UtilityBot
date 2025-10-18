import discord
from discord.ext import commands, voice_recv
from openai import OpenAI
import soundfile as sf
import numpy as np
import asyncio
import os
import logging
from dotenv import load_dotenv
from .recorder import CombinedRecorder
import ctypes

log = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

opus_path = r"C:\Users\tanis\Desktop\UtilityBot\bot\library"
os.add_dll_directory(opus_path)
os.environ["PATH"] = opus_path + os.pathsep + os.environ["PATH"]
os.environ["OPUS_LIBRARY"] = os.path.join(opus_path, "opus.dll")

ctypes.cdll.LoadLibrary(os.path.join(opus_path, "opus.dll"))

import opuslib

class CombinedRecorder(voice_recv.AudioSink):
    """AudioSink that receives Opus packets and decodes to PCM."""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.decoder = opuslib.Decoder(48000, 1)  # 1 = mono channel

    def wants_opus(self) -> bool:
        """Tell Discord to send Opus (compressed) audio."""
        return True

    def write(self, user, data):
        """Called when an Opus frame arrives."""
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
        """Optional: clean up resources."""
        pass


class MeetingNotesCog(commands.Cog):
    """Records and transcribes audio from a Discord voice channel."""

    def __init__(self, bot):
        self.bot = bot
        self.vc = None
        self.audio_buffer = []
        super().__init__()

    async def cleanup(self):
        """Combine and save recorded PCM data to WAV."""
        if not self.audio_buffer:
            print("⚠️ No audio data received.")
            return None

        # Combine all recorded chunks
        all_audio = np.concatenate(self.audio_buffer).astype(np.int16)
        sf.write("meeting_audio.wav", all_audio, 48000, subtype="PCM_16")
        print("✅ Audio saved to meeting_audio.wav")
        return "meeting_audio.wav"

    @commands.command(name="record")
    async def record(self, ctx):
        """Join the user's voice channel and start recording."""
        if ctx.author.voice is None:
            return await ctx.send("❌ You must be in a voice channel to use this command.")

        channel = ctx.author.voice.channel
        self.vc = await channel.connect(cls=voice_recv.VoiceRecvClient)

        self.recorder = CombinedRecorder(self)
        self.vc.listen(self.recorder)

        await ctx.send("🎙️ Started recording... use `!stop` to end.")

    @commands.command(name="stop")
    async def stop(self, ctx):
        """Stop recording and transcribe."""
        if not self.vc:
            return await ctx.send("⚠️ I'm not currently recording.")

        await self.vc.disconnect(force=True)
        await ctx.send("🔇 Stopped recording. Processing audio...")

        file_path = await self.cleanup()
        if not file_path:
            return await ctx.send("⚠️ No audio captured.")

        await asyncio.sleep(2)

        try:
            with open(file_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            await ctx.send(f"📝 Transcription:\n```{transcription.text}```")
        except Exception as e:
            await ctx.send(f"❌ Error during transcription: {e}")
            log.error(e)


async def setup(bot):
    await bot.add_cog(MeetingNotesCog(bot))
