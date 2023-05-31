"""
 Copyright (C) 2023 Fern Lane, Telegram-blockpost-bot
 Licensed under the GNU Affero General Public License, Version 3.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
       https://www.gnu.org/licenses/agpl-3.0.en.html
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
 IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR
 OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
 ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 OTHER DEALINGS IN THE SOFTWARE.
"""

import asyncio
import logging
import threading
import time

import telegram
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

import UsersHandler

# User commands
BOT_COMMAND_START = "start"
BOT_COMMAND_CHAT_ID = "chatid"

# Admin-only commands
BOT_COMMAND_ADMIN_USERS = "users"
BOT_COMMAND_ADMIN_RESETMESSAGES = "resetmessages"
BOT_COMMAND_ADMIN_BAN = "ban"
BOT_COMMAND_ADMIN_UNBAN = "unban"
BOT_COMMAND_ADMIN_RESTART = "restart"

# After how many seconds restart bot polling if error occurs
RESTART_ON_ERROR_DELAY = 10

# Telegram bot internal polling timeout
WRITE_READ_TIMEOUT = 30


async def _send_safe(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends message without raising any error
    :param chat_id:
    :param context:
    :return:
    """
    try:
        await context.bot.send_message(chat_id=chat_id,
                                       text=text.replace("\\n", "\n").replace("\\t", "\t"))
    except Exception as e:
        logging.error("Error sending {0} to {1}!".format(text.replace("\\n", "\n").replace("\\t", "\t"), chat_id),
                      exc_info=e)


class BotHandler:
    def __init__(self, config: dict, users_handler: UsersHandler.UsersHandler, ):
        self.config = config
        self.users_handler = users_handler

        self._application = None
        self._event_loop = None
        self._restart_requested_flag = False
        self._form_message = ""

    def start_bot(self):
        """
        Starts bot (blocking)
        :return:
        """
        # Start telegram bot polling (exit by CTRL+C)
        while True:
            try:
                # Read form message
                form_file = open(self.config["form_file"], "r", encoding="utf-8")
                self._form_message = form_file.read()
                form_file.close()

                # Build bot
                logging.warning("Starting telegram bot")
                builder = ApplicationBuilder().token(self.config["api_key"])
                builder.write_timeout(WRITE_READ_TIMEOUT)
                builder.read_timeout(WRITE_READ_TIMEOUT)
                self._application = builder.build()

                # User commands
                self._application.add_handler(CommandHandler(BOT_COMMAND_START,
                                                             self.bot_command_start))
                self._application.add_handler(CommandHandler(BOT_COMMAND_CHAT_ID,
                                                             self.bot_command_chatid))

                # Message from user (redirect to admins)
                self._application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND),
                                                             self.bot_message))

                # Admin commands
                self._application.add_handler(CommandHandler(BOT_COMMAND_ADMIN_USERS,
                                                             self.bot_command_users))
                self._application.add_handler(CommandHandler(BOT_COMMAND_ADMIN_BAN,
                                                             self.bot_command_ban))
                self._application.add_handler(CommandHandler(BOT_COMMAND_ADMIN_UNBAN,
                                                             self.bot_command_unban))
                self._application.add_handler(CommandHandler(BOT_COMMAND_ADMIN_RESTART,
                                                             self.bot_command_restart))
                self._application.add_handler(CommandHandler(BOT_COMMAND_ADMIN_RESETMESSAGES,
                                                             self.bot_command_resetmessages))

                # Unknown command -> ignore

                # Start bot
                self._event_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._event_loop)
                self._event_loop.run_until_complete(self._application.run_polling())

            # Exit requested
            except KeyboardInterrupt:
                logging.warning("KeyboardInterrupt @ bot_start")
                break

            # Bot error?
            except Exception as e:
                if "Event loop is closed" in str(e):
                    if not self._restart_requested_flag:
                        logging.warning("Stopping telegram bot")
                        break
                else:
                    logging.error("Telegram bot error!", exc_info=e)

            # Wait before restarting if needed
            if not self._restart_requested_flag:
                logging.warning("Restarting bot polling after {0} seconds".format(RESTART_ON_ERROR_DELAY))
                try:
                    time.sleep(RESTART_ON_ERROR_DELAY)
                # Exit requested while waiting for restart
                except KeyboardInterrupt:
                    logging.warning("KeyboardInterrupt @ bot_start")
                    break

            # Restart bot
            logging.warning("Restarting bot polling")
            self._restart_requested_flag = False

        # If we're here, exit requested
        logging.warning("Telegram bot stopped")

    async def bot_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Text message from user
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log without context
        logging.warning("Text message from {0} ({1}) ({2})".format(user["full_name"], user["username"], user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Ignore admins
        if user["admin"]:
            return

        # Increment user messages counter
        user["messages_total"] += 1

        # Save user
        self.users_handler.save_user(user)

        # Check messages limit
        if user["messages_total"] <= self.config["user_max_messages"]:
            # Extract text from message
            message_text = str(update.message.text)

            # Get list of users
            users = self.users_handler.read_users()

            # Add user info to message
            message_text = "{0} (@{1}) ({2})\n\n".format(user["full_name"], user["username"], user["id"]) + message_text

            # Broadcast to admins
            for broadcast_user in users:
                if broadcast_user["admin"]:
                    logging.warning("Sending user request to {0} ({1}) ({2})".format(broadcast_user["full_name"],
                                                                                     broadcast_user["username"],
                                                                                     broadcast_user["id"]))
                    await _send_safe(broadcast_user["id"], message_text, context)

            # Send confirmation
            await _send_safe(user["id"], self.config["confirmation_message"], context)

    async def bot_command_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.bot_command_ban_unban(True, update, context)

    async def bot_command_unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.bot_command_ban_unban(False, update, context)

    async def bot_command_ban_unban(self, ban: bool, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /ban, /unban commands
        :param ban: True to ban, False to unban
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/{0} command from {1} ({2}) ({3})".format("ban" if ban else "unban",
                                                                   user["full_name"],
                                                                   user["username"],
                                                                   user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Check for admin rules
        if not user["admin"]:
            return

        # Check user_id to ban
        if not context.args or len(context.args) < 1:
            return
        try:
            ban_user_id = int(str(context.args[0]).strip())
        except Exception as e:
            await _send_safe(user["id"], str(e), context)
            return

        # Get user to ban
        banned_user = self.users_handler.get_user_by_id(ban_user_id)

        # Ban / unban
        banned_user["banned"] = ban

        # Save user
        self.users_handler.save_user(banned_user)

        # Send confirmation
        if ban:
            await _send_safe(user["id"], self.config["ban_confirmation_message"], context)
        else:
            await _send_safe(user["id"], self.config["unban_confirmation_message"], context)

    async def bot_command_resetmessages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /resetmessages command
        :param update: 
        :param context: 
        :return: 
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/resetmessages command from {0} ({1}) ({2})".format(user["full_name"],
                                                                             user["username"],
                                                                             user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Check for admin rules
        if not user["admin"]:
            return

        # Check user_id to reset
        if not context.args or len(context.args) < 1:
            return
        try:
            reset_user_id = int(str(context.args[0]).strip())
        except Exception as e:
            await _send_safe(user["id"], str(e), context)
            return

        # Get user to reset
        reset_user = self.users_handler.get_user_by_id(reset_user_id)

        # Reset messages limit
        reset_user["messages_total"] = 0

        # Save user
        self.users_handler.save_user(reset_user)

        # Send confirmation
        await _send_safe(user["id"], self.config["resetmessages_confirmation_message"], context)

    async def bot_command_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /users command
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/users command from {0} ({1}) ({2})".format(user["full_name"], user["username"], user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Check for admin rules
        if not user["admin"]:
            return

        # Get list of users
        users = self.users_handler.read_users()

        # Add them to message
        message = "id\tUsername\tFull name\tAdmin?\tBanned?\tTotal messages\n\n"
        for user_info in users:
            message += "{0}\t@{1}\t{2}\t{3}\t{4}\t{5}\n".format(user_info["id"],
                                                                user_info["username"],
                                                                user_info["full_name"],
                                                                user_info["admin"],
                                                                user_info["banned"],
                                                                user_info["messages_total"])

        # Send list of users
        await _send_safe(user["id"], message, context)

    async def bot_command_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /restart command
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/restart command from {0} ({1}) ({2})".format(user["full_name"], user["username"], user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Check for admin rules
        if not user["admin"]:
            return

        # Send restarting message
        logging.warning("Restarting")
        await _send_safe(user["id"], self.config["restart_message_start"], context)

        # Restart telegram bot
        self._restart_requested_flag = True
        self._event_loop.stop()
        try:
            self._event_loop.close()
        except:
            pass

        def send_message_after_restart():
            # Sleep while restarting
            while self._restart_requested_flag:
                time.sleep(1)

            # Done?
            logging.warning("Restarting done")
            try:
                asyncio.run(telegram.Bot(self.config["api_key"])
                            .sendMessage(chat_id=user["id"],
                                         text=self.config["restart_message_done"].replace("\\n", "\n")))
            except Exception as e:
                logging.error("Error sending message!", exc_info=e)

        threading.Thread(target=send_message_after_restart).start()

    async def bot_command_chatid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /chatid command
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/chatid command from {0} ({1}) ({2})".format(user["full_name"], user["username"], user["id"]))

        # Send chat id and not exit if banned
        await _send_safe(user["id"], str(user["id"]), context)

    async def bot_command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /start command
        :param update:
        :param context:
        :return:
        """
        # Get user
        user = await self._user_check_get(update, context)

        # Log command
        logging.warning("/start command from {0} ({1}) ({2})".format(user["full_name"], user["username"], user["id"]))

        # Exit if banned
        if user["banned"]:
            return

        # Send start message (form) or admin help
        if user["admin"]:
            await _send_safe(user["id"], self.config["admin_message"], context)
        else:
            await _send_safe(user["id"], self._form_message, context)

    async def _user_check_get(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
        """
        Gets (or creates) user based on update.effective_chat.id and checks if they are banned or not
        :param update:
        :param context:
        :return: user as dictionary
        """
        # Get user (or create a new one)
        telegram_chat_id = update.effective_chat.id
        telegram_user_username = update.message.from_user.username if update.message is not None else None
        telegram_user_full_name = update.message.from_user.full_name if update.message is not None else None

        user = self.users_handler.get_user_by_id(telegram_chat_id)

        # Update username and full_name
        if telegram_user_username is not None:
            user["username"] = str(telegram_user_username)
            self.users_handler.save_user(user)
        if telegram_user_full_name is not None:
            user["full_name"] = str(telegram_user_full_name)
            self.users_handler.save_user(user)

        # Send banned message
        if user["banned"]:
            banned_message = str(self.config["banned_message"]).strip()
            if len(banned_message) > 0:
                await _send_safe(telegram_chat_id, banned_message, context)

        return user
