from pathlib import Path
from typing import Optional, Union
from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto

async def get_user_avatar_input(bot: Optional[Bot], user_id: int) -> Union[str, FSInputFile, None]:
    """
    Tries to fetch the user's Telegram profile photo.
    Returns the file_id (str) if available, or FSInputFile("img/ava.png") as fallback.
    """
    if bot:
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            if photos and photos.total_count > 0 and photos.photos:
                # Largest size photo is the last element in the list
                return photos.photos[0][-1].file_id
        except Exception:
            pass
    
    fallback_path = Path("img/ava.png")
    if fallback_path.exists():
        return FSInputFile(str(fallback_path))
    return None


async def _send_or_edit_card_photo(
    callback: CallbackQuery,
    photo_input: Union[str, FSInputFile, None],
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None
):
    """
    Renders or edits a card photo message:
    - If the message already has a photo, calls edit_media or edit_caption.
    - If it's a text message or edit fails, deletes old message and sends answer_photo.
    - If photo_input is None, falls back to answer.
    """
    message = callback.message
    has_photo = bool(getattr(message, "photo", None))
    
    if has_photo and photo_input:
        try:
            media = InputMediaPhoto(media=photo_input, caption=caption, parse_mode="HTML")
            await message.edit_media(media=media, reply_markup=reply_markup)
            try:
                await callback.answer()
            except Exception:
                pass
            return
        except Exception:
            pass
        try:
            await message.edit_caption(caption=caption, reply_markup=reply_markup, parse_mode="HTML")
            try:
                await callback.answer()
            except Exception:
                pass
            return
        except Exception:
            pass

    # Якщо повідомлення було текстовим або редагування не вдалося:
    if message:
        try:
            await message.delete()
        except Exception:
            pass

    if photo_input:
        try:
            await message.answer_photo(
                photo=photo_input,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            try:
                await callback.answer()
            except Exception:
                pass
            return
        except Exception:
            pass

    # Фолбек на звичайний текст
    await message.answer(caption, reply_markup=reply_markup, parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass
