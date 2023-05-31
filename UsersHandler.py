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

import logging

import JSONReaderWriter


def get_key_or_none(dictionary: dict, key):
    """
    Safely gets value of key from dictionary
    :param dictionary:
    :param key:
    :return: key value or None if not found
    """
    if key is None:
        return None

    if key in dictionary:
        return dictionary[key]

    return None


class UsersHandler:
    def __init__(self, config: dict):
        self.config = config

    def read_users(self) -> list:
        """
        Reads users data from database
        :return: users as list of dictionaries or [] if not found
        """
        users = JSONReaderWriter.load_json(self.config["users_database"])
        if users is None:
            return []
        return users

    def get_user_by_id(self, id_: int) -> dict:
        """
        Returns user (or create new one) as dictionary from database using user_id
        :param id_: user_id as integer
        :return: dictionary
        """
        users = self.read_users()
        for user in users:
            if user["id"] == id_:
                return user

        # If we are here then user doesn't exist
        return self._create_user(id_)

    def save_user(self, user_data: dict) -> None:
        """
        Saves user_data to database
        :param user_data:
        :return:
        """
        if user_data is None:
            return

        users = self.read_users()
        user_index = -1
        for i in range(len(users)):
            if users[i]["id"] == user_data["id"]:
                user_index = i
                break

        # User exists
        if user_index >= 0:
            new_keys = user_data.keys()
            for new_key in new_keys:
                users[user_index][new_key] = user_data[new_key]

        # New user
        else:
            users.append(user_data)

        # Save to database
        JSONReaderWriter.save_json(self.config["users_database"], users)

    def _create_user(self, id_: int) -> dict:
        """
        Creates and saves new user
        :param id_: user_id as integer
        :return:
        """
        logging.warning("Creating new user with id: {0}".format(id_))
        user = {
            "id": id_,
            "username": "",
            "full_name": "",
            "admin": False,
            "banned": False,
            "messages_total": 0
        }
        self.save_user(user)
        return user
