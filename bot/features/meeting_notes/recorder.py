import discord
import logging
import numpy as np
from discord.ext import voice_recv

log = logging.getLogger(__name__)

class CombinedRecorder(voice_recv.AudioSink):
    """AudioSink that receives Opus packets and decodes them into PCM."""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        # Discord sends audio as 48 kHz Opus frames (20 ms, 960 samples)
        self.decoder = opuslib.Decoder(48000, 1)  

    def wants_opus(self) -> bool:
        """Tell Discord that we want Opus-encoded (compressed) audio."""
        return True

    def write(self, user, data):
        """Decode incoming Opus packets and append PCM samples."""
        try:
            if data.opus:
                # Decode Opus frame (960 samples per 20 ms frame at 48 kHz)
                pcm = self.decoder.decode(data.opus, 960, decode_fec=False)
                audio = np.frombuffer(pcm, dtype=np.int16)
                self.cog.audio_buffer.append(audio)
        except opuslib.OpusError as e:
            log.warning(f"Opus decode error from {user}: {e}")
        except Exception as e:
            log.error(f"Unexpected error in write(): {e}")

    def cleanup(self):
        """Called when the sink stops."""
        log.info("CombinedRecorder cleanup complete.")
