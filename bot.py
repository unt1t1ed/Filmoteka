import asyncio
import html
import logging
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from config import ADMIN_IDS, BOT_TOKEN, BOT_USERNAME, DB_PATH
from database import (
    add_film,
    add_required_channel,
    delete_required_channel,
    get_active_required_channels,
    get_all_required_channels,
    get_film_by_code,
    get_missing_click_channels,
    get_recent_films,
    has_access,
    has_clicked_all_required_channels,
    init_db,
    normalize_code,
    register_channel_click,
    reset_user_access,
    set_user_unlocked,
    upsert_user,
)

logging.basicConfig(level=logging.INFO)

router = Router()


class AddFilmState(StatesGroup):
    waiting_for_title = State()
    waiting_for_year = State()
    waiting_for_genres = State()
    waiting_for_description = State()
    waiting_for_poster_url = State()
    waiting_for_watch_url = State()


class AddChannelState(StatesGroup):
    waiting_for_username = State()
    waiting_for_title = State()
    waiting_for_url = State()
    waiting_for_sort_order = State()
    waiting_for_button_text = State()


class QuickAddFilmState(StatesGroup):
    waiting_for_bulk_text = State()


class UserState(StatesGroup):
    waiting_for_code = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_valid_url(value: str) -> bool:
    value = value.strip()
    return value.startswith("https://") or value.startswith("http://")


def normalize_channel_username(value: str) -> str:
    raw = (value or "").strip()

    raw = raw.replace("https://t.me/", "")
    raw = raw.replace("http://t.me/", "")
    raw = raw.replace("https://telegram.me/", "")
    raw = raw.replace("http://telegram.me/", "")
    raw = raw.replace("t.me/", "")
    raw = raw.replace("telegram.me/", "")
    raw = raw.lstrip("@").strip()

    raw = raw.split("/")[0].strip()
    raw = raw.split("?")[0].strip()

    if not raw:
        return ""

    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", raw):
        return ""

    return raw


def parse_quickadd_text(raw_text: str) -> dict:
    data = {
        "title": "",
        "year": None,
        "genres": "",
        "description": "",
        "poster_url": "",
        "watch_url": "",
    }

    mapping = {
        "название": "title",
        "title": "title",
        "год": "year",
        "year": "year",
        "жанры": "genres",
        "genres": "genres",
        "описание": "description",
        "description": "description",
        "постер": "poster_url",
        "poster": "poster_url",
        "poster_url": "poster_url",
        "ссылка": "watch_url",
        "watch": "watch_url",
        "watch_url": "watch_url",
        "просмотр": "watch_url",
    }

    for line in raw_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        field_name = mapping.get(key)
        if not field_name:
            continue

        if field_name == "year":
            if value == "0" or value == "":
                data["year"] = None
            elif value.isdigit():
                data["year"] = int(value)
            else:
                raise ValueError("Поле 'Год' должно быть числом.")
        else:
            data[field_name] = value

    if not data["title"]:
        raise ValueError("Не заполнено поле 'Название'.")
    if not data["description"]:
        raise ValueError("Не заполнено поле 'Описание'.")
    if not data["poster_url"] or not is_valid_url(data["poster_url"]):
        raise ValueError("Поле 'Постер' должно содержать ссылку с http:// или https://")
    if not data["watch_url"] or not is_valid_url(data["watch_url"]):
        raise ValueError("Поле 'Ссылка' должно содержать ссылку с http:// или https://")

    return data


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Найти фильм по коду")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Нажми кнопку ниже",
    )


def get_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Назад")],
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


