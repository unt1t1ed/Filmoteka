import asyncio
import html
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import ADMIN_IDS, BOT_TOKEN, BOT_USERNAME, DB_PATH
from database import add_film, get_film_by_code, get_recent_films, init_db

logging.basicConfig(level=logging.INFO)

router = Router()


class AddFilmState(StatesGroup):
    waiting_for_title = State()
    waiting_for_year = State()
    waiting_for_genres = State()
    waiting_for_description = State()
    waiting_for_poster_url = State()
    waiting_for_watch_url = State()


class UserState(StatesGroup):
    waiting_for_code = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_valid_url(value: str) -> bool:
    value = value.strip()
    return value.startswith("https://") or value.startswith("http://")


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Найти фильм по коду")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Нажми кнопку ниже",
    )


def build_watch_keyboard(watch_url: str) -> Optional[InlineKeyboardMarkup]:
    watch_url = (watch_url or "").strip()

    if not watch_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к просмотру", url=watch_url)]
        ]
    )


def format_film_caption(film: dict) -> str:
    title = html.escape(film["title"])
    code = html.escape(film["code"])
    year = film["year"] if film["year"] else "—"
    genres = html.escape(film["genres"] or "—")
    description = html.escape(film["description"] or "Без описания.")

    return (
        f"<b>{title}</b>\n\n"
        f"<b>Код:</b> {code}\n"
        f"<b>Год:</b> {year}\n"
        f"<b>Жанры:</b> {genres}\n\n"
        f"<b>Описание:</b>\n{description}"
    )


async def send_film_by_code(message: Message, code_text: str) -> None:
    film = get_film_by_code(DB_PATH, code_text)

    if film is None:
        await message.answer(
            "Фильм по такому коду не найден.\n"
            "Проверь код и отправь еще раз.\n\n"
            "Пример: FM-0001",
            reply_markup=get_main_keyboard(),
        )
        return

    caption = format_film_caption(film)
    keyboard = build_watch_keyboard(film.get("watch_url", ""))
    poster_url = (film.get("poster_url") or "").strip()

    if poster_url:
        await message.answer_photo(
            photo=poster_url,
            caption=caption,
            reply_markup=keyboard,
        )
        return

    await message.answer(
        caption,
        reply_markup=keyboard,
    )


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()

    bot_name = f"@{BOT_USERNAME}" if BOT_USERNAME else "Filmoteka"

    text = (
        "Привет.\n\n"
        "Это Filmoteka.\n"
        "Здесь ты можешь найти фильм по коду из Shorts или TikTok.\n\n"
        "Как это работает:\n"
        "1. Попался шортс\n"
        "2. Увидел код фильма\n"
        "3. Перешел в бота\n"
        "4. Нажал кнопку поиска\n"
        "5. Ввел код и получил ссылку на просмотр\n\n"
        "Пример кода: FM-0001\n"
        f"Если увидел код в видео, просто отправь его в {bot_name}"
    )

    await message.answer(
        text,
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == "Найти фильм по коду")
async def find_film_button_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(UserState.waiting_for_code)
    await message.answer(
        "Отправь код фильма.\n\n"
        "Пример: FM-0001",
        reply_markup=get_main_keyboard(),
    )


@router.message(UserState.waiting_for_code)
async def code_input_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if not text:
        await message.answer(
            "Отправь код фильма.\n\n"
            "Пример: FM-0001",
            reply_markup=get_main_keyboard(),
        )
        return

    await state.clear()
    await send_film_by_code(message, text)


@router.message(Command("addfilm"))
async def addfilm_command(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    await state.set_state(AddFilmState.waiting_for_title)
    await message.answer("Отправь название фильма.")


@router.message(AddFilmState.waiting_for_title)
async def addfilm_title_handler(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()

    if not title:
        await message.answer("Название не может быть пустым. Отправь название фильма.")
        return

    await state.update_data(title=title)
    await state.set_state(AddFilmState.waiting_for_year)
    await message.answer("Отправь год. Если не нужен, отправь 0.")


@router.message(AddFilmState.waiting_for_year)
async def addfilm_year_handler(message: Message, state: FSMContext) -> None:
    raw_year = (message.text or "").strip()

    if not raw_year.isdigit():
        await message.answer("Год должен быть числом. Например: 2014 или 0.")
        return

    year_num = int(raw_year)
    year_value = None if year_num == 0 else year_num

    await state.update_data(year=year_value)
    await state.set_state(AddFilmState.waiting_for_genres)
    await message.answer("Отправь жанры. Пример: боевик, триллер, криминал")


@router.message(AddFilmState.waiting_for_genres)
async def addfilm_genres_handler(message: Message, state: FSMContext) -> None:
    genres = (message.text or "").strip()

    await state.update_data(genres=genres)
    await state.set_state(AddFilmState.waiting_for_description)
    await message.answer("Отправь короткое описание фильма.")


@router.message(AddFilmState.waiting_for_description)
async def addfilm_description_handler(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()

    await state.update_data(description=description)
    await state.set_state(AddFilmState.waiting_for_poster_url)
    await message.answer(
        "Теперь отправь ссылку на обложку фильма.\n\n"
        "Пример:\n"
        "https://site.com/poster.jpg"
    )


@router.message(AddFilmState.waiting_for_poster_url)
async def addfilm_poster_handler(message: Message, state: FSMContext) -> None:
    poster_url = (message.text or "").strip()

    if not is_valid_url(poster_url):
        await message.answer(
            "Ссылка на обложку должна начинаться с http:// или https://"
        )
        return

    await state.update_data(poster_url=poster_url)
    await state.set_state(AddFilmState.waiting_for_watch_url)
    await message.answer(
        "Теперь отправь одну главную ссылку для просмотра.\n\n"
        "Именно она будет открываться по кнопке.\n\n"
        "Пример:\n"
        "https://site.com/watch"
    )


@router.message(AddFilmState.waiting_for_watch_url)
async def addfilm_watch_handler(message: Message, state: FSMContext) -> None:
    watch_url = (message.text or "").strip()

    if not is_valid_url(watch_url):
        await message.answer(
            "Ссылка для просмотра должна начинаться с http:// или https://"
        )
        return

    data = await state.get_data()

    code = add_film(
        db_path=DB_PATH,
        title=data["title"],
        year=data.get("year"),
        genres=data.get("genres", ""),
        description=data.get("description", ""),
        poster_url=data.get("poster_url", ""),
        watch_url=watch_url,
    )

    await state.clear()

    await message.answer(
        "Фильм добавлен.\n\n"
        f"Сгенерированный код: <b>{html.escape(code)}</b>\n\n"
        "Теперь этот код можно использовать в видео.",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("recent"))
async def recent_handler(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    films = get_recent_films(DB_PATH, limit=10)

    if not films:
        await message.answer("Фильмов пока нет.")
        return

    lines = ["Последние фильмы:\n"]

    for film in films:
        title = film["title"]
        code = film["code"]
        year = film["year"] if film["year"] else "—"
        lines.append(f"{code} | {title} | {year}")

    await message.answer("\n".join(lines))


@router.message(F.text)
async def code_search_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if not text:
        await message.answer(
            "Отправь код фильма.\n\n"
            "Пример: FM-0001",
            reply_markup=get_main_keyboard(),
        )
        return

    if text.startswith("/"):
        await message.answer("Неизвестная команда.")
        return

    await state.clear()
    await send_film_by_code(message, text)


async def main() -> None:
    init_db(DB_PATH)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())