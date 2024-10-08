import asyncio
from datetime import datetime
from random import randint, choices
from time import time
from urllib.parse import unquote, quote

import aiohttp
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.types import InputBotAppShortName

from typing import Callable
import functools
from tzlocal import get_localzone
from bot.config import settings
from bot.exceptions import InvalidSession
from bot.utils import logger
from .agents import generate_random_user_agent
from .headers import headers
from .profiles import profiles

def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
    return wrapper

def convert_to_local_and_unix(iso_time):
    dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
    local_dt = dt.astimezone(get_localzone())
    unix_time = int(local_dt.timestamp())
    return unix_time

class Tapper:
    def __init__(self, tg_client: Client, proxy: str | None):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.proxy = proxy

    async def get_tg_web_data(self) -> str:
        import json
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('Agent301Bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 3)
            
            ref_id = choices([settings.REF_ID, "onetime6451244166"], weights=[85, 15], k=1)[0]
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="app"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            tg_web_data_parts = tg_web_data.split('&')
            user = json.loads(tg_web_data_parts[0].split('=')[1])
            init_data = (f"user={user["id"]}")
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return ref_id, init_data

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)
            return None, None

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://api.agent301.org{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        return await response.json()

    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        ip = response.get('origin')
        logger.info(f"{self.session_name} | Proxy IP: {ip}")

    @error_handler
    async def get_balance(self, http_client, ref_id: str):
        return await self.make_request(http_client, "POST", "/getMe", json={"referrer_id": ref_id})
    
    @error_handler
    async def get_tasks(self, http_client):
        return await self.make_request(http_client, "POST", "/getTasks", json={'language_code': 'en'})

    @error_handler
    async def complete_task(self, http_client, task_type: str, task_title: str, current_count=0, max_count=1):
        response = await self.make_request(http_client, "POST", "/completeTask", json={"type": task_type})
        if 'ok' in response and response['ok']:
            result = response['result']
            logger.success(f"{self.session_name} | Làm nhiệm vụ {task_title} {current_count + 1}/{max_count} thành công | Phần thưởng {result['reward']} | Balance {result['balance']}")
            return result
        else:
            logger.error(f"{self.session_name} | Có lỗi khi làm nhiệm vụ!")

    @error_handler
    async def handle_task(self, http_client):
        response = await self.get_tasks(http_client=http_client)
        if 'ok' in response and response['ok']:
            tasks = response['result']['data']
            unclaimed_tasks = [task for task in tasks if (not task['is_claimed']) and (task['type'] not in ['nomis2', 'boost', 'invite_3_friends', 'transaction', 'stars_purchase'])]

            if len(unclaimed_tasks) == 0:
                logger.warning(f"{self.session_name} | Không tìm thấy nhiệm vụ!")
                return
            
            for task in tasks:
                remaining_count = (task['max_count'] - task['count']) if task['max_count'] > 0 else 1
                i = 0
                while i < remaining_count:
                    await self.complete_task(http_client=http_client, task_type=task['type'], task_title=task['title'], current_count=i, max_count=remaining_count)
                    await asyncio.sleep(delay=10)
                    i=i+1
        else:
            logger.error(f"{self.session_name} | Có lỗi khi lấy danh sách nhiệm vụ!")
        return

    @error_handler
    async def spin_wheel(self, http_client):
        response = await self.make_request(http_client, "POST", "/wheel/spin")
        if 'ok' in response and response['ok']:
            result = response['result']
            logger.success(f"{self.session_name} | Spin thành công: nhận được {result['reward']}")
            logger.info(f"{self.session_name} | * Balance : {result['balance']}")
            logger.info(f"{self.session_name} | * Toncoin : {result['toncoin']}")
            logger.info(f"{self.session_name} | * Notcoin : {result['notcoin']}")
            logger.info(f"{self.session_name} | * Tickets : {result['tickets']}")
        else:
            logger.error(f"{self.session_name} | Quay bị lỗi")
        return

    @error_handler
    async def spin_all_tickets(self, http_client, tickets):
        while tickets > 0:
            result = await self.spin_wheel(http_client=http_client)
            if 'ok' in result and result['ok']:
                tickets = result['tickets']
            else:
                logger.error(f"{self.session_name} | Có lỗi xảy ra, không thể thực hiện xoay vòng quay!")
            await asyncio.sleep(delay=5)
        logger.info(f"{self.session_name} | Đã sử dụng hết tickets.")
        return

    @error_handler
    async def wheel_load(self, http_client):
        return await self.make_request(http_client, "POST", "/wheel/load")

    @error_handler
    async def get_wheel_task(self, http_client, wheel_task_type: str):
        return await self.make_request(http_client, "POST", "/wheel/task", json={ "type": wheel_task_type })

    @error_handler
    async def handle_wheel_tasks(self, http_client):
        logger.info(f"{self.session_name} | Load vòng quay...")
        wheel_data = await self.wheel_load(http_client=http_client)
        current_timestamp = round(time())

        if 'ok' in wheel_data:
            logger.info(f"{self.session_name} | Start to work daily tasks!")
            if current_timestamp > wheel_data['result']['tasks']['daily']:
                daily_result = await self.get_wheel_task(http_client=http_client, wheel_task_type='daily')
                if 'ok' in daily_result:
                    next_daily = datetime.utcfromtimestamp(wheel_data['result']['tasks']['daily'])
                    logger.success(f"{self.session_name} | Claim daily ticket thành công. Lần claim tiếp theo: {next_daily}")
                    wheel_data = daily_result
            else:
                next_daily = datetime.utcfromtimestamp(wheel_data['result']['tasks']['daily'])
                logger.info(f"{self.session_name} | Thời gian claim daily ticket tiếp theo: {next_daily}")

            if not wheel_data['result']['tasks']['bird']:
                logger.info(f"{self.session_name} | Start to work task that type is bird!")
                bird_result = await self.get_wheel_task(http_client=http_client, wheel_task_type='bird')
                if 'ok' in bird_result:
                    logger.success(f"{self.session_name} | Làm nhiệm vụ ticket bird thành công")
                    wheel_data = bird_result

            logger.info(f"{self.session_name} | Start to work the hourly task!")
            hour_count = wheel_data['result']['tasks']['hour']['count']
            while (hour_count < 5) and (current_timestamp > wheel_data['result']['tasks']['hour']['timestamp']):
                hour_result = await self.get_wheel_task(http_client=http_client, wheel_task_type='hour')
                if ('ok' in hour_result):
                    hour_count = hour_result['result']['tasks']['hour']['count']
                    logger.success(f"{self.session_name} | Làm nhiệm vụ hour thành công.")
                    wheel_data = hour_result

            if (hour_count == 0) and (current_timestamp < wheel_data['result']['tasks']['hour']['timestamp']):
                next_hour = datetime.utcfromtimestamp(wheel_data['result']['tasks']['hour']['timestamp'])
                logger.info(f"{self.session_name} | Thời gian xem video claim ticket tiếp theo: {next_hour}")

        return

    async def run(self) -> None:        
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(f"{self.tg_client.name} | Bot will start in <light-red>{random_delay}s</light-red>")
            await asyncio.sleep(delay=random_delay)
        
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

        # ``
        # Blum Farming Bot
        # ``
        end_farming_dt = 0
        token_expiration = 0
        tickets = 0
        next_stars_check = 0
        next_combo_check = 0
        
        while True:
            try:
                # set up proxy and client session
                logger.warning(f"{self.session_name} | Set up proxy and Client Session!")
                http_client.headers["Authorization"] = f"{profiles[self.session_name]['query']}"
                if http_client.closed:
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
                    if settings.FAKE_USERAGENT:            
                        http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

                # Start farming
                logger.warning(f"{self.session_name} | Get go!")
                await asyncio.sleep(delay=1)

                ## get user balance
                user_info = await self.get_balance(http_client=http_client, ref_id=profiles[self.session_name]['ref_id'])
                if 'ok' in user_info and user_info['ok']:
                    logger.info(f"{self.session_name} | Balance: {user_info['result']['balance']}")
                    logger.info(f"{self.session_name} | Tickets: {user_info['result']['tickets']}")

                    await self.handle_task(http_client=http_client)
                    await self.handle_wheel_tasks(http_client=http_client)

                    user_new_info = await self.get_balance(http_client=http_client, ref_id=profiles[self.session_name]['ref_id'])
                    if user_new_info['result']['tickets'] > 0:
                        logger.info(f"{self.session_name} | Begin to spin wheel ...")
                        await self.spin_all_tickets(http_client=http_client, tickets=user_info['result']['tickets'])
                    else:
                        logger.info(f"{self.session_name} | Không có ticket nào để xoay vòng quay!")
                else:
                    logger.warning(f"{self.session_name} | Could not get user info! Sleep 30s until the next login!")
                    await asyncio.sleep(delay=30)
                    continue

                logger.success(f'{self.session_name} | Sleep <light-red>30m.</light-red>')
                await asyncio.sleep(delay=1800)
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()
            except InvalidSession as error:
                raise error

            except Exception as error:
                logger.error(f"{self.session_name} | Unknown error: {error}")
                await asyncio.sleep(delay=3)
                logger.info(f'{self.session_name} | Sleep <light-red>3m.</light-red>')
                await asyncio.sleep(180)

async def run_tapper(tg_client: Client):
    proxy = None
    if settings.ENABLE_PROXY:
        proxy_data = profiles[tg_client.name]['proxy'].strip()
        if proxy_data:
            proxy = Proxy.from_str(proxy=proxy_data).as_url
            logger.info(f"{tg_client.name} | Run bot with this proxy: {proxy}")
        else:
            logger.warning(f"{tg_client.name} | The proxy is empty!")
    else:
        proxy = None

    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