def build_required_channels_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows = []

    for channel in channels:
        button_text = (channel.get("button_text") or "").strip()
        if not button_text:
            button_text = f"Перейти в {channel['channel_title']}"

        rows.append(
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"open_channel:{channel['id']}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Продолжить",
                callback_data="continue_after_clicks",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def get_start_text() -> str:
    bot_name = f"@{BOT_USERNAME}" if BOT_USERNAME else "Filmoteka"

    return (
        "Привет.\n\n"
        "Это Filmoteka.\n"
        "Здесь ты можешь найти фильм по коду из Shorts и TikTok.\n\n"
        "Как это работает:\n"
        "1. Увидел код в видео\n"
        "2. Перешел в бота\n"
        "3. Нажал кнопку поиска\n"
        "4. Ввел код\n"
        "5. Получил фильм и ссылку на просмотр\n\n"
        "Код можно вводить в разном виде:\n"
        "FM-0001\n"
        "fm0001\n"
        "fm 0001\n\n"
        f"Если увидел код в видео, просто отправь его в {bot_name}"
    )


def get_unlock_text() -> str:
    return (
        "Перед поиском фильма нужно открыть обязательные каналы ниже.\n\n"
        "После этого нажми «Продолжить».\n"
        "Когда все нужные переходы будут выполнены, доступ откроется автоматически."
    )


def get_quickadd_template() -> str:
    return (
        "Название: Джон Уик\n"
        "Год: 2014\n"
        "Жанры: боевик, триллер, криминал\n"
        "Описание: Бывший наемный убийца возвращается в мир преступности после личной трагедии.\n"
        "Постер: https://site.com/poster.jpg\n"
        "Ссылка: https://site.com/watch"
    )


async def send_main_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        get_start_text(),
        reply_markup=get_main_keyboard(),
    )


async def send_unlock_screen(message: Message, state: FSMContext) -> None:
    await state.clear()

    channels = get_active_required_channels(DB_PATH)

    if not channels:
        await message.answer(
            "Доступ открыт.\n\n"
            "Нажми «Найти фильм по коду» и введи код.",
            reply_markup=get_main_keyboard(),
        )
        return

    await message.answer(
        get_unlock_text(),
        reply_markup=get_back_keyboard(),
    )

    await message.answer(
        "Открой все каналы ниже и потом нажми «Продолжить».",
        reply_markup=build_required_channels_keyboard(channels),
    )


async def send_film_by_code(message: Message, code_text: str) -> None:
    normalized = normalize_code(code_text)
    film = get_film_by_code(DB_PATH, code_text)

    if film is None:
        await message.answer(
            "Фильм по такому коду не найден.\n"
            "Проверь код и отправь еще раз.\n\n"
            "Можно вводить так:\n"
            "FM-0001\n"
            "fm0001\n"
            "fm 0001",
            reply_markup=get_back_keyboard(),
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
    else:
        await message.answer(
            caption,
            reply_markup=keyboard,
        )

    await message.answer(
        f"Код распознан как: {normalized}\n\n"
        "Можешь отправить еще один код или вернуться назад.",
        reply_markup=get_back_keyboard(),
    )


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    upsert_user(
        db_path=DB_PATH,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await send_main_menu(message, state)


@router.message(F.text == "Назад")
async def back_handler(message: Message, state: FSMContext) -> None:
    upsert_user(
        db_path=DB_PATH,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await send_main_menu(message, state)


@router.message(F.text == "Найти фильм по коду")
async def find_film_button_handler(message: Message, state: FSMContext) -> None:
    upsert_user(
        db_path=DB_PATH,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if not has_access(DB_PATH, message.from_user.id):
        await send_unlock_screen(message, state)
        return

    await state.set_state(UserState.waiting_for_code)
    await message.answer(
        "Отправь код фильма.\n\n"
        "Можно так:\n"
        "FM-0001\n"
        "fm0001\n"
        "fm 0001",
        reply_markup=get_back_keyboard(),
    )


@router.callback_query(F.data.startswith("open_channel:"))
async def open_channel_handler(callback: CallbackQuery) -> None:
    user = callback.from_user
    raw_id = callback.data.split(":", 1)[1]

    if not raw_id.isdigit():
        await callback.answer("Ошибка канала.", show_alert=True)
        return

    channel_id = int(raw_id)
    channels = get_active_required_channels(DB_PATH)
    channel = next((item for item in channels if int(item["id"]) == channel_id), None)

    if channel is None:
        await callback.answer("Канал не найден.", show_alert=True)
        return

    register_channel_click(DB_PATH, user.id, channel_id)
    await callback.answer("Переход засчитан.")

    try:
        await callback.message.answer(
            f"Открой канал: {channel['channel_title']}\n{channel['channel_url']}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=(channel.get("button_text") or f"Перейти в {channel['channel_title']}"),
                            url=channel["channel_url"],
                        )
                    ]
                ]
            ),
        )
    except Exception:
        pass


