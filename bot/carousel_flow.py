import logging

import httpx
from aiogram import Dispatcher, types


def register_carousel_handlers(dispatcher: Dispatcher, bot, backend_api_url: str, remove_inline_keyboard) -> None:
    pending_edits: dict[str, int] = {}

    async def review(draft_id: int, user_id: str, action: str, text: str | None = None) -> bool:
        try:
            payload = {"action": action}
            if text is not None:
                payload["text"] = text
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{backend_api_url}/carousels/{user_id}/{draft_id}/review",
                    json=payload,
                )
            response.raise_for_status()
            return True
        except Exception as exc:
            logging.error("Failed to review carousel %s: %s", draft_id, exc)
            return False

    @dispatcher.message_handler(commands=["carousel"])
    async def carousel_command(message: types.Message):
        text = (message.get_args() or "").strip()
        if not text:
            await message.reply("Использование: /carousel текст будущей карусели")
            return
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{backend_api_url}/carousels/{message.from_user.id}",
                    json={
                        "master_text": text,
                        "telegram_chat_id": str(message.chat.id),
                        "telegram_reply_message_id": str(message.message_id),
                    },
                )
            response.raise_for_status()
            await message.reply(f"✅ Текст карусели #{response.json()['id']} отправлен на одобрение.")
        except httpx.HTTPStatusError as exc:
            await message.reply(f"❌ Не удалось создать карусель: {exc.response.text[:500]}")
        except Exception:
            logging.exception("Failed to create carousel from Telegram")
            await message.reply("❌ Не удалось создать карусель. Проверьте настройки проекта и шаблоны KARPIX Carousel.")

    @dispatcher.message_handler(lambda message: str(message.from_user.id) in pending_edits)
    async def carousel_edit(message: types.Message):
        user_id = str(message.from_user.id)
        draft_id = pending_edits.pop(user_id, None)
        text = (message.text or "").strip()
        if not draft_id:
            return
        if not text:
            await message.reply("❌ Текст пустой. Нажмите «Изменить» ещё раз и отправьте текст.")
            return
        if await review(draft_id, user_id, "edit", text):
            await message.reply(f"✅ Новый текст карусели #{draft_id} принят. Запускаю генерацию слайдов.")
        else:
            await message.reply("❌ Не удалось сохранить текст карусели. Попробуйте ещё раз.")

    @dispatcher.callback_query_handler(lambda callback: callback.data and callback.data.startswith("carouseltext:"))
    async def carousel_callback(callback: types.CallbackQuery):
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            await callback.answer("Некорректная команда", show_alert=True)
            return
        _, action, draft_id_raw = parts
        try:
            draft_id = int(draft_id_raw)
        except ValueError:
            await callback.answer("Некорректный ID карусели", show_alert=True)
            return
        user_id = str(callback.from_user.id)
        if action == "edit":
            pending_edits[user_id] = draft_id
            await remove_inline_keyboard(callback.message)
            await callback.answer("Отправьте новый текст следующим сообщением")
            await bot.send_message(callback.message.chat.id, f"✏️ Отправьте новый единый текст для карусели #{draft_id}.")
            return
        if action not in {"approve", "reject"}:
            await callback.answer("Некорректное действие", show_alert=True)
            return
        if not await review(draft_id, user_id, action):
            await callback.answer("Не удалось отправить решение", show_alert=True)
            return
        await remove_inline_keyboard(callback.message)
        await callback.answer("Текст одобрен" if action == "approve" else "Карусель отклонена")
        await bot.send_message(
            callback.message.chat.id,
            f"{'✅ Запускаю генерацию слайдов' if action == 'approve' else '🚫 Карусель отклонена'} #{draft_id}.",
        )
