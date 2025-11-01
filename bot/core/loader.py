import logging
import pkgutil


logger = logging.getLogger(__name__)


def iter_feature_extensions():
    import bot.features

    for _, name, is_pkg in pkgutil.iter_modules(bot.features.__path__):
        if is_pkg:
            yield f"bot.features.{name}.cog"


async def load_feature_extensions(bot):
    for ext in iter_feature_extensions():
        try:
            await bot.load_extension(ext)
            logger.info(f"Loaded extension: {ext}")
        except Exception as e:
            logger.exception(f"Failed to load extension: {ext}: {e}")