@router.callback_query(F.data == "continue_after_clicks")
async def continue_after_clicks_handler(callback: CallbackQuery, state: FSMContext) -> None:
    user = callback.from_user

    upsert_user(
        db_path=DB_PATH,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if has_clicked_all_required_channels(DB_PATH, user.id):
        set_user_unlocked(DB_PATH, user.id, True)
        await callback.answer("Доступ открыт.")
        try:
            await callback.message.delete()
        except Exception:
            pass

        await callback.message.answer(
            "Готово.\n\n"
            "Доступ открыт.\n"
            "Теперь нажми «Найти фильм по коду» и введи код.",
            reply_markup=get_main_keyboard(),
        )
        return

    missing_channels = get_missing_click_channels(DB_PATH, user.id)
    missing_titles = "\n".join(
        f"• {channel['channel_title']}" for channel in missing_channels[:10]
    )

    await callback.answer("Не все действия выполнены.", show_alert=True)
    await callback.message.answer(
        "Ты еще не открыл все обязательные каналы.\n\n"
        f"Осталось открыть:\n{missing_titles}\n\n"
        "После этого снова нажми «Продолжить».",
        reply_markup=get_back_keyboard(),
    )


@router.message(UserState.waiting_for_code)
async def code_input_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if text == "Назад":
        await send_main_menu(message, state)
        return

    if not text:
        await message.answer(
            "Отправь код фильма.\n\n"
            "Пример: FM-0001",
            reply_markup=get_back_keyboard(),
        )
        return

    upsert_user(
        db_path=DB_PATH,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if not has_access(DB_PATH, message.from_user.id):
        await send_unlock_screen(message, state)
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


@router.message(Command("filmtemplate"))
async def filmtemplate_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    await message.answer(
        "Шаблон для быстрого добавления фильма:\n\n"
        f"<code>{html.escape(get_quickadd_template())}</code>"
    )


@router.message(Command("quickadd"))
async def quickadd_command(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    await state.set_state(QuickAddFilmState.waiting_for_bulk_text)
    await message.answer(
        "Отправь фильм одним сообщением по шаблону ниже.\n\n"
        f"<code>{html.escape(get_quickadd_template())}</code>"
    )


@router.message(QuickAddFilmState.waiting_for_bulk_text)
async def quickadd_handler(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()

    if raw_text == "Назад":
        await send_main_menu(message, state)
        return

    try:
        data = parse_quickadd_text(raw_text)
    except ValueError as exc:
        await message.answer(
            f"Ошибка в шаблоне: {html.escape(str(exc))}\n\n"
            f"<code>{html.escape(get_quickadd_template())}</code>",
            reply_markup=get_back_keyboard(),
        )
        return

    code = add_film(
        db_path=DB_PATH,
        title=data["title"],
        year=data["year"],
        genres=data["genres"],
        description=data["description"],
        poster_url=data["poster_url"],
        watch_url=data["watch_url"],
    )

    await state.clear()

    await message.answer(
        "Фильм добавлен через быстрый режим.\n\n"
        f"Сгенерированный код: <b>{html.escape(code)}</b>\n\n"
        "Теперь этот код можно использовать в видео.",
        reply_markup=get_main_keyboard(),
    )


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
        "Теперь этот код можно использовать в видео.\n"
        "Пользователь сможет ввести его в любом удобном виде: FM-0001, fm0001, fm 0001",
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


@router.message(Command("channels"))
async def channels_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    channels = get_all_required_channels(DB_PATH)

    if not channels:
        await message.answer("Каналов в воронке пока нет.")
        return

    lines = ["Каналы в воронке:\n"]

    for channel in channels:
        status = "active" if int(channel["is_active"]) == 1 else "off"
        lines.append(
            f"ID: {channel['id']} | {channel['channel_title']} | @{channel['channel_username']} | order={channel['sort_order']} | {status}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("delchannel"))
async def delchannel_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    parts = (message.text or "").strip().split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Используй так:\n/delchannel 3\n\n"
            "Сначала посмотри ID через /channels"
        )
        return

    channel_id = int(parts[1])
    deleted = delete_required_channel(DB_PATH, channel_id)

    if not deleted:
        await message.answer("Канал с таким ID не найден.")
        return

    await message.answer(f"Канал с ID {channel_id} удален.")


@router.message(Command("resetme"))
async def resetme_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    reset_user_access(DB_PATH, message.from_user.id)
    await message.answer(
        "Твой unlock и клики сброшены.\n"
        "Теперь можешь заново тестировать воронку."
    )


@router.message(Command("addchannel"))
async def addchannel_command(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    await state.set_state(AddChannelState.waiting_for_username)
    await message.answer(
        "Отправь username канала.\n\n"
        "Можно так:\n"
        "fridovcloud\n"
        "@fridovcloud\n"
        "https://t.me/fridovcloud"
    )


@router.message(AddChannelState.waiting_for_username)
async def addchannel_username_handler(message: Message, state: FSMContext) -> None:
    channel_username = normalize_channel_username(message.text or "")

    if not channel_username:
        await message.answer(
            "Не удалось распознать username канала.\n\n"
            "Отправь в одном из форматов:\n"
            "fridovcloud\n"
            "@fridovcloud\n"
            "https://t.me/fridovcloud"
        )
        return

    await state.update_data(channel_username=channel_username)
    await state.set_state(AddChannelState.waiting_for_title)
    await message.answer(f"Принято: @{channel_username}\n\nТеперь отправь название канала.")


@router.message(AddChannelState.waiting_for_title)
async def addchannel_title_handler(message: Message, state: FSMContext) -> None:
    channel_title = (message.text or "").strip()

    if not channel_title:
        await message.answer("Название канала не может быть пустым.")
        return

    await state.update_data(channel_title=channel_title)
    await state.set_state(AddChannelState.waiting_for_url)
    await message.answer("Отправь ссылку на канал.")


@router.message(AddChannelState.waiting_for_url)
async def addchannel_url_handler(message: Message, state: FSMContext) -> None:
    channel_url = (message.text or "").strip()

    if not is_valid_url(channel_url):
        await message.answer("Ссылка должна начинаться с http:// или https://")
        return

    await state.update_data(channel_url=channel_url)
    await state.set_state(AddChannelState.waiting_for_sort_order)
    await message.answer("Отправь sort order числом. Например: 1")


@router.message(AddChannelState.waiting_for_sort_order)
async def addchannel_sort_handler(message: Message, state: FSMContext) -> None:
    raw_sort = (message.text or "").strip()

    if not raw_sort.isdigit():
        await message.answer("Sort order должен быть числом.")
        return

    await state.update_data(sort_order=int(raw_sort))
    await state.set_state(AddChannelState.waiting_for_button_text)
    await message.answer(
        "Отправь текст для кнопки перехода.\n\n"
        "Пример:\n"
        "Открыть канал\n\n"
        "Если хочешь стандартный текст, отправь: -"
    )


@router.message(AddChannelState.waiting_for_button_text)
async def addchannel_button_text_handler(message: Message, state: FSMContext) -> None:
    button_text = (message.text or "").strip()
    data = await state.get_data()

    if button_text == "-":
        button_text = ""

    add_required_channel(
        db_path=DB_PATH,
        channel_username=data["channel_username"],
        channel_title=data["channel_title"],
        channel_url=data["channel_url"],
        sort_order=int(data["sort_order"]),
        button_text=button_text,
    )

    await state.clear()

    await message.answer(
        "Канал добавлен в click-воронку.\n\n"
        "Теперь доступ будет открываться после обязательных переходов и кнопки «Продолжить».",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("unlockme"))
async def unlockme_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    set_user_unlocked(DB_PATH, message.from_user.id, True)
    await message.answer("Твой доступ отмечен как unlocked.")


@router.message(F.text)
async def code_search_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    upsert_user(
        db_path=DB_PATH,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if text == "Назад":
        await send_main_menu(message, state)
        return

    if not text:
        await message.answer(
            "Отправь код фильма.\n\n"
            "Пример: FM-0001",
            reply_markup=get_back_keyboard(),
        )
        return

    if text.startswith("/"):
        await message.answer("Неизвестная команда.")
        return

    if not has_access(DB_PATH, message.from_user.id):
        await send_unlock_screen(message, state)
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