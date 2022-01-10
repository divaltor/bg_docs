import aiogram
import httpx
from aiogram import types, executor
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.exceptions import MessageNotModified
from apscheduler.triggers.cron import CronTrigger
from envparse import env
from lxml import etree
from pytz import utc

import services

env.read_envfile()

bot = aiogram.Bot(token=env.str('TOKEN'), parse_mode='HTML')
storage = RedisStorage2(
    host=env.str('REDIS_HOST'),
    password=env.str('REDIS_PASSWORD', default=None),
    port=env.str('REDIS_PORT'),
    db=1
)
dp = aiogram.Dispatcher(bot, storage=storage)

client = httpx.AsyncClient()

URL = 'https://publicbg.mjs.bg/BgInfo/Home/Enroll'

list_cd = CallbackData('list', 'request_num', 'pin_code')
delete_cd = CallbackData('delete', 'request_num')


async def parse_data(user_id: int, request_number: str, pin_code: str, from_task: bool = True):
    parser = etree.HTMLParser()
    content_page = await client.get(URL)
    tree = etree.fromstring(content_page.content.decode(), parser=parser)

    try:
        token = tree.xpath('//input[@name="__RequestVerificationToken"]')[0].attrib['value']
    except IndexError:
        await bot.send_message(chat_id=user_id, text='Не получилось собрать данные')
        return

    resp = await client.post(URL, data={
        '__RequestVerificationToken': token,
        'reqNum': request_number,
        'pin': pin_code
    })

    tree = etree.fromstring(resp.content.decode(), parser=parser)

    try:
        result = tree.xpath("//*[contains(@class, 'validation-summary-errors')]//li")[0].text
    except IndexError:
        await bot.send_message(chat_id=user_id, text='Не получилось собрать данные')
        return

    if not from_task:
        is_message_sent = await compare_results(user_id, result)

        if not is_message_sent:
            await bot.send_message(chat_id=user_id, text=result)


async def compare_results(user_id: int, result: str):
    fsm_context = FSMContext(storage=storage, chat=user_id, user=user_id)

    user_data = await fsm_context.get_data()

    if not user_data or user_data.get('last_check') != result:
        await bot.send_message(chat_id=user_id, text=result)
        user_data['last_check'] = result
        await fsm_context.set_data(user_data)

        return True

    return False


@dp.message_handler(commands=['list'])
async def handle_list(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    markup = InlineKeyboardMarkup(row_width=1)

    buttons = []

    for num, pin in data.items():
        buttons.append(
            InlineKeyboardButton(num, callback_data=list_cd.new(num, pin))
        )

    if not buttons:
        await msg.answer('Список наблюдения пуст, введите /start для начала')
        return

    markup.add(*buttons)

    await msg.answer('Текущий список наблюдения', reply_markup=markup)


@dp.message_handler(commands=['delete'])
async def handle_delete(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    markup = InlineKeyboardMarkup(row_width=1)

    buttons = []

    for num in data:
        buttons.append(
            InlineKeyboardButton(num, callback_data=delete_cd.new(num))
        )

    if not buttons:
        await msg.answer('Список наблюдения пуст, введите /start для начала')
        return

    markup.add(*buttons)

    await msg.answer('Выберите элемент для удаления', reply_markup=markup)


@dp.callback_query_handler(delete_cd.filter())
async def handle_delete_button(query: types.CallbackQuery, state: FSMContext, callback_data: dict):
    data = await state.get_data()

    request_num = callback_data['request_num']

    if callback_data['request_num'] in data:
        services.apscheduler.remove_job(f'{query.from_user.id}_{request_num}_{data[request_num]}_parse_job')
        del data[callback_data['request_num']]

    await state.set_data(data)

    buttons = []

    markup = InlineKeyboardMarkup()

    for item in data:
        buttons.append(
            InlineKeyboardButton(item, callback_data=delete_cd.new(item))
        )

    if not buttons:
        await query.message.edit_text('Больше нет элементов в списке наблюдения')

    markup.add(*buttons)

    try:
        await query.message.edit_reply_markup(reply_markup=markup)
    except MessageNotModified:
        pass


@dp.callback_query_handler(list_cd.filter())
async def handle_list_button(query: types.CallbackQuery, callback_data: dict):
    await query.message.delete_reply_markup()
    await query.answer()
    await parse_data(query.from_user.id, callback_data['request_num'], callback_data['pin_code'], False)


@dp.message_handler(commands=['check'])
async def handle_check(msg: types.Message):
    args = msg.get_args().split()

    if len(args) != 2:
        await msg.answer('Введите номер запроса и пинкод через пробел, пример: \n\n<code>/check 1111/0000 123456</code>')
        return

    request_number, pin_code, *_ = args

    await parse_data(msg.from_user.id, request_number, pin_code, False)


@dp.message_handler(commands=['start'])
async def handle_start(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    args = msg.get_args().split()

    if len(args) != 2:
        await msg.answer('Введите номер запроса и пинкод через пробел, пример: \n\n<code>/start 1111/0000 123456</code>')
        return

    request_number, pin_code, *_ = args

    if data.get(request_number):
        return await msg.answer('Уже записан')

    job_id = f'{msg.from_user.id}_{request_number}_{pin_code}_parse_job'

    if not services.apscheduler.get_job(job_id):
        cron = CronTrigger(hour=18, minute=0, timezone=utc)
        services.apscheduler.add_job(parse_data, trigger=cron, args=(msg.from_user.id, request_number, pin_code), id=job_id)

    data[request_number] = pin_code
    await state.set_data(data)

    await msg.answer('Записан в очередь')


async def on_startup(_):
    services.setup()


async def on_shutdown(_):
    services.stop()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